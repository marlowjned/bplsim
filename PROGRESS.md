# bplsim build progress

Living log of the overnight build (started 2026-10-29). Spec: `../HET/docs/TRADE_FRAMEWORK_PLAN.md` (v0.2)
and `../HET/docs/TRADE_FRAMEWORK_EXAMPLE.md` (v0.3). If a session ends, resume from "Next steps".

## Environment

- Python 3.12 virtual environment at `.venv` (`uv venv --python 3.12`, then `uv pip install -e ".[dev]"`).
  Run: `.venv/Scripts/python.exe -m pytest -m "not slow"`, `.venv/Scripts/bplsim.exe ...`.
- GetDP 3.5.0 (Windows): `../HET/tools/getdp-3.5.0-Windows64/getdp.exe`, found via site `tools.getdp`,
  `BPLSIM_TOOL_GETDP`, or PATH. gmsh 4.15.2 (pip wheel).
- Commits are local only (not pushed), in both `bplsim` and `HET`.

## Status by phase

| Phase | State | Notes |
|---|---|---|
| 0 Groundwork | done | package, CLI, venv; CI workflow + Dockerfile written (not run: no GitHub push, no Docker here) |
| 1 Config and model | done | loader, units, expressions, materials, part types, assemblies, resolver with origins, checks |
| 2 Measurement and execution core | done | probes, metrics, references, measurement sets, superposition, normalization, hashing, folders, worker, local/inline executors, store, query, samplers, driver |
| 3 GetDP 2-D + HET library + parity | done | `../HET/sim`; Design A and B within the legacy model's mesh noise (`../HET/sim/PARITY.md`) |
| 4 Studies, figures, reports | partly | figures + reports + analysis API done; 4 legacy studies ported and run (gap sweep + report, Design A compass search, permeability, Design B coil layering) |
| 5 Remote execution | done (untested on a real cluster) | Slurm executor, multi-worker run-task, sync (ssh+tar), container; tested with stand-in Slurm commands |
| 6 3-D | done, one open issue | `getdp_3d` (geometry from part recipes, linear and nonlinear iron, Newton); 2-D vs 3-D cross-check agrees; nonlinear convergence on the test design: see open issue O1 |
| 7 WarpX | adapter done, untested with real WarpX | multi-stage pipelines, openPMD exports, `warpx` backend with deck templates; tested with a stand-in WarpX |

Tests: 36 fast tests (`-m "not slow"`), 1 slow subprocess test, 2 HET parity tests (`../HET/sim/tests`, need GetDP).

## Key decisions to discuss (made overnight)

| # | Decision | Why | Alternative |
|---|---|---|---|
| K1 | Develop and run **natively on Windows**; code kept cross-platform. | WSL is not installed (needs admin + reboot); BPL members use Windows. You said WSL can come later. | Move to WSL2/Linux. |
| K2 | `uv` + `.venv` instead of pixi. | pixi not installed; GetDP is a plain binary. | pixi for the container. |
| K3 | Probe data in **h5py** with a small own format (`ProbeData`), no xarray/h5netcdf. | Fewer dependencies; data are arrays; combining is a weighted sum. | xarray. |
| K4 | Unit constants in Python entries are **SI float multipliers** (`17.6 * mm` = 0.0176); dimensions from annotations (`Length`, ...). pint only for YAML strings and expressions. | Fast, simple geometry code. | pint quantities everywhere. |
| K5 | Expressions are evaluated **lazily** (pull-based, memoised, cycle detection). | Makes `a if parts.cap else 0` skip the untaken branch (guards on optional slots). | Static graph first. |
| K6/K9 | Overlap/clearance for (axisymmetric, any) pairs computed **exactly in r-z** against the other part's **shadow** (`shadow_rz`). Only (non-axisym, non-axisym) pairs are "not checked" (would need 3-D OCC distances). | Exact, cheap, no CAD needed for most pairs. | OCC for every pair. |
| K7 | Probes must depend only on geometry and their own parameters. | A case is shared by rows that differ only in non-solver inputs. | Probe-relevant values in the case hash. |
| K8 | The **run hash includes the metric definitions** (and exports). | Adding a metric gives new cheap runs instead of half-complete old ones; cases (expensive) still shared. | Fill missing metrics into old run folders. |
| K10 | Part types may define `footprint(p)` (top view) for containment checks (`std:metrics/within`). | Posts on a square plate need a top view. | 3-D. |
| K11 | Derived values used in expressions need declared dimensions: a `Derived` inner class with annotations. | Otherwise `parts.outer_posts.pitch / 2` has no unit. | Return pint quantities. |
| K12 | Local executor: one subprocess per task (`python -m bplsim run-task`); also an in-process `inline` executor. | Crash/timeout isolation; same entry point as Slurm. | multiprocessing pool. |
| K13 | Locks are also stale when the owning PID on the same host is gone (Windows-safe check). | A crashed worker otherwise blocks retries for 10 minutes. | Heartbeat only. |
| K14 | Optuna 5: constraints via `trial.set_constraint` (`constraints_func` is deprecated in 5.0). | Current API. | none |
| K15 | `getdp_axisym`/`getdp_3d` field access interpolates GetDP's **element-nodal B** (one export per basis) instead of GetDP locating every point. Points on element edges get the mean of the adjacent elements. | 27x faster; identical to GetDP's own OnGrid away from element edges (validated). | GetDP OnGrid (`exact=True` keeps it). |
| K16 | HET parity designs use `legacy_bn`: one iron (mu_r 1500), spec winding windows, 50 C (legacy "hot" resistances). | Parity. New designs should use real materials. | none |
| K17 | Legacy saturation ported as `het:metrics/iron_saturation`; `std:metrics/saturation` stays generic. | Parity; post/core treatment is HET-specific. | none |
| K18 | Sync over **ssh + tar**, not rsync. | rsync is not on Windows; ssh and tar are. | rsync on Linux. |
| K19 | Pipeline **exports are ordinary grid probes** (`std:probes/grid_fieldmap`) stored per basis; each run combines them at its (normalized) currents and writes an **openPMD** file for the next stage. | One mechanism; exports reflect each run's currents. | Backend-specific export calls. |
| K20 | Measurement-set probes/metrics may name a `stage:`; default is the last stage. Normalization runs at the stage of its target metric. | Mag -> PIC studies need shape metrics at the magnetostatic stage and plasma metrics at the PIC stage. | One measurement set per stage. |
| K21 | Nonlinear normalization: the **case job iterates** (secant on the current scale, re-solving on the same mesh); the case is defined by geometry + current ratio + target. | No superposition with nonlinear iron. | Driver-level loop over cases. |
| K22 | 3-D post coils carry current **clockwise seen from +z** (sign -1 about each post's own axis), matching the 2-D winding sheets (inner sheet +theta) so the posts carry the return flux. | Consistent 2-D/3-D fields (cross-check agrees). | none |
| K23 | WarpX decks are **Jinja templates** from the project (`fidelity.deck`), rendered with fidelity, op, params, parts and upstream file paths; the bundled `default_rz.j2` is only a starting point. | WarpX parameter names change between versions; the physics setup belongs to the project. | Generate decks in Python. |

## Open issues

- **O1 Nonlinear 3-D convergence.** On the coarse test design at 2.0 A / 1.6 A, Picard stalled (relative residual
  ~1 at the 50 % ramp step, then diverged). Newton with Akima-interpolated B-H (the legacy fallback) is
  implemented; see the log for its result. The legacy pipeline had the same difficulty (`nl_watchdog.py`).
- **O2** `bplsim schema export` (JSON Schemas for editor autocompletion) is not implemented: validation is
  hand-written rather than pydantic models, so schemas would have to be written separately.
- **O3** CI and the Docker image are written but have never run (no push, no Docker on this machine); the GetDP
  Linux download name in the Dockerfile is unverified.
- **O4** Slurm executor tested only with stand-in `sbatch/squeue/sacct`; WarpX only with a stand-in. Both need
  a real run (Savio / a WarpX install).
- **O5** 3-D geometry checks between two non-axisymmetric parts (posts vs plates vs post coils) are reported
  "not checked" (they touch by design in the HET; a real check needs OCC distances).
- **O6** Legacy studies not yet ported: target_sigma sweeps/search, bn_noshield, peak_forward, permeability,
  stock_design, shieldless, spacer, noshield, a_reopt, final_design (gap sweep and Design A search done).
- **O7** Remeasure / metric recompute are automatic (re-running a study with a changed measurement set fills
  missing probes from retained raw output, or re-solves), so there are no separate commands.

## Log

- Core: units, expr, yamlio, project/library loader, materials, parts, assembly merge, resolver, checks, rz
  geometry, cad facade, analytic backends, measurement engine, pipelines.
- Execution: worker, locks, folders, local/inline executors, SQLite store, collect/rebuild, query, study
  spec/variables, samplers, driver (rounds, resume, retry once), CLI.
- Phase 3: getdp_axisym; HET library in ../HET/sim; parity (Design A: misfit 1.178 vs 1.173 %, currents +0.05 %;
  Design B: misfit 1.944 vs 1.936 %, fixed-turns power +0.15 %). Bug found: `measure.add` shorthand was
  silently ignored; unknown keys are now rejected in measure, measure.add, sampler settings.
- Phase 4/5: figures (library entry kind), reports, analysis API; Slurm executor, sync, container, CI.
- Phase 6: getdp_3d; coarse 3-D (444k tets, ~90 s per basis) vs 2-D on the same design: currents within 1 %,
  sigma 17.3 vs 17.2 mm, exit B_r 88.0 vs 89.7 %; 3-D exit-ring ripple 21 % (coarse mesh).
- Ported studies run on GetDP 2-D (HET/sim/studies, data in scratch/hetdata):
  - design_a_search (compass, 85 solves, 12 rounds): misfit 1.178 -> 0.716 %; it ended on the range limits
    (cap edge 1.0 mm, chamfer 10 mm), so the bounds should be widened before trusting the optimum.
  - design_b_coil_layers (36 rows, 11 rejected by the pre-screen: coils overlapping the BN part): best
    26 inner / 21 outer turns per layer, misfit 1.30 % (as designed 29/21: 1.94 %).
  - design_a_permeability: misfit insensitive to mu_r (1.17-1.31 %); power 1.48 W (mu 5000) to 2.64 W (mu 200).
- O8 (design question): sweeping a material property continuously (e.g. mu_r 200-5000) needs either
  generated material variants or a material-override mechanism; swapping whole materials across all iron
  parts already works via an assembly parameter (`params.iron`, used in HET/sim).
- Phase 7: multi-stage pipelines (exports -> openPMD -> next stage), warpx backend, nonlinear normalization.

## Next steps

1. Finish O1 (nonlinear 3-D convergence) and add a slow 3-D test.
2. Run `../HET/sim/studies/design_a_search.yaml` (compass on the real backend) and port the remaining legacy
   studies (O6).
3. Real-cluster and real-WarpX runs (O4); push and run CI (O3).
