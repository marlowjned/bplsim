"""The trade database: a rebuildable SQLite index of case and run folders (plan §12)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS studies(study_id TEXT PRIMARY KEY, spec_path TEXT, spec_hash TEXT, spec_yaml TEXT,
    snapshot_hash TEXT, created REAL, bplsim_version TEXT, project_commit TEXT, production INTEGER);
CREATE TABLE IF NOT EXISTS rows(study_id TEXT, row_id INTEGER, round INTEGER, origin TEXT, status TEXT,
    invalid_reason TEXT, PRIMARY KEY (study_id, row_id));
CREATE TABLE IF NOT EXISTS row_values(study_id TEXT, row_id INTEGER, name TEXT, value_num REAL, value_text TEXT,
    unit TEXT, PRIMARY KEY (study_id, row_id, name));
CREATE TABLE IF NOT EXISTS row_runs(study_id TEXT, row_id INTEGER, stage TEXT, run_id TEXT, case_id TEXT,
    PRIMARY KEY (study_id, row_id, stage));
CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, backend TEXT, backend_version TEXT, status TEXT,
    reason TEXT, path TEXT, wall_s REAL, cpu_s REAL, raw_retained INTEGER, provenance_json TEXT);
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, case_id TEXT, stage TEXT, status TEXT, error TEXT,
    path TEXT, normalized_json TEXT, provenance_json TEXT, finished REAL);
CREATE TABLE IF NOT EXISTS params(run_id TEXT, path TEXT, value_num REAL, value_text TEXT, unit TEXT,
    PRIMARY KEY (run_id, path));
CREATE TABLE IF NOT EXISTS metrics(run_id TEXT, name TEXT, definition_hash TEXT, metric_id TEXT,
    metric_version TEXT, value_num REAL, value_text TEXT, unit TEXT, stale INTEGER DEFAULT 0,
    PRIMARY KEY (run_id, name, definition_hash));
CREATE TABLE IF NOT EXISTS pins(run_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS tags(run_id TEXT, tag TEXT, PRIMARY KEY (run_id, tag));
CREATE INDEX IF NOT EXISTS ix_params_path ON params(path);
CREATE INDEX IF NOT EXISTS ix_metrics_name ON metrics(name);
"""


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.con.commit()
        self.close()

    def execute(self, sql: str, args: Iterable = ()) -> sqlite3.Cursor:
        return self.con.execute(sql, tuple(args))

    def upsert(self, table: str, row: dict[str, Any]):
        cols = list(row)
        self.con.execute(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [_sql(v) for v in row.values()])

    def commit(self):
        self.con.commit()

    def query(self, sql: str, args: Iterable = ()) -> list[sqlite3.Row]:
        self.con.row_factory = sqlite3.Row
        try:
            return list(self.con.execute(sql, tuple(args)))
        finally:
            self.con.row_factory = None


def _sql(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    if isinstance(v, bool):
        return int(v)
    return v


def split_value(v) -> tuple[float | None, str | None]:
    if isinstance(v, bool):
        return float(v), None
    if isinstance(v, (int, float)):
        return float(v), None
    if v is None:
        return None, None
    return None, str(v)
