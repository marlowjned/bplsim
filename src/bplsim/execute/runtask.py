"""The worker entry point: run the jobs of a task file (plan §11.2).

A task file is JSON: {"project": <library snapshot project dir>, "data_root": ..., "jobs": [...]}.
Jobs are fully resolved; workers never re-resolve studies. Case jobs solve and measure; run jobs
combine, normalize and compute metrics.
"""
from __future__ import annotations

import os
import shutil
import socket
import time
import traceback
from pathlib import Path

import h5py

from ..backends import get_backend
from ..backends.base import Basis
from ..errors import BplsimError
from ..measure.data import ProbeData
from ..measure.engine import MetricDef, ProbeDef, compute_metrics, evaluate_probe, normalize
from ..project import Project
from ..resolve import ResolvedDesign
from .folders import DataRoot, publish, read_json, write_json
from .locks import Lock

_PROJECTS: dict[str, Project] = {}


def _project(path: str) -> Project:
    if path not in _PROJECTS:
        _PROJECTS.clear()
        _PROJECTS[path] = Project.load(path)
    return _PROJECTS[path]


def _stamp() -> dict:
    return {"host": socket.gethostname(), "pid": os.getpid(), "time": time.time()}


# ---- case jobs ------------------------------------------------------------------------------------
def read_case_data(case_dir: Path, hashes) -> dict[str, dict[str, ProbeData]]:
    out = {}
    with h5py.File(case_dir / "measurements.h5", "r") as f:
        for h in hashes:
            if h not in f:
                raise KeyError(h)
            out[h] = {b: ProbeData.from_h5(f[h][b]) for b in f[h]}
    return out


def _measured(case_dir: Path) -> set[str]:
    p = case_dir / "measurements.h5"
    if not p.exists():
        return set()
    with h5py.File(p, "r") as f:
        return set(f.keys())


def _measure(project, backend, job, workdir: Path, probes: list[dict], h5path: Path):
    design = ResolvedDesign.from_canonical(project, job["design"])
    bases = [Basis(b["name"], b["currents"]) for b in job["bases"]]
    with h5py.File(h5path, "a") as f:
        for pc in probes:
            if pc["hash"] in f:
                continue
            pdef = ProbeDef(pc["alias"], pc["probe"], pc["version"], pc["params"])
            g = f.create_group(pc["hash"])
            g.attrs["probe"], g.attrs["alias"], g.attrs["version"] = pc["probe"], pc["alias"], pc["version"]
            for b in bases:
                sol = backend.field_access(job["inputs"], workdir / "raw", b)
                evaluate_probe(project, design, pdef, sol).to_h5(g.create_group(b.name))


def run_case(project, root: DataRoot, job: dict) -> str:
    h = job["case_hash"]
    final = root.case_dir(h)
    backend = get_backend(job["backend"])
    if root.done(final):
        missing = [p for p in job["probes"] if p["hash"] not in _measured(final)]
        if not missing:
            return "cached"
        if not (final / "raw").exists() and job.get("needs_raw", True):
            shutil.rmtree(final, ignore_errors=True)          # raw purged: solve again
        else:
            with Lock(final.parent / (h + ".lock")) as lk:
                if not lk.acquire():
                    return "busy"
                _measure(project, backend, job, final, missing, final / "measurements.h5")
            return "remeasured"
    lock = Lock(final.parent / (h + ".lock"))
    if not lock.acquire():
        return "busy"
    tmp = final.parent / f"{h}.tmp-{socket.gethostname()}-{os.getpid()}"
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "raw").mkdir(parents=True)
        t0, c0 = time.time(), time.process_time()
        write_json(tmp / "case.json", {"case_hash": h, "backend": job["backend"], "backend_version": backend.version,
                                       "tool_version": backend.tool_version(), "stage": job["stage"],
                                       "inputs": job["inputs"], "bases": job["bases"], "provenance": job.get("provenance", {}),
                                       "started": _stamp()})
        backend.prepare(job["inputs"], tmp / "raw")
        for b in job["bases"]:
            res = backend.execute(job["inputs"], tmp / "raw", Basis(b["name"], b["currents"]), job.get("resources", {}))
            if res.status != "ok":
                return _fail(root, tmp, h, "failed" if res.status == "failed" else res.status, res.reason)
        _measure(project, backend, job, tmp, job["probes"], tmp / "measurements.h5")
        write_json(tmp / "status.json", {"status": "done", "wall_s": time.time() - t0,
                                         "cpu_s": time.process_time() - c0, "finished": _stamp()})
        (tmp / "DONE").write_text("")
        if job.get("retention", {}).get("raw") == "purge_on_success" and not job.get("pinned"):
            shutil.rmtree(tmp / "raw", ignore_errors=True)
        publish(tmp, final)
        return "done"
    except Exception as e:  # noqa: BLE001 - every failure is recorded, then the next job runs
        return _fail(root, tmp, h, "failed", f"{type(e).__name__}: {e}", traceback.format_exc())
    finally:
        lock.release()


def _fail(root: DataRoot, tmp: Path, h: str, status: str, reason: str, tb: str = "") -> str:
    fd = root.failed_dir(h)
    shutil.rmtree(fd, ignore_errors=True)
    fd.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        shutil.move(str(tmp), str(fd))
    fd.mkdir(parents=True, exist_ok=True)
    write_json(fd / "status.json", {"status": status, "reason": reason, "traceback": tb, "finished": _stamp()})
    return status


# ---- run jobs -------------------------------------------------------------------------------------
def run_run(project, root: DataRoot, job: dict) -> str:
    h = job["run_hash"]
    final = root.run_dir(h)
    if root.done(final):
        return "cached"
    case_dir = root.case_dir(job["case_hash"])
    tmp = final.parent / f"{h}.tmp-{socket.gethostname()}-{os.getpid()}"
    try:
        if not root.done(case_dir):
            st = root.failed_dir(job["case_hash"]) / "status.json"
            reason = read_json(st)["reason"] if st.exists() else "case not solved"
            return _fail_run(root, h, "failed", f"case {job['case_hash'][:12]}: {reason}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        design = ResolvedDesign.from_canonical(project, job["design"])
        mdefs = {}
        for mc in job["metrics"]:
            md = MetricDef(mc["alias"], mc["metric"], mc["version"], mc["inputs"], mc["params"], mc["input_hashes"],
                           outputs=mc.get("outputs", {}))
            md.finish()
            mdefs[md.alias] = md
        hashes = {h2 for md in mdefs.values() for h2 in md.input_hashes.values()}
        case_data = read_case_data(case_dir, hashes)
        normalized = {}
        if job.get("normalize"):
            normalized = normalize(project, design, mdefs, case_data, job["bases"], job["normalize"], job["superposed"])
        metrics = compute_metrics(project, design, mdefs, case_data, job["bases"])
        flat = {}
        for alias, outs in metrics.items():
            md = mdefs[alias]
            for k, v in outs.items():
                unit = md.outputs.get(k, "") if isinstance(md.outputs, dict) else ""
                flat[f"{alias}.{k}"] = {"value": _plain(v), "unit": unit, "metric": md.metric_id,
                                        "version": md.version, "definition": md.def_hash}
        write_json(tmp / "run.json", {"run_hash": h, "case_hash": job["case_hash"], "stage": job["stage"],
                                      "design": job["design"], "normalized": normalized, "bases": job["bases"],
                                      "provenance": job.get("provenance", {}), "finished": _stamp()})
        write_json(tmp / "metrics.json", flat)
        write_json(tmp / "status.json", {"status": "done"})
        (tmp / "DONE").write_text("")
        publish(tmp, final)
        return "done"
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return _fail_run(root, h, "failed", f"{type(e).__name__}: {e}", traceback.format_exc())


def _fail_run(root, h, status, reason, tb=""):
    fd = root.failed_dir(h)
    fd.mkdir(parents=True, exist_ok=True)
    write_json(fd / "status.json", {"status": status, "reason": reason, "traceback": tb, "finished": _stamp(),
                                    "kind": "run"})
    return status


def _plain(v):
    try:
        import numpy as np
        if isinstance(v, (np.floating, np.integer)):
            return v.item()
    except ImportError:
        pass
    return v


def _run_group(project_dir: str, data_root: str, group: list[dict]) -> dict[str, str]:
    project = _project(project_dir)
    root = DataRoot(data_root)
    out = {}
    for job in group:
        if job["type"] == "case":
            out[job["case_hash"]] = run_case(project, root, job)
        else:
            out[job["run_hash"]] = run_run(project, root, job)
    return out


def run_task(task_file: str | Path, jobs: str | None = None, workers: int = 1) -> dict[str, str]:
    """Run a task's jobs. With workers > 1 (one node of a Slurm array task), groups of jobs (a case with
    its runs) run in parallel processes."""
    task = read_json(Path(task_file))
    sel = task["jobs"]
    if jobs:
        lo, _, hi = jobs.partition("-")
        sel = sel[int(lo): int(hi or lo) + 1]
    groups: dict[str, list[dict]] = {}
    for job in sel:
        key = job["case_hash"] if job["type"] == "case" or job["case_hash"] in groups else "run:" + job["run_hash"]
        groups.setdefault(key, []).append(job)
    if workers <= 1 or len(groups) <= 1:
        return _run_group(task["project"], task["data_root"], sel)
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    out: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(groups)), mp_context=mp.get_context("spawn")) as ex:
        for res in ex.map(_run_group, [task["project"]] * len(groups), [task["data_root"]] * len(groups),
                          list(groups.values())):
            out.update(res)
    return out
