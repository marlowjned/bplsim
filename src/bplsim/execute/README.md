# execute: where and how jobs run

Expensive solver work happens in *case* folders (geometry + solver inputs); cheap measurement happens in *run*
folders (case + currents + metrics). Both live under the site's data root and are found again by hash.

| File | Role |
|---|---|
| `folders.py` | data-root layout (plan §2.3): `cases/<hh>/<hash>/`, `runs/<hh>/<hash>/`, `studies/`, status files and DONE markers |
| `local.py` | executors and packing (plan §11.3): `local` (one subprocess per task, crash and timeout isolation, K12) and `inline` (in-process, for tests); packs jobs into tasks |
| `runtask.py` | the worker entry point, `bplsim run-task <task.json>` (plan §11.2): runs the jobs of a task file, same entry point for every executor |
| `locks.py` | folder locks: lock files with a heartbeat; stale when the heartbeat is old or the owning process on the same host is gone (K13) |
| `slurm.py` | Slurm executor (plan §11.3): one job array per round, each array task runs one task file on one node; tested with stand-in commands only (O4) |
| `sites.py` | site profiles (example §14): `~/.config/bplsim/sites/<name>.yaml` (data root, executor, Slurm settings, container, tool paths); `local` is the default |
| `sync.py` | move case and run folders between sites with ssh + tar (plan §11.4, K18) |
