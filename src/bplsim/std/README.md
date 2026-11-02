# std: the built-in library

Device-agnostic entries every project can use as `std:<folder>/<name>`. It is an ordinary library folder, read by
the same loader as project libraries, so it doubles as a reference for writing entries.

| Entry | Role |
|---|---|
| `probes/scalars.py` | scalar outputs a backend reports (energy, iterations, test-function values, ...) |
| `probes/part_fields.py` | field values over the volume of selected parts (element centroids with volume weights) |
| `probes/grid_fieldmap.py` | a regular field grid, for hand-off to a later stage (pipeline `exports`) or for maps |
| `metrics/scalar.py` | pass backend scalar outputs through as metric outputs |
| `metrics/profile_misfit.py` | misfit of a line profile against a reference, as % of the profile's peak |
| `metrics/saturation.py` | iron saturation from region data, against each part material's `saturation_knee` |
| `metrics/ring_ripple.py` | azimuthal ripple of B_r around a ring (0 for axisymmetric data) |
| `metrics/clearance.py` | design check: minimum gap between listed pairs of parts (r-z exact) |
| `metrics/within.py` | design check: the top-view footprint of one part lies inside another's, with an edge margin |
| `figures/scatter.py` | scatter (or line) of one study column against another, optionally coloured by a third |
| `figures/pareto.py` | two-objective scatter with the Pareto front highlighted |
| `figures/line_probe.py` | overlay one line probe (e.g. a profile) from several runs of a study |
