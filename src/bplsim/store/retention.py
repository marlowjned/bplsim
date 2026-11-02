"""Retention (plan §8.6, example §13): pin cases so their raw output is kept; garbage-collect raw output.

Raw solver output is purgeable: probes and metrics are stored separately, so deleting `raw/` only means a
probe added later needs a re-solve. Pinned cases (a PINNED file in the case folder) are never purged.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from bplsim.execute.folders import DataRoot, read_json


def pin(root: DataRoot, run_or_case: str, on: bool = True) -> Path:
    d = root.case_dir(run_or_case)
    if not d.exists():
        run = root.run_dir(run_or_case)
        if not run.exists():
            raise FileNotFoundError(f"no case or run {run_or_case[:12]}")
        d = root.case_dir(read_json(run / "run.json")["case_hash"])
    marker = d / "PINNED"
    if on:
        marker.write_text(time.ctime())
    elif marker.exists():
        marker.unlink()
    return d


def gc(root: DataRoot, raw_older_than_days: float = 14.0, dry_run: bool = False) -> dict:
    """Delete raw/ of unpinned, finished cases whose DONE marker is older than the limit."""
    limit = time.time() - raw_older_than_days * 86400
    freed, n = 0, 0
    for done in root.root.glob("cases/*/*/DONE"):
        d = done.parent
        raw = d / "raw"
        if not raw.exists() or (d / "PINNED").exists() or done.stat().st_mtime > limit:
            continue
        size = sum(f.stat().st_size for f in raw.rglob("*") if f.is_file())
        if not dry_run:
            shutil.rmtree(raw, ignore_errors=True)
        freed += size
        n += 1
    return {"cases": n, "freed_MB": round(freed / 2 ** 20, 1), "dry_run": dry_run}
