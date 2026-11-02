# The bplsim package

How a study row becomes a stored result, and where each step lives:

```
project + library entries          model/project.py      load and validate libraries (ids from paths)
      │                             model/assembly.py     assemblies, `extends` merging with value origins
study YAML ── sampler asks rows     study/spec.py, study/samplers.py
      │
resolve one row                     model/resolve.py      assembly + row -> one ResolvedDesign (expressions, units)
pre-screen                          model/checks.py       part checks, overlaps, clearances (no solver)
hash case and run                   core/hashing.py       identical inputs are never solved twice
      │
jobs -> executor -> worker          execute/              local, inline or Slurm; run-task is the worker
backend solves the case             backends/             GetDP 2-D/3-D, analytic, WarpX
measure                             measure/              probes, metrics, references, combine, normalization
      │
folders on disk -> SQLite index     store/                collect, query (units in filters), Pareto, retention
read back, plot, report             results/, figures.py  analysis API, figures, reports from the database
```

`study/driver.py` runs the loop: ask -> resolve -> pre-screen -> hash -> jobs -> execute -> collect -> tell, round
after round, resumable. `cli/` is the `bplsim` command.

## Layout

| Path | Role |
|---|---|
| `__init__.py` | version |
| `__main__.py` | `python -m bplsim` (the CLI; worker processes use `python -m bplsim run-task`) |
| **Public API** (imported by project libraries; do not move) | |
| `units.py` | unit constants as SI multipliers (`mm`, `G`, `deg`, ...), dimension annotations (`Length`, `FluxDensity`), the pint registry for YAML strings |
| `parts.py` | part-type authoring: `PartType`, `Param`, `Slot`, `Material`, `margin`, `equivalence` |
| `probes.py` | probe authoring: the `@probe` decorator, `Slot`, sampling helpers (`ring`, `grid_rtz`, `radial_mean`) |
| `metrics.py` | metric authoring: the `@metric` decorator |
| `figures.py` | the `@figure` decorator and figure rendering from stored results |
| `geom/` | geometry for part types: r-z regions (`rz`) and the 3-D CAD facade (`cad`) |
| `measure/` | `Slot`, `reference`, probe data; also the measurement engine |
| **Internals** | |
| [`core/`](core/README.md) | errors, expression language, YAML with line numbers, hashing |
| [`model/`](model/README.md) | projects and libraries, materials, assemblies, resolution, checks, pipelines |
| [`study/`](study/README.md) | study specs, samplers, the driver |
| [`backends/`](backends/README.md) | simulation tools behind one interface |
| [`measure/`](measure/README.md) | probe data, measurement sets, combine, normalization, openPMD |
| [`execute/`](execute/README.md) | data-root layout, executors, worker, locks, sites, sync |
| [`store/`](store/README.md) | the SQLite trade database |
| [`results/`](results/README.md) | analysis API and reports |
| [`cli/`](cli/README.md) | the command line |
| [`geom/`](geom/README.md) | r-z geometry and the gmsh OpenCASCADE facade |
| [`std/`](std/README.md) | the built-in `std` library (probes, metrics, figures), in the same format as a project library |

Docstrings cite the design documents as "plan §n" (`docs/design.md`) and "example §n" / rules "R1-R11"
(`docs/user_guide.md`).
