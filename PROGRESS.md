# bplsim build progress



Living log for the overnight build (started 2026-10-29). Spec: `../HET/docs/TRADE_FRAMEWORK_PLAN.md` (v0.2)

and `../HET/docs/TRADE_FRAMEWORK_EXAMPLE.md` (v0.3). If a session ends, resume from "Next steps".



## Environment



- Python 3.12 virtual environment at `.venv` (created with `uv venv --python 3.12`).

  Run things with `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/bplsim.exe ...`.

- GetDP 3.5.0 (Windows build): `../HET/tools/getdp-3.5.0-Windows64/getdp.exe`, found through the site

  profile `tools.getdp` or the `BPLSIM_GETDP` / PATH fallback.

- gmsh 4.15.2 (pip wheel).



## Key decisions to discuss (made overnight, need your review)



| # | Decision | Why | Alternative |

|---|---|---|---|

| K1 | Develop and run **natively on Windows**; code kept cross-platform (Linux via CI/container later). | WSL is not installed on this machine (needs admin + reboot), and BPL members will use Windows anyway. | Install WSL2 and move to Linux as planned. |

| K2 | `uv` + `.venv` instead of pixi. | pixi not installed; uv is. GetDP is a plain binary, so conda isn't needed. | pixi later for the container. |

| K3 | Probe data stored with **h5py** in a small own format (`ProbeData`: coords + fields + attrs) instead of xarray/h5netcdf. | Fewer dependencies; data are simple arrays; combining is a weighted sum. | xarray if analysis needs labelled arrays. |

| K4 | Unit constants in Python entries (`mm`, `deg`, `G`, …) are **SI float multipliers**; dimensions come from annotations (`Length`, `Angle`, …). pint is used only for YAML strings and expressions. | Fast, simple geometry code; matches "units only at the edges". | pint quantities everywhere (slow, awkward in geometry). |

| K5 | Expressions are evaluated **lazily on demand** (pull-based with memo and cycle detection) rather than building a static graph first. | Lets `a if cond else b` skip the untaken branch, which is what makes guards on optional slots work. | Static graph (would need special-casing for conditionals). |

| K6 | Overlap/clearance checks for pairs with a non-axisymmetric part are **reported as "not checked"** until the 3-D facade exists (phase 6). | OCC checks need the cad facade. | Build the facade first. |

| K7 | Probes must depend only on geometry and their own parameters (a case may be shared by rows that differ elsewhere). | Case = solver inputs. | Put probe-relevant design values into the case hash. |

| K8 | The **run hash includes the metric definitions** (not only case + inputs + normalization). | A study that adds a metric then gets new, cheap run folders instead of half-complete old ones; cases (the expensive part) are still shared. | Fill missing metrics into existing run folders. |

| K9 | Overlap/clearance for (axisymmetric, any) pairs are computed **exactly in r-z** against the other part's **shadow** (`shadow_rz`, its projection onto the r-z half-plane). Only (non-axisym, non-axisym) pairs need 3-D. | Exact, cheap, no CAD needed for most pairs. | 3-D OCC for every pair. |

| K10 | Part types may define `footprint(p)` (top view) for containment checks (`std:metrics/within`). | Posts-on-square-plate needs a top view; cheap and exact for circles/squares. | 3-D. |

| K11 | Derived values that expressions use need declared dimensions: a `Derived` inner class with annotations (like `Params`). | Otherwise `parts.outer_posts.pitch / 2` has no unit. | Return pint quantities from derived(). |

| K12 | Local executor: tasks are subprocesses (`python -m bplsim run-task`), one per slot; plus an in-process `inline` executor for tests/debugging. | Crash/timeout isolation on Windows; same entry point as Slurm. | multiprocessing pool. |

| K13 | Locks also count as stale when the owning PID on the same host is gone (Windows-safe check). | A crashed worker otherwise blocks retries for 10 minutes. | Heartbeat timeout only. |

| K15 | getdp_axisym field access interpolates GetDP's element-nodal B (one Depth-1 export per basis) instead of asking GetDP to locate every point. Points on element edges get the mean of the adjacent elements. | 27x faster (1.4 s vs 37 s for the channel profile); identical to GetDP's own OnGrid to machine precision away from element edges (validated). | GetDP OnGrid per probe (still available: `exact=True`). |
| K16 | The HET parity designs use a `legacy_bn` assembly with the legacy model's choices: one iron (mu_r 1500), spec winding windows (explicit build/length), op temperature 50 C (matches the legacy 'hot' resistances). | Parity with the legacy numbers. New designs should use real materials. | — |
| K17 | Legacy saturation ratio ported as `het:metrics/iron_saturation` (p95 / knee; posts by flux / real area; core by max(p95, shaft flux)). `std:metrics/saturation` stays generic. | Parity; the post/core treatment is HET-specific. | — |
| K18 | Sync uses ssh + tar (not rsync). | rsync is not on Windows; ssh and tar are built in to Windows 10+. | rsync on Linux only. |
| K14 | Optuna 5: constraints are attached with `trial.set_constraint` (the `constraints_func` API is deprecated in 5.0). | Current API. | none |



## Status by phase



- [x] 0 Groundwork (venv, package, CLI; CI/container still to do)

- [x] 1 Config and model

- [x] 2 Measurement and execution core (analytic backends): 31 tests pass

- [ ] 3 GetDP 2-D + HET library + parity

- [ ] 4 Studies, figures, reports

- [ ] 5 Remote execution (Slurm)

- [ ] 6 3-D

- [ ] 7 WarpX



## Log



- 2026-10-29: environment set up; progress file created.

- Core modules written: units, expr, yamlio, project/library loader, materials, parts, assembly merge, resolver,

  checks (pre-screen), rz geometry, cad facade (descriptions), backends (analytic loops/functions/flaky),

  measurement engine (probes, metrics, references, sets, combine, normalize), pipelines.

- Execution: worker (`run-task`), locks, folders, local + inline executors, SQLite store, collect/rebuild, query,

  study spec/variables, samplers (grid, list, sobol, lhs, product, compass, optuna_tpe, optuna_nsga2), driver

  (rounds, resume, retry once), CLI (check, show, study plan/run/status, run-task, collect, query, init, lib fork).

- Tests: tests/fixtures/het_example (the example doc's library) and tests/fixtures/funcs (optimizer tests).



- Phase 3: getdp_axisym backend; HET library in ../HET/sim (Design A, Design B, legacy_bn); parity within the
  legacy model's own mesh noise (sim/PARITY.md). Bugs found on the way: measure.add shorthand was silently
  ignored (fixed; unknown keys now rejected in measure, measure.add and sampler settings).
- Phase 4/5: figures, reports, analysis API; Slurm executor, sync, container, CI.

## Next steps



Phase 6: cad facade realisation in gmsh OCC; getdp_3d backend (port of gmsh_getdp/assembly); 3-D probes
(theta sampling); 2-D vs 3-D cross-check on Design A. Then phase 7 (WarpX adapter).
Remaining legacy studies to port as specs (one done): target_sigma sweeps/search, bn_design search,
bn_noshield, peak_forward, permeability, stock_design, shieldless, spacer, noshield, a_reopt, final_design.

