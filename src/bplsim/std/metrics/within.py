"""Design check: the top-view footprint of one part lies inside another's, with an edge margin.

Footprints come from the part types' `footprint(p)`: ("circle", (x, y), r) or ("square", (x, y), side)."""
import math

from bplsim.metrics import Length, Slot, metric


def _edge_distance(inner, outer) -> float:
    kind_i, (xi, yi), ri = inner
    kind_o, (xo, yo), so = outer
    if kind_i != "circle":
        raise ValueError("within: inner footprints must be circles")
    if kind_o == "square":
        h = so / 2
        return min(h - abs(xi - xo), h - abs(yi - yo)) - ri
    if kind_o == "circle":
        return so - (math.hypot(xi - xo, yi - yo) + ri)
    raise ValueError(f"within: unknown footprint {kind_o!r}")


@metric(version="1.0.0", outputs={"margin": "m", "detail": "text"})
def within(design, inner: Slot, outer: Slot, min_edge: Length = 0.0):
    pi_, po = design.part(inner), design.part(outer)
    fi = pi_.footprint()
    (fo,) = po.footprint()
    edge = min(_edge_distance(c, fo) for c in fi)
    return {"margin": edge - min_edge,
            "detail": f"{inner} in {outer}: edge {edge * 1e3:.4g} mm (min {min_edge * 1e3:.4g})"}
