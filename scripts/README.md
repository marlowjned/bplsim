# Scripts

Developer utilities; not needed to use bplsim.

| File | Role |
|---|---|
| `wsl_setup.sh` | sets up the Linux (WSL2) workspace: uv, the `.venv` with bplsim installed editable, GetDP 3.5.0 in `~/tools/getdp`, and a `local` site profile. Assumes the repository at `~/Projects/bplsim` and the gmsh system libraries installed (`docs/development.md`) |
| `nonlinear_3d_check.py` | the open-issue O1 investigation script: a nonlinear 3-D Newton solve of the test design with a fine current ramp, printing iterations per step (about 8 min, needs GetDP). The regression test is `tests/test_3d_nonlinear.py` |
