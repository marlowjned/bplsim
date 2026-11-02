# geom: geometry for part types

Part types describe their shape with these; backends and checks consume it.

| File | Role |
|---|---|
| `rz.py` | r-z (axisymmetric) geometry: regions are polygons in a part's local frame, with named edges (example §5, plan §6). (Non-axisymmetric parts give their r-z shadow with `shadow_rz`, used by `model/checks.py`, K6.) |
| `cad.py` | 3-D geometry facade over gmsh's OpenCASCADE kernel (plan §6): the recipes part types use for `getdp_3d` |
