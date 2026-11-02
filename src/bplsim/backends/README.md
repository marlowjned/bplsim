# backends: simulation tools behind one interface

A pipeline stage names a backend and a version range (`backend: getdp_axisym ^1.0`). Each backend turns a resolved
design into one or more solved bases (one per independent current, so linear results superpose), and gives the
probes field access.

| File | Role |
|---|---|
| `__init__.py` | the registry: backend name -> class, imported lazily so a missing tool only matters when used |
| `base.py` | the interface (plan §7.1): `Backend` (`check`, `bases`, `prepare`, `execute`, `field_access`), `Basis`, `Capabilities`, `ExecResult`, `FieldAccess`, `StageConfig` |
| `analytic.py` | built-in backends needing no external tool (plan §7.5): `analytic_functions` (Branin, Rosenbrock, ZDT1 test functions), `analytic_loops` (closed-form field of air-core current loops on the same geometry), `analytic_flaky` (fails on purpose, for tests) |
| `getdp_axisym/__init__.py` | `getdp_axisym`: 2-D axisymmetric linear magnetostatics, gmsh mesh + GetDP solve (plan §7.3); field access interpolates element-nodal B (K15) |
| `getdp_axisym/axi.pro` | the GetDP formulation for it |
| `getdp_3d/__init__.py` | `getdp_3d`: 3-D magnetostatics (plan §7.4): geometry from part recipes in gmsh OpenCASCADE, edge elements, linear or nonlinear iron (Newton, monotone B-H table, K24) |
| `getdp_3d/mag3d.pro` | the GetDP formulation for it |
| `warpx/__init__.py` | `warpx`: particle-in-cell stage (plan §7.6) fed a field map from an upstream stage; renders a Jinja deck, reads WarpX's reduced diagnostics and field output. Tested only with a stand-in (open issue O4) |
| `warpx/default_rz.j2` | a starting-point WarpX deck (RZ, electrostatic); real projects supply their own (K23) |

GetDP is found through the site profile (`tools: {getdp: ...}`), `BPLSIM_TOOL_GETDP`, or `PATH`; WarpX likewise.
