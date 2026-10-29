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

## Status by phase

- [ ] 0 Groundwork
- [ ] 1 Config and model
- [ ] 2 Measurement and execution core (analytic backends)
- [ ] 3 GetDP 2-D + HET library + parity
- [ ] 4 Studies, figures, reports
- [ ] 5 Remote execution (Slurm)
- [ ] 6 3-D
- [ ] 7 WarpX

## Log

- 2026-10-29: environment set up; progress file created.

## Next steps

Phase 0 → 1.
