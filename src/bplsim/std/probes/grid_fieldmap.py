"""A regular field grid, for hand-off to a later stage (pipeline `exports`) or for maps.

grid: "cylindrical" (r, z; theta = 0) or "cartesian" (x, y, z). Ranges are [low, high] and spacing is
the grid step (bare numbers in the project's length unit). A pipeline export of this probe is written as an openPMD file per run (plan §7.5)."""
import numpy as np

from bplsim.probes import Length, ProbeData, Where, probe


@probe(version="1.0.0", kind="grid")
def grid_fieldmap(design, sol, grid: str = "cylindrical", r: list[Length] | None = None,
                  x: list[Length] | None = None, y: list[Length] | None = None, z: list[Length] | None = None,
                  spacing: Length = 1e-3, fields: list | None = None):
    def axis(rng):
        lo, hi = (float(v) for v in rng)
        return np.arange(lo, hi + spacing * 1e-6, spacing)
    if grid == "cylindrical":
        rs, zs = axis(r or [0, 0.08]), axis(z or [-0.06, 0.06])
        R, Z = np.meshgrid(rs, zs, indexing="ij")
        w = Where(R, np.zeros_like(R), Z, ("r", "z"), {"r": rs, "z": zs})
        d = sol.sample(w, fields or ["B"])
        d.attrs.update(grid="cylindrical")
        return d
    xs, ys, zs = axis(x or [-0.08, 0.08]), axis(y or [-0.08, 0.08]), axis(z or [-0.06, 0.06])
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    R, TH = np.hypot(X, Y), np.arctan2(Y, X)
    d = sol.sample(Where(R, TH, Z, ("x", "y", "z"), {"x": xs, "y": ys, "z": zs}), fields or ["B"])
    c, s = np.cos(TH), np.sin(TH)
    bx = d.fields["B_r"] * c - d.fields["B_theta"] * s
    by = d.fields["B_r"] * s + d.fields["B_theta"] * c
    return ProbeData({"x": X, "y": Y, "z": Z}, {"B_x": bx, "B_y": by, "B_z": d.fields["B_z"]},
                     {"grid": "cartesian"}, ("x", "y", "z"))
