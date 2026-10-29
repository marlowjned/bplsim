"""Slurm executor (plan §11.3): one job array per round; each array task runs one task file on one node,
with `bplsim run-task --workers <slots>` packing several jobs onto the node.

Site profile (example §14):

    executor: slurm
    slurm:
      partition: savio3
      account: fc_<pi>
      qos: savio_normal               # optional
      cpus_per_node: 32
      memory_per_node: 96 GB
      max_walltime: "72:00:00"
      max_concurrent_tasks: 20
      setup: ["module load python"]   # optional shell lines before the run
      commands: {sbatch: sbatch, squeue: squeue, sacct: sacct}   # override for testing
    container: /path/bplsim.sif       # optional: run inside `apptainer exec`
"""
from __future__ import annotations

import math
import re
import subprocess
import time
from pathlib import Path

from ..errors import ConfigError
from ..units import DEFAULT_UNITS, DIMS
from .local import TaskOutcome, TaskSpec, pack, slots


def _walltime(seconds: float) -> str:
    seconds = int(math.ceil(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_walltime(text: str) -> float:
    parts = [int(x) for x in str(text).replace("-", ":").split(":")]
    if len(parts) == 4:                          # d-hh:mm:ss
        d, h, m, s = parts
        return d * 86400 + h * 3600 + m * 60 + s
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


class SlurmExecutor:
    def __init__(self, site, poll: float = 15.0):
        self.site = site
        cfg = dict(site.slurm or {})
        for req in ("partition", "cpus_per_node"):
            if req not in cfg:
                raise ConfigError(f"site {site.name}: slurm.{req} is required")
        self.cfg = cfg
        mem = cfg.get("memory_per_node")
        self.mem = DEFAULT_UNITS.to_si(mem, DIMS["memory"]) if isinstance(mem, str) else (mem or 0)
        self.cpus = int(cfg["cpus_per_node"])
        self.max_wall = _parse_walltime(cfg.get("max_walltime", "24:00:00"))
        self.max_conc = int(cfg.get("max_concurrent_tasks", 50))
        self.cmd = {"sbatch": "sbatch", "squeue": "squeue", "sacct": "sacct", **(cfg.get("commands") or {})}
        self.poll = float(cfg.get("poll_s", poll))
        self.workers = self.cpus
        self._slots = 1
        self._runtime = 60.0

    # same interface as LocalExecutor ------------------------------------------------------------
    def capacity(self, cores_per_job: int, mem_per_job: float) -> int:
        self._slots = slots(self.cpus, self.mem, cores_per_job, mem_per_job)
        return self._slots

    def partition(self, n_groups: int, n_slots: int, runtime: float, resources: dict) -> list[int]:
        """Plan packing rule: slots x k jobs per task, k making a task last >= 10 min (min_task)."""
        self._runtime = runtime
        return pack(n_groups, n_slots, runtime, min_task=float(resources.get("min_task", 600.0)),
                    max_tasks=self.max_conc)

    def run(self, tasks: list[TaskSpec], parallel: int | None = None) -> list[TaskOutcome]:
        if not tasks:
            return []
        d = tasks[0].path.parent
        per_task_jobs = max(t.n_jobs for t in tasks)
        est = per_task_jobs / max(1, self._slots) * self._runtime * 1.5 + 300
        wall = min(self.max_wall, max(est, max((t.timeout or 0) for t in tasks)))
        names = " ".join(f'"{t.path.as_posix()}"' for t in tasks)
        run = f'bplsim run-task "${{TASKS[$SLURM_ARRAY_TASK_ID]}}" --workers {self._slots}'
        if self.site.container:
            run = f'apptainer exec "{self.site.container}" {run}'
        lines = ["#!/bin/bash", f"#SBATCH --job-name=bplsim-{d.parent.parent.parent.name[:40]}",
                 f"#SBATCH --array=0-{len(tasks) - 1}%{self.max_conc}", f"#SBATCH --partition={self.cfg['partition']}",
                 "#SBATCH --nodes=1", f"#SBATCH --cpus-per-task={self.cpus}", f"#SBATCH --time={_walltime(wall)}",
                 f"#SBATCH --output={d.as_posix()}/slurm-%A_%a.out"]
        if self.cfg.get("account"):
            lines.append(f"#SBATCH --account={self.cfg['account']}")
        if self.cfg.get("qos"):
            lines.append(f"#SBATCH --qos={self.cfg['qos']}")
        if self.mem:
            lines.append(f"#SBATCH --mem={int(self.mem // 1024 ** 2)}M")
        lines += list(self.cfg.get("setup") or [])
        for name, path in (self.site.tools or {}).items():
            lines.append(f'export BPLSIM_TOOL_{name.upper()}="{path}"')
        lines += ["export OMP_NUM_THREADS=1", f"TASKS=({names})", run]
        script = d / "submit.sh"
        script.write_text("\n".join(lines) + "\n", newline="\n")
        r = subprocess.run([*self.cmd["sbatch"].split(), "--parsable", str(script)], capture_output=True, text=True)
        if r.returncode != 0:
            raise ConfigError(f"sbatch failed: {r.stderr.strip() or r.stdout.strip()}")
        job = r.stdout.strip().split(";")[0]
        (d / "slurm_job_id").write_text(job)
        t0 = time.time()
        while True:
            q = subprocess.run([*self.cmd["squeue"].split(), "-h", "-j", job, "-o", "%i %T"],
                               capture_output=True, text=True)
            if q.returncode == 0 and not q.stdout.strip():
                break
            time.sleep(self.poll)
        states = self._states(job)
        out = []
        for i, t in enumerate(tasks):
            st = states.get(i, "UNKNOWN")
            rc = 0 if st == "COMPLETED" else 1
            out.append(TaskOutcome(t.path, rc, st == "TIMEOUT", time.time() - t0, d / f"slurm-{job}_{i}.out"))
        return out

    def _states(self, job: str) -> dict[int, str]:
        r = subprocess.run([*self.cmd["sacct"].split(), "-n", "-P", "-X", "-j", job, "-o", "JobID,State"],
                           capture_output=True, text=True)
        out = {}
        for line in r.stdout.splitlines():
            m = re.match(rf"{re.escape(job)}_(\d+)\|(\w+)", line.strip())
            if m:
                out[int(m.group(1))] = m.group(2)
        return out
