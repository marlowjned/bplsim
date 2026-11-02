# Example: a test function

The Branin test function (known minimum) behind the built-in `analytic_functions` backend: no external tools.
Use it to learn the commands and the study file format.

## Files

| File | Role |
|---|---|
| `project.yaml` | project name and namespace (`funcs`), the libraries it uses (only the built-in `std`) |
| `library/assemblies/xy.yaml` | the "design": parameters `x1`, `x2` with defaults |
| `library/pipelines/branin.yaml` | one stage: backend `analytic_functions`, evaluating Branin |
| `library/measurements/scalars.yaml` | the measurement set: the backend's output as metric `f` (`f.f`) |
| `studies/branin_grid.yaml` | a sweep: `x1` at 4 values times 8 quasi-random points in `x2`, 32 rows |
| `studies/branin_compass.yaml` | an optimizer: compass (pattern) search from (2.5, 7.5) with shrinking steps |
| `reports/summary.md.j2` | a report template: best values and a figure, read from the database |

## Run it

```
cd examples/functions
bplsim check                                  # validate the project (all errors at once, with file:line)
bplsim study plan studies/branin_grid.yaml    # dry run: rows, cached cases, cost
bplsim study run studies/branin_grid.yaml     # 32 rows, about 2 s
bplsim study status studies/branin_grid.yaml  # progress and the result table
bplsim study run studies/branin_compass.yaml  # 72 rows, about 17 s
bplsim report build reports/summary.md.j2     # writes reports/summary.md and reports/summary_figures/
```

Running a study again does nothing new: every row is found in the cache. Interrupt a run and start it again and
it resumes where it stopped.

## What you should get

| Study | Best | Known answer |
|---|---|---|
| `branin_grid` | f = 2.39 at (10.0, 2.33) | 0.397887 at (-pi, 12.275), (pi, 2.275), (9.425, 2.475): the grid is coarse |
| `branin_compass` | f = 0.3982 at (3.150, 2.270) | 0.397887 at (pi, 2.275) |

More samplers (Optuna TPE, NSGA-II, constrained studies) are described in `src/bplsim/study/README.md`; the test
project `tests/fixtures/funcs/` has a study for each.
