# Tests

```
python -m pytest -m "not slow"     # fast: analytic backends only, about 30 s
python -m pytest -m slow           # needs GetDP (export BPLSIM_TOOL_GETDP=...), about 10 min
```

| File | What it tests |
|---|---|
| `conftest.py` | shared fixtures: the `het_example` project, a temporary data root per test, and `run_study()` |
| `test_units_expr.py` | units and the expression language (rule R4): display units for bare numbers, unit mismatches, null guards, the operator whitelist, dimension checks |
| `test_resolve.py` | resolution and the pre-screen: resolved values and their origins, checks, optional slots, overlaps, errors with file:line, cycles, material inheritance and swaps |
| `test_studies.py` | the driver end to end on analytic backends: caching, case sharing, resume after interruption, failures and retry, samplers (grid, product, compass, TPE, constrained, NSGA-II), store, query with units, figures, reports (best values only from feasible rows), CLI, site profiles |
| `test_examples.py` | the hand-out projects in `examples/`: they validate, their studies give the results their READMEs quote, their reports build (the magnet sweep is slow: GetDP) |
| `test_chain.py` | stage chaining: magnetostatics exports an openPMD field map at the run's currents, a (stand-in) WarpX stage consumes it |
| `test_slurm.py` | the Slurm executor end to end with stand-in `sbatch`/`squeue`/`sacct` that run the array locally |
| `test_bh_table.py` | the reluctivity table handed to GetDP keeps H(B) monotone (open issue O1) |
| `test_3d.py` | slow: `getdp_3d` against `getdp_axisym` on the same design (angle-averaged channel profile) |
| `test_3d_nonlinear.py` | slow: nonlinear 3-D Newton solve converges and matches a stored reference (about 8 min) |
| `fake_slurm/` | stand-ins for `sbatch`, `squeue`, `sacct` |
| `fake_warpx.py` | stand-in for the WarpX executable: checks the rendered deck and the field file, writes reduced diagnostics |
| `fixtures/funcs/` | test project: analytic test functions (Branin, Rosenbrock, ZDT1) as pipelines |
| `fixtures/het_example/` | test project: a Hall-thruster magnetic circuit (the `docs/user_guide.md` example), with 2-D, 3-D, nonlinear and magnetostatics-to-PIC pipelines |

The fixture projects are for tests; the hand-out versions are in `examples/` (see `examples/README.md`).
