"""r-z (axisymmetric) geometry: regions are polygons in a part's local frame (example §5, plan §6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from shapely.geometry import Polygon

NM = 1e-9


def rect(r0: float, r1: float, z0: float, z1: float) -> list[tuple[float, float]]:
    r0, r1 = min(r0, r1), max(r0, r1)
    z0, z1 = min(z0, z1), max(z0, z1)
    return [(r0, z0), (r1, z0), (r1, z1), (r0, z1)]


@dataclass
class Region:
    """A polygon in (r, z), with its material, named edges and optional excitation.

    surfaces maps a name to edge indices (edge i joins points[i] and points[i+1]).
    excitation: {"circuit": name, "turns": N, "sign": +1|-1}; current flows in +theta for sign +1."""
    points: list
    material: Any = None
    surfaces: dict = field(default_factory=dict)
    excitation: dict | None = None
    name: str = ""

    def __post_init__(self):
        pts = [(float(r), float(z)) for r, z in self.points]
        dedup = [p for i, p in enumerate(pts) if p != pts[i - 1]] if len(pts) > 1 else pts
        if len(dedup) != len(pts):
            # dropping a repeated vertex would shift edge indices; refuse rather than mislabel
            if self.surfaces:
                raise ValueError("region has repeated consecutive vertices; remove them so edge "
                                 "indices for named surfaces stay meaningful")
            pts = dedup
        self.points = pts
        if len(pts) < 3:
            raise ValueError("a region needs at least 3 distinct points")
        if min(r for r, _ in pts) < -NM:
            raise ValueError("region extends to r < 0")
        poly = Polygon(pts)
        if not poly.is_valid or poly.area <= 0:
            raise ValueError(f"region polygon is not simple or has zero area: {pts}")
        for name, idx in self.surfaces.items():
            for i in idx:
                if not 0 <= i < len(pts):
                    raise ValueError(f"surface {name!r}: edge index {i} out of range")
        if self.excitation is not None:
            exc = dict(self.excitation)
            exc.setdefault("sign", 1)
            if "circuit" not in exc or "turns" not in exc:
                raise ValueError("excitation needs 'circuit' and 'turns'")
            self.excitation = exc

    def placed(self, dz: float = 0.0, name: str | None = None) -> "Region":
        return Region([(r, z + dz) for r, z in self.points], self.material, dict(self.surfaces),
                      dict(self.excitation) if self.excitation else None, name if name is not None else self.name)

    def polygon(self) -> Polygon:
        return Polygon(self.points)

    @property
    def area(self) -> float:
        return self.polygon().area

    def edges(self, surface: str) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        idx = self.surfaces.get(surface)
        if idx is None:
            raise KeyError(surface)
        n = len(self.points)
        return [(self.points[i], self.points[(i + 1) % n]) for i in idx]

    def canonical(self) -> dict:
        q = lambda v: round(v / NM)  # noqa: E731 - quantise to 1 nm
        mat = self.material.canonical() if hasattr(self.material, "canonical") else self.material
        return {"points": [[q(r), q(z)] for r, z in self.points], "material": mat,
                "excitation": self.excitation, "name": self.name}


def as_regions(obj: Any) -> list[Region]:
    if obj is None:
        return []
    if isinstance(obj, Region):
        return [obj]
    if isinstance(obj, Iterable):
        out = []
        for o in obj:
            out.extend(as_regions(o))
        return out
    raise TypeError(f"expected Region(s), got {type(obj).__name__}")
