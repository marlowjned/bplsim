"""3-D geometry facade over gmsh's OpenCASCADE kernel (plan §6).

Part types build solids only through these helpers, so the kernel can be swapped later. The helpers
return lightweight *descriptions* (Solid objects); a backend realises them inside its own gmsh model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Solid:
    """A recipe for one or more 3-D solids, built later by `realise` inside a gmsh model."""
    op: str
    args: dict
    children: list = field(default_factory=list)
    material: Any = None
    names: str | None = None
    excitation: dict | None = None
    surfaces: dict = field(default_factory=dict)

    def canonical(self) -> dict:
        mat = self.material.canonical() if hasattr(self.material, "canonical") else self.material
        return {"op": self.op, "args": self.args, "children": [c.canonical() for c in self.children],
                "material": mat, "names": self.names, "excitation": self.excitation}


def cylinder(radius: float, length: float, material=None) -> Solid:
    """Cylinder on the z axis, front face at z = 0, extending to -length."""
    return Solid("cylinder", {"radius": radius, "length": length}, material=material)


def box(dx: float, dy: float, dz: float, center=(0.0, 0.0), material=None) -> Solid:
    """Box centred on (x, y), front face at z = 0, extending to -dz."""
    return Solid("box", {"dx": dx, "dy": dy, "dz": dz, "center": list(center)}, material=material)


def revolve(region, material=None) -> Solid:
    """Solid of revolution of an r-z region about the z axis."""
    regions = region if isinstance(region, list) else [region]
    return Solid("revolve", {"points": [list(map(list, r.points)) for r in regions]},
                 material=material if material is not None else regions[0].material,
                 surfaces=dict(regions[0].surfaces), excitation=regions[0].excitation)


def polar_array(solid: Solid, count: int, radius: float, phase: float = 0.0, names: str | None = None) -> Solid:
    """`count` copies of `solid` placed on a circle of `radius`, first copy at angle `phase`."""
    return Solid("polar_array", {"count": int(count), "radius": radius, "phase": phase}, [solid],
                 material=solid.material, names=names, excitation=solid.excitation)


def translate(solid: Solid, dx=0.0, dy=0.0, dz=0.0) -> Solid:
    return Solid("translate", {"d": [dx, dy, dz]}, [solid], material=solid.material,
                 excitation=solid.excitation)


def cut(a: Solid, b: Solid) -> Solid:
    return Solid("cut", {}, [a, b], material=a.material, excitation=a.excitation)


def fuse(a: Solid, b: Solid) -> Solid:
    return Solid("fuse", {}, [a, b], material=a.material, excitation=a.excitation)
