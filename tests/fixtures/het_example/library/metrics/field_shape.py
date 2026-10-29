import numpy as np

from bplsim.metrics import Slot, metric
from bplsim.units import mm


@metric(version="2.0.0", inputs={"profile": "line[B]"},
        outputs={"peak_Br": "T", "peak_z": "m", "exit_Br_pct": "%", "anode_Br_pct": "%", "anode_B_pct": "%",
                 "half_depth": "m", "sigma": "m"})
def field_shape(profile, design, channel: Slot = Slot("channel", type="het:part_types/channel_insulator")):
    """The legacy shape metrics (metrics.shape_metrics): peak of B_r searched from 15 mm beyond the exit to
    the anode, exit and anode values as % of peak, half depth, pinned-amplitude half-Gaussian sigma."""
    depth = design.parts[channel].depth
    z = np.ravel(profile["z"])
    br = np.ravel(profile["B_r"])
    bz = np.ravel(profile["B_z"])
    i_exit = int(np.argmin(np.abs(z)))
    sgn = np.sign(br[i_exit]) or 1.0
    br, bz = sgn * br, sgn * bz
    win = (z <= 15 * mm + 1e-12) & (z >= -depth - 1e-12)
    i_pk = np.flatnonzero(win)[np.argmax(br[win])]
    pk = br[i_pk]

    def at(zz, v):
        order = np.argsort(z)
        return float(np.interp(zz, z[order], v[order]))

    b_exit = at(0.0, br)
    inside = (z <= 1e-12) & (z >= -depth - 1e-12)
    d = -z[inside]
    bi = br[inside]
    order = np.argsort(d)
    d, bi = d[order], bi[order]
    below = np.flatnonzero(bi <= 0.5 * b_exit)
    half = float(d[below[0]]) if len(below) else float("nan")
    sig_grid = np.linspace(2, 80, 781) * mm
    errs = [np.sqrt(np.mean((bi - b_exit * np.exp(-d ** 2 / (2 * s ** 2))) ** 2)) for s in sig_grid]
    j = int(np.argmin(errs))
    return {"peak_Br": float(sgn * pk), "peak_z": float(z[i_pk]), "exit_Br_pct": b_exit / pk * 100,
            "anode_Br_pct": at(-depth, br) / pk * 100,
            "anode_B_pct": float(np.hypot(at(-depth, br), at(-depth, bz)) / pk * 100),
            "half_depth": half, "sigma": float(sig_grid[j])}
