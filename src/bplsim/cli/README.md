# cli: the `bplsim` command

| File | Role |
|---|---|
| `__init__.py` | the command line (plan §13), built with typer: `study plan/run/status`, `show`, `query`, `plot`, `report build`, `collect`, `sync`, `gc`, `pin`, `run-task`, ...; `bplsim --help` lists them |
| `check.py` | `bplsim check` (validate every entry and assembly, all errors at once with file:line), `bplsim init` (new project skeleton) and `bplsim lib fork` |
