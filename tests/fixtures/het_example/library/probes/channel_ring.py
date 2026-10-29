from bplsim.probes import Length, Slot, probe, ring


@probe(version="1.0.0", kind="ring")
def channel_ring(design, sol, z: Length, channel: Slot = Slot("channel", type="het:part_types/channel_insulator"),
                 n_theta: int = 360):
    """B on a full circle at the channel mid-radius, at axial position z."""
    ch = design.parts[channel]
    return sol.sample(ring(r=(ch.r_in + ch.r_out) / 2, z=z, n=n_theta), ["B"])
