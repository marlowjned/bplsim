"""Executors and packing (plan §11.3).

Every executor runs tasks through the same CLI entry point (`python -m bplsim run-task`), so local
runs, cloud VMs and Slurm behave identically. Each task is a separate process: a crash or timeout
kills only that task, and finished jobs are already safely published.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .folders import write_json


@dataclass
class TaskSpec:
    path: Path
    n_jobs: int
    cores: int = 1
    memory: float = 0.0          # bytes per job
    timeout: float | None = None  # seconds for the whole task
    log: Path | None = None


@dataclass
class TaskOutcome:
    path: Path
    returncode: int | None
    timed_out: bool = False
    wall_s: float = 0.0
    log: Path | None = None


def slots(cpus: int, mem_bytes: float, cores_per_job: int, mem_per_job: float) -> int:
    by_cpu = max(1, cpus // max(1, int(cores_per_job)))
    by_mem = max(1, int(mem_bytes // mem_per_job)) if mem_per_job and mem_bytes else by_cpu
    return max(1, min(by_cpu, by_mem))


def pack(n_jobs: int, n_slots: int, runtime: float, min_task: float = 600.0, max_tasks: int | None = None) -> list[int]:
    """Jobs per task: slots x k, k the smallest integer making a task last >= min_task seconds."""
    if n_jobs <= 0:
        return []
    k = max(1, math.ceil(min_task / max(runtime, 1e-6))) if runtime < min_task else 1
    per = n_slots * k
    n_tasks = math.ceil(n_jobs / per)
    if max_tasks:
        n_tasks = max(n_tasks, min(max_tasks, math.ceil(n_jobs / n_slots)))
        n_tasks = min(n_tasks, n_jobs)
    sizes = [n_jobs // n_tasks + (1 if i < n_jobs % n_tasks else 0) for i in range(n_tasks)]
    return [s for s in sizes if s]


def write_task(path: Path, project_dir: str, data_root: str, jobs: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"project": str(project_dir), "data_root": str(data_root), "jobs": jobs})
    return path


class LocalExecutor:
    """Runs tasks as subprocesses, `workers` at a time."""

    def __init__(self, workers: int | None = None, memory_limit: float | None = None, python: str | None = None):
        self.cpus = os.cpu_count() or 2
        self.workers = workers or max(1, self.cpus - 1)
        self.memory_limit = memory_limit
        self.python = python or sys.executable

    def capacity(self, cores_per_job: int, mem_per_job: float) -> int:
        return min(self.workers, slots(self.workers, self.memory_limit or 0, cores_per_job, mem_per_job))

    def partition(self, n_groups: int, n_slots: int, runtime: float, resources: dict) -> list[int]:
        """Locally a task is one process running its jobs one after another: use one task per slot
        (at most one per job group), so every slot stays busy."""
        if n_groups <= 0:
            return []
        n_tasks = min(n_groups, n_slots)
        return [n_groups // n_tasks + (1 if i < n_groups % n_tasks else 0) for i in range(n_tasks)]

    def run(self, tasks: list[TaskSpec], parallel: int | None = None) -> list[TaskOutcome]:
        parallel = parallel or self.workers
        pending = list(tasks)
        running: list[tuple[subprocess.Popen, TaskSpec, float, object]] = []
        done: list[TaskOutcome] = []
        env = dict(os.environ, PYTHONUNBUFFERED="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                   MKL_NUM_THREADS="1")
        while pending or running:
            while pending and len(running) < parallel:
                t = pending.pop(0)
                log = t.log or t.path.with_suffix(".log")
                fh = open(log, "w")
                p = subprocess.Popen([self.python, "-m", "bplsim", "run-task", str(t.path)], stdout=fh,
                                     stderr=subprocess.STDOUT, env=env)
                running.append((p, t, time.time(), fh))
            time.sleep(0.05)
            still = []
            for p, t, t0, fh in running:
                rc = p.poll()
                elapsed = time.time() - t0
                if rc is None and t.timeout and elapsed > t.timeout:
                    p.kill()
                    p.wait()
                    fh.close()
                    done.append(TaskOutcome(t.path, None, True, elapsed, t.log or t.path.with_suffix(".log")))
                elif rc is not None:
                    fh.close()
                    done.append(TaskOutcome(t.path, rc, False, elapsed, t.log or t.path.with_suffix(".log")))
                else:
                    still.append((p, t, t0, fh))
            running = still
        return done


class InlineExecutor(LocalExecutor):
    """Runs tasks in this process, one after another (tests, debugging). No timeouts, no isolation."""

    def __init__(self, workers: int = 1):
        super().__init__(workers=workers)

    def run(self, tasks, parallel=None):
        from .runtask import run_task
        out = []
        for t in tasks:
            t0 = time.time()
            try:
                run_task(t.path)
                rc = 0
            except Exception:  # noqa: BLE001 - mirrors a crashed subprocess
                rc = 1
            out.append(TaskOutcome(t.path, rc, False, time.time() - t0))
        return out
