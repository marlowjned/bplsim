from bplsim.probes import Angle, Length, Slot, grid_rtz, probe, radial_mean
from bplsim.units import mm


@probe(version="1.0.0", kind="line")
def channel_profile(design, sol, channel: Slot = Slot("channel", type="magnet:part_types/channel_insulator"),
                    dz: Length = 0.25 * mm, dr: Length = 0.25 * mm, beyond_exit: Length = 15 * mm,
                    azimuth: Angle | str = "average", n_theta: int = 36):
    """B averaged over the channel's radial span (r-weighted) at each axial position, from the anode face
    to beyond_exit downstream. azimuth="average": also averaged over n_theta angles (identical in 2-D)."""
    ch = design.parts[channel]
    g = grid_rtz(r=(ch.r_in, ch.r_out, dr), z=(-ch.depth, beyond_exit, dz), azimuth=azimuth, n_theta=n_theta)
    return radial_mean(sol.sample(g, ["B"]), weight="r")
