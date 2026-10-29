"""Reading results back: study tables, runs, and their probe data combined at the run's currents.

    from bplsim.analysis import Results
    res = Results(data_root)
    df = res.study_table("design_a_gap_sweep")
    run = res.run(df.run_id[0])
    prof = run.probe("profile")          # ProbeData combined with the run's (normalized) basis weights
"""
from __future__ import annotations

from pathlib import Path

import h5py
import pandas as pd

from .execute.folders import DataRoot, read_json
from .measure.data import ProbeData
from .measure.engine import basis_weights
from .store.db import DB
from .store.query import query, study_table


class _WeightDesign:
    """Minimal design stand-in for basis_weights: op values with normalization applied."""

    def __init__(self, canon: dict, normalized: dict):
        self.values = dict(canon["values"])
        self.values.update(canon.get("normalized", {}))
        self.values.update(normalized or {})

    def value(self, path):
        return self.values[path]


class RunView:
    def __init__(self, root: DataRoot, run_id: str):
        self.root, self.id = root, run_id
        self.dir = root.run_dir(run_id)
        self.info = read_json(self.dir / "run.json")
        self.metrics = {k: v["value"] for k, v in read_json(self.dir / "metrics.json").items()}
        self.case_dir = root.case_dir(self.info["case_hash"])
        self.design = self.info["design"]

    def value(self, path: str):
        return self.design["values"].get(path)

    def probe_aliases(self) -> dict[str, str]:
        """alias -> probe definition hash, as recorded in the case's measurements."""
        out = {}
        with h5py.File(self.case_dir / "measurements.h5", "r") as f:
            for h in f:
                out.setdefault(f[h].attrs.get("alias", h), h)
        return out

    def probe(self, alias_or_hash: str) -> ProbeData:
        aliases = self.probe_aliases()
        h = aliases.get(alias_or_hash, alias_or_hash)
        weights = basis_weights(_WeightDesign(self.design, self.info.get("normalized")), self.info["bases"])
        with h5py.File(self.case_dir / "measurements.h5", "r") as f:
            if h not in f:
                raise KeyError(f"run {self.id[:12]} has no probe {alias_or_hash!r} (has: {', '.join(aliases)})")
            parts = [(weights[b], ProbeData.from_h5(f[h][b])) for b in f[h]]
        return ProbeData.combine(parts)


class Results:
    def __init__(self, data_root: str | Path, units=None):
        self.root = DataRoot(data_root)
        self.db = DB(self.root.db_path)
        self.units = units

    def study_id(self, name: str) -> str:
        rows = self.db.query("SELECT study_id FROM studies WHERE study_id LIKE ? ORDER BY created DESC",
                             [f"%{name}%"])
        if not rows:
            raise KeyError(f"no study matching {name!r}")
        return rows[0]["study_id"]

    def study_table(self, name: str) -> pd.DataFrame:
        return study_table(self.db, self.study_id(name))

    def query(self, where=None, metrics=None, study=None, pareto=None) -> pd.DataFrame:
        return query(self.db, self.units, where=where, metrics=metrics, study=study, pareto=pareto)

    def run(self, run_id: str) -> RunView:
        return RunView(self.root, run_id)
