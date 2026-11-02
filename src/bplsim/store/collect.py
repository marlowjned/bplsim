"""Index case and run folders into the database. Idempotent; --rebuild recreates the database."""
from __future__ import annotations

import json
from pathlib import Path

from bplsim.execute.folders import DataRoot, read_json
from bplsim.store.db import DB, split_value


def _flatten_design(canon: dict) -> dict:
    out = {}
    for p, v in canon.get("values", {}).items():
        if isinstance(v, dict) and "material" in v:
            v = v["material"]
        out[p] = (v, canon.get("dims", {}).get(p, ""))
    for p, v in canon.get("normalized", {}).items():
        out[p] = (v, canon.get("dims", {}).get(p, ""))
        out[f"normalized.{p}"] = (v, canon.get("dims", {}).get(p, ""))
    for slot, tid in canon.get("slots", {}).items():
        out[f"parts.{slot}"] = (tid, "")
    return out


def collect(root: DataRoot, db: DB, only_new: bool = True) -> dict[str, int]:
    known_runs = {r[0] for r in db.execute("SELECT run_id FROM runs WHERE status='done'")} if only_new else set()
    known_cases = {r[0] for r in db.execute("SELECT case_id FROM cases WHERE status='done'")} if only_new else set()
    n = {"cases": 0, "runs": 0, "failed": 0}
    for done in root.root.glob("cases/*/*/DONE"):
        d = done.parent
        h = d.name
        if h in known_cases:
            continue
        info = read_json(d / "case.json")
        st = read_json(d / "status.json")
        db.upsert("cases", {"case_id": h, "backend": info["backend"], "backend_version": info["backend_version"],
                            "status": "done", "reason": None, "path": str(d), "wall_s": st.get("wall_s"),
                            "cpu_s": st.get("cpu_s"), "raw_retained": int((d / "raw").exists()),
                            "provenance_json": info.get("provenance", {})})
        n["cases"] += 1
    for done in root.root.glob("runs/*/*/DONE"):
        d = done.parent
        h = d.name
        if h in known_runs:
            continue
        info = read_json(d / "run.json")
        metrics = read_json(d / "metrics.json")
        db.upsert("runs", {"run_id": h, "case_id": info["case_hash"], "stage": info["stage"], "status": "done",
                           "error": None, "path": str(d), "normalized_json": info.get("normalized", {}),
                           "provenance_json": info.get("provenance", {}),
                           "finished": info.get("finished", {}).get("time")})
        db.execute("DELETE FROM params WHERE run_id=?", [h])
        design = dict(info["design"])
        design["normalized"] = info.get("normalized", {})
        for p, (v, unit) in _flatten_design(design).items():
            num, text = split_value(v)
            db.upsert("params", {"run_id": h, "path": p, "value_num": num, "value_text": text, "unit": unit})
        db.execute("DELETE FROM metrics WHERE run_id=?", [h])
        for name, m in metrics.items():
            num, text = split_value(m["value"])
            db.upsert("metrics", {"run_id": h, "name": name, "definition_hash": m["definition"],
                                  "metric_id": m["metric"], "metric_version": m["version"], "value_num": num,
                                  "value_text": text, "unit": m.get("unit", ""), "stale": 0})
        n["runs"] += 1
    for st in root.root.glob("failed/*/status.json"):
        h = st.parent.name
        info = read_json(st)
        if info.get("kind") == "run":
            if not (root.run_dir(h) / "DONE").exists():
                db.upsert("runs", {"run_id": h, "case_id": None, "stage": None, "status": info["status"],
                                   "error": info.get("reason"), "path": str(st.parent), "normalized_json": None,
                                   "provenance_json": None, "finished": info.get("finished", {}).get("time")})
        elif not (root.case_dir(h) / "DONE").exists():
            db.upsert("cases", {"case_id": h, "backend": None, "backend_version": None, "status": info["status"],
                                "reason": info.get("reason"), "path": str(st.parent), "wall_s": None, "cpu_s": None,
                                "raw_retained": 0, "provenance_json": None})
        n["failed"] += 1
    db.commit()
    return n


def rebuild(root: DataRoot) -> dict[str, int]:
    """Drop the case/run/param/metric index and rebuild it from the folders (studies and rows are kept)."""
    db = DB(root.db_path)
    for t in ("cases", "runs", "params", "metrics"):
        db.execute(f"DELETE FROM {t}")
    out = collect(root, db, only_new=False)
    db.close()
    return out
