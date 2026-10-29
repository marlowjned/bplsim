from bplsim.probes import Slot, probe


@probe(version="1.0.0", kind="surface")
def channel_wall(design, sol, wall: str = "inner_wall",
                 channel: Slot = Slot("channel", type="het:part_types/channel_insulator")):
    """B on a named surface of the channel part (surface names come from the part type)."""
    return sol.boundary(f"{channel}.{wall}", ["B"])
