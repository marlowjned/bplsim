"""Design check: minimum gap between listed pairs of parts (r-z exact; see bplsim.checks)."""
from bplsim.checks import pair_geometry
from bplsim.metrics import Length, Slot, metric


@metric(version="1.0.0", outputs={"margin": "m", "detail": "text"})
def clearance(design, pairs: list[tuple[Slot, Slot, Length]]):
    """Each pair: [slot_a, slot_b, minimum gap]. Pairs with an empty slot are skipped."""
    worst, details, unchecked = None, [], []
    for a, b, gmin in pairs:
        if a not in design.slots or b not in design.slots:
            continue
        g = pair_geometry(design, a, b)
        if g is None:
            unchecked.append(f"{a}/{b}")
            continue
        gap, area = g
        if area > 1e-12:
            gap = -(area ** 0.5)
        slack = gap - gmin
        details.append(f"{a} - {b} gap {gap * 1e3:.4g} mm (min {gmin * 1e3:.4g})")
        worst = slack if worst is None else min(worst, slack)
    if unchecked:
        details.append("not checked (needs 3-D): " + ", ".join(unchecked))
    return {"margin": worst if worst is not None else 0.0, "detail": "; ".join(details),
            "checked": worst is not None}
