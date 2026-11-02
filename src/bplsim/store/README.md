# store: the trade database

The folders on disk are the record; the database is a rebuildable index of them (plan §12), so it can be deleted
and recreated with `bplsim collect --rebuild`.

| File | Role |
|---|---|
| `db.py` | the SQLite schema and access (WAL mode): tables `studies`, `rows`, `row_values`, `row_runs` (study side), `cases`, `runs`, `params`, `metrics` (results), `pins`, `tags` |
| `collect.py` | index case and run folders into the database; idempotent; `--rebuild` recreates it |
| `query.py` | queries across studies: wide tables of parameters and metrics, `where` filters with units (`radius <= 17.6 mm`), Pareto fronts |
| `retention.py` | retention (plan §8.6, example §13): pin cases so their raw solver output is kept; garbage-collect raw output of the rest |
