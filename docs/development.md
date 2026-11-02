# Developing bplsim

For people changing bplsim itself. Using it: [`user_guide.md`](user_guide.md). Internals as designed:
[`design.md`](design.md). This file records the build status, the decisions taken while building (K1-K24,
where the code departs from or fills in the design) and the open issues.

## Set-up

Linux (or WSL2 on Windows) is the main platform; the code also runs natively on Windows and macOS.

```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
source .venv/bin/activate
python -m pytest -m "not slow"          # fast suite, analytic backends only (about 30 s)
python -m pytest -m slow                # GetDP: 2-D vs 3-D, nonlinear 3-D (about 8 min), the magnet example; crash retry
```

- `scripts/wsl_setup.sh` reproduces the Linux workspace (uv, Python 3.12, GetDP 3.5.0 in `~/tools/getdp`, a
  local site profile). System packages for gmsh: `sudo apt install -y build-essential libglu1-mesa libxrender1
  libxcursor1 libxft2 libxinerama1 libgomp1 libxi6 libxrandr2 wget`.
- The slow tests need GetDP: `export BPLSIM_TOOL_GETDP=~/tools/getdp/bin/getdp` (they do not read the site
  profile). gmsh comes as a pip wheel.
- The HET project (`HET/sim`, a separate repository) has parity tests against the legacy 2-D code
  (`HET/sim/tests`, need GetDP). Run them after changing a backend.

## Status by phase

| Phase | State | Notes |
|---|---|---|
| 0 Groundwork | done | package, CLI, venv, CI workflow, Dockerfile (image never built) |
| 1 Config and model | done | loader, units, expressions, materials, part types, assemblies, resolver with origins, checks |
| 2 Measurement and execution core | done | probes, metrics, references, measurement sets, superposition, normalization, hashing, folders, worker, local/inline executors, store, query, samplers, driver |
| 3 GetDP 2-D + HET library + parity | done | `HET/sim`; the two parity designs agree with the legacy model within its mesh noise |
| 4 Studies, figures, reports | done | figures, reports, analysis API; HET legacy studies partly ported (O6) |
| 5 Remote execution | done, untested on a real cluster | Slurm executor, multi-worker run-task, sync (ssh + tar), container; tested with stand-in Slurm commands |
| 6 3-D | done | `getdp_3d` (geometry from part recipes, linear and nonlinear iron, Newton); 2-D vs 3-D cross-check agrees |
| 7 WarpX | adapter done, untested with real WarpX | multi-stage pipelines, openPMD exports, `warpx` backend with deck templates; tested with a stand-in |

Tests: 48 fast, 4 slow (`tests/README.md`).

## Package layout

`src/bplsim/README.md` maps every module. The top level holds only what project libraries import (`units`,
`parts`, `probes`, `metrics`, `figures`, and the `geom` and `measure` packages); keep it that way, since moving
those breaks every project. Everything else is internal and may move.

## Decisions taken while building

| # | Decision | Why | Alternative |
|---|---|---|---|
| K1 | Code kept cross-platform; Linux/WSL2 is the main workspace (Windows first, moved 2026-10-29). | BPL members use Windows; WarpX is Linux-first. | Linux only. |
| K2 | `uv` + `.venv` instead of pixi. | GetDP is a plain binary. | pixi for the container. |
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
| K24 | B-H curves are validated **in the backend**, as the backend will interpolate them (`getdp_3d.check()`, before meshing), not on the material. | What is physical depends on the interpolation: in O1 a valid table became non-monotone only through the nu(B^2) spline. Keeps library entries solver-agnostic. | A material-level check at load time (it can only test the raw table, so it would not have caught O1). |

Also settled (O8, 2026-10-29): materials have fixed properties. Worst/best cases are separate material entries
(e.g. `iron_legacy_mu200`), swapped across parts with an assembly parameter (`params.iron`).

## Open issues

- **O2** `bplsim schema export` (JSON Schemas for editor autocompletion) is not implemented: validation is
  hand-written rather than pydantic models, so schemas would have to be written separately.
- **O3** The Docker image (`containers/Dockerfile`) has never been built.
- **O4** The Slurm executor is tested only with stand-in `sbatch/squeue/sacct`, the WarpX backend only with a
  stand-in. Both need a real run (Savio, a WarpX install).
- **O5** 3-D geometry checks between two non-axisymmetric parts (posts vs plates vs post coils) are reported
  "not checked" (a real check needs OCC distances).
- **O6** HET legacy studies not yet ported: target_sigma sweeps/search, bn_noshield, peak_forward, stock_design,
  shieldless, spacer, noshield, a_reopt, final_design.
- **O7** Remeasure / metric recompute are automatic (re-running a study with a changed measurement set fills
  missing probes from retained raw output, or re-solves), so there are no separate commands.

## Closed: O1, nonlinear 3-D convergence (2026-10-29)

Newton stalled on the coarse test design (61 iterations, not converged, at the 85 % ramp step). The cause was
the reluctivity table, not saturation: nu = H/B set at the B-H points only and interpolated by GetDP against B^2
made H(B) decrease between 0.65 and 0.80 T, an unphysical law with an indefinite Newton tangent. Fix (getdp_3d
1.1.0, `nu_table`): H(B) interpolated with a monotone cubic (PCHIP), resampled at 160 points, and the nu(B^2) list
checked to keep H(B) increasing under GetDP's interpolation. Result: 3-4 Newton iterations per step, 478 s
instead of 3964 s. Tests: `tests/test_bh_table.py`, `tests/test_3d_nonlinear.py`. Check placement: K24.

## History

- 2026-10-29: phases 0-7 built; HET library and parity (`HET/sim`); move to the Linux workspace; O1 fixed.
- 2026-11-02: package organized into subpackages (`core`, `model`, `results`, `cli`); documentation and the
  `examples/` projects added; report "best" values use only feasible rows.
