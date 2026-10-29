"""Queries over the trade database: wide tables, `where` filters with units, Pareto fronts."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..expr import Expr
from .db import DB

_UNIT_LIT = re.compile(r"(?<![\w.])(\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+([A-Za-z][A-Za-z0-9_*/^]*)")


def _si_literals(text: str, units) -> str:
    def rep(m):
        num, unit = m.group(1), m.group(2)
        if unit in ("and", "or", "not", "if", "else", "in"):
            return m.group(0)
        try:
            q = units.parse(f"{num} {unit}")
        except ValueError:
            return m.group(0)
        return repr(float(q.to_base_units().magnitude))
    return _UNIT_LIT.sub(rep, text)


def _pivot(rows, key: str, name: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["value"] = df["value_num"].where(df["value_num"].notna(), df["value_text"])
    return df.pivot_table(index=key, columns=name, values="value", aggfunc="first")


def wide(db: DB, run_ids: list[str] | None = None, metrics: list[str] | None = None) -> pd.DataFrame:
    cond, args = "", []
    if run_ids is not None:
        if not run_ids:
            return pd.DataFrame()
        cond = f" WHERE run_id IN ({','.join('?' * len(run_ids))})"
        args = list(run_ids)
    p = _pivot(db.query("SELECT run_id, path, value_num, value_text FROM params" + cond, args), "run_id", "path")
    mq = "SELECT run_id, name, value_num, value_text FROM metrics" + cond
    m = _pivot(db.query(mq, args), "run_id", "name")
    if metrics is not None and len(m):
        m = m[[c for c in metrics if c in m.columns]]
    df = p.join(m, how="outer") if len(p) else m
    df.index.name = "run_id"
    return df.reset_index()


def study_table(db: DB, study_id: str) -> pd.DataFrame:
    """One line per row: study variables, status, the final stage's run_id, and the metrics of all its
    stages' runs."""
    rows = db.query("SELECT row_id, round, status, invalid_reason FROM rows WHERE study_id = ? ORDER BY row_id",
                    [study_id])
    base = pd.DataFrame([dict(r) for r in rows])
    if base.empty:
        return base
    rr = db.query("SELECT row_id, stage, run_id, stage_index FROM row_runs WHERE study_id = ?", [study_id])
    last = {}
    for r in sorted(rr, key=lambda x: (x["row_id"], x["stage_index"] or 0)):
        last[r["row_id"]] = r["run_id"]
    base["run_id"] = base["row_id"].map(last)
    vals = _pivot(db.query("SELECT row_id, name, value_num, value_text FROM row_values WHERE study_id=?",
                           [study_id]), "row_id", "name")
    base = base.join(vals, on="row_id")
    run_ids = sorted({r["run_id"] for r in rr})
    if run_ids:
        m = _pivot(db.query(f"SELECT run_id, name, value_num, value_text FROM metrics WHERE run_id IN "
                            f"({','.join('?' * len(run_ids))})", run_ids), "run_id", "name")
        if len(m):
            run_row = pd.DataFrame([{"run_id": r["run_id"], "row_id": r["row_id"]} for r in rr])
            per_row = run_row.join(m, on="run_id").drop(columns="run_id").groupby("row_id").first()
            base = base.join(per_row, on="row_id")
    return base


def pareto_mask(df: pd.DataFrame, objectives: list[str]) -> np.ndarray:
    cols, signs = [], []
    for o in objectives:
        signs.append(-1.0 if o.startswith("-") else 1.0)
        cols.append(o.lstrip("-"))
    x = np.column_stack([pd.to_numeric(df[c], errors="coerce").to_numpy() * s for c, s in zip(cols, signs)])
    ok = np.all(np.isfinite(x), axis=1)
    mask = np.zeros(len(df), bool)
    idx = np.flatnonzero(ok)
    for i in idx:
        dominated = np.any(np.all(x[idx] <= x[i], axis=1) & np.any(x[idx] < x[i], axis=1))
        mask[i] = not dominated
    return mask


def query(db: DB, units, where: str | None = None, metrics: list[str] | None = None, study: str | None = None,
          pareto: list[str] | None = None) -> pd.DataFrame:
    run_ids = None
    if study:
        run_ids = [r["run_id"] for r in db.query("SELECT run_id FROM row_runs WHERE study_id LIKE ?",
                                                  [study if "%" in study else f"%{study}%"])]
    df = wide(db, run_ids, None)
    if df.empty:
        return df
    if where:
        e = Expr("${ " + _si_literals(where, units) + " }", "query")
        keep = []
        for _, row in df.iterrows():
            def look(path, row=row):
                if path in row.index:
                    v = row[path]
                    return None if (isinstance(v, float) and np.isnan(v)) else v
                if any(c.startswith(path + ".") for c in row.index):
                    present = any(isinstance(row[c], str) or pd.notna(row[c]) for c in row.index
                                  if c.startswith(path + "."))
                    return True if present else None
                return None
            try:
                keep.append(bool(e.evaluate(look)))
            except Exception:  # noqa: BLE001 - a row lacking a value simply does not match
                keep.append(False)
        df = df[np.array(keep, bool)]
    if metrics:
        base_cols = [c for c in df.columns if not any(c == m for m in metrics)]
        df = df[[c for c in df.columns if c == "run_id" or c in metrics or c.startswith(("parts.", "params.", "op."))]]
    if pareto:
        df = df.assign(pareto=pareto_mask(df, pareto))
    return df.reset_index(drop=True)
