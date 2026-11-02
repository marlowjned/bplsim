"""Pre-screen (plan §5 step 4, rule R11): part checks, automatic overlap check, assembly checks.

Overlap and clearance between an axisymmetric part A and any part B are computed exactly in r-z:
a point of B lies in (or near) A iff its (r, z) projection does, so it suffices to compare A's
profile with B's *shadow* (B projected onto the r-z half-plane). Only pairs where both parts are
non-axisymmetric need 3-D geometry; those are reported as not checked (decision K6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.ops import unary_union

from bplsim.core.errors import ResolveError
from bplsim.geom.rz import as_regions

OVERLAP_AREA = 1e-12      # m^2 (1 um x 1 um): below this, shapes only touch


@dataclass
class CheckItem:
    name: str
    ok: bool
    slack: float | None = None       # SI; >= 0 is ok
    detail: str = ""
    checked: bool = True


@dataclass
class Prescreen:
    items: list[CheckItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.ok for i in self.items if i.checked)

    @property
    def failures(self) -> list[CheckItem]:
        return [i for i in self.items if i.checked and not i.ok]

    def summary(self) -> str:
        f = self.failures
        if not f:
            return "ok"
        return "invalid: " + "; ".join(f"{i.name} ({i.detail})" if i.detail else i.name for i in f)

    def canonical(self) -> list[dict]:
        return [{"name": i.name, "ok": i.ok, "slack": i.slack, "detail": i.detail, "checked": i.checked}
                for i in self.items]


def shadow(part) -> Any:
    """The part's r-z shadow as a shapely geometry (None if it cannot be computed)."""
    if part.axisymmetric:
        regs = part.regions_rz()
    else:
        fn = getattr(part._instance, "shadow_rz", None)
        if fn is None:
            return None
        regs = [r.placed(part.at, name=part.slot) for r in as_regions(fn(part.p))]
    return unary_union([r.polygon() for r in regs])


def pair_geometry(design, a: str, b: str):
    """(gap distance in m, overlap area in m^2) or None when the pair needs 3-D."""
    pa, pb = design.part(a), design.part(b)
    if not pa.axisymmetric and not pb.axisymmetric:
        return None
    ga, gb = shadow(pa), shadow(pb)
    if ga is None or gb is None:
        return None
    return ga.distance(gb), ga.intersection(gb).area


def prescreen(design, checks_spec: dict | None = None, units=None) -> Prescreen:
    """Run every design-only check of a resolved design."""
    units = units or design.project.units
    out = Prescreen()
    slots = list(design.slots)
    # part checks
    for s in slots:
        for m in design.part(s).checks():
            out.items.append(CheckItem(f"{s}.{m.name}", m.ok, m.slack,
                                       f"margin {units.show(m.value, _len())}, min {units.show(m.min, _len())}"))
    # automatic overlap check
    unchecked = []
    for i, a in enumerate(slots):
        for b in slots[i + 1:]:
            g = pair_geometry(design, a, b)
            if g is None:
                unchecked.append(f"{a}/{b}")
                continue
            _, area = g
            if area > OVERLAP_AREA:
                out.items.append(CheckItem(f"overlap {a} / {b}", False, None,
                                           f"{area * 1e6:.4g} mm^2 of {a} and {b} overlap in r-z"))
    out.items.append(CheckItem("overlap (all pairs)", True, None,
                               "none" + (f"; not checked (both non-axisymmetric, need 3-D): {', '.join(unchecked)}"
                                         if unchecked else ""), True))
    # assembly checks
    for name, spec in (checks_spec or {}).items():
        from bplsim.measure.engine import call_design_metric
        try:
            res = call_design_metric(design, spec["metric"], spec.get("with") or {}, f"checks.{name}")
        except ResolveError:
            raise
        slack = res.get("margin")
        ok = res.get("ok", slack is None or slack >= -1e-12)
        out.items.append(CheckItem(name, bool(ok), slack, str(res.get("detail", "")),
                                   checked=res.get("checked", True)))
    return out


def _len():
    from bplsim.units import DIMS
    return DIMS["length"]
