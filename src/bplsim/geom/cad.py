"""3-D geometry facade over gmsh's OpenCASCADE kernel (plan §6).

Part types build solids only through these helpers, which return lightweight *recipes* (Solid). A backend
realises them inside its own gmsh model with `realise()`, so the kernel can be swapped without touching
part types. Frame: global z is the thruster axis (+z downstream); part solids are built in the part's
local frame and placed by translating along z.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Solid:
    """A recipe for one or more 3-D solids."""
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
    return Solid("revolve", {"points": [[list(p) for p in r.points] for r in regions]},
                 material=material if material is not None else regions[0].material,
                 surfaces=dict(regions[0].surfaces), excitation=regions[0].excitation)


def polar_array(solid: Solid, count: int, radius: float, phase: float = 0.0, names: str | None = None) -> Solid:
    """`count` copies of `solid` (built on the z axis) on a circle of `radius`, first copy at `phase`."""
    return Solid("polar_array", {"count": int(count), "radius": radius, "phase": phase}, [solid],
                 material=solid.material, names=names, excitation=solid.excitation)


def translate(solid: Solid, dx=0.0, dy=0.0, dz=0.0) -> Solid:
    return Solid("translate", {"d": [dx, dy, dz]}, [solid], material=solid.material, excitation=solid.excitation)


def cut(a: Solid, b: Solid) -> Solid:
    return Solid("cut", {}, [a, b], material=a.material, excitation=a.excitation)


def fuse(a: Solid, b: Solid) -> Solid:
    return Solid("fuse", {}, [a, b], material=a.material, excitation=a.excitation)


# ---- realisation in gmsh ---------------------------------------------------------------------------
@dataclass
class Body:
    """One realised solid: its gmsh volume tags, material, and (for windings) excitation with the coil
    axis position and the winding cross-section area (for the current density)."""
    tags: list[int]
    material: Any
    excitation: dict | None = None
    axis_xy: tuple[float, float] = (0.0, 0.0)
    section_area: float = 0.0
    name: str = ""


def _section_area(s: Solid) -> float:
    """Area of the winding cross-section in a plane containing the coil axis."""
    if s.op == "revolve":
        from shapely.geometry import Polygon
        return sum(Polygon(p).area for p in s.args["points"])
    if s.op == "cut" and all(c.op == "cylinder" for c in s.children):
        a, b = s.children
        return (a.args["radius"] - b.args["radius"]) * a.args["length"]
    if s.op == "translate":
        return _section_area(s.children[0])
    return 0.0


def realise(occ, s: Solid, dz: float = 0.0, name: str = "") -> list[Body]:
    """Build a Solid recipe in the gmsh OCC model; returns one Body per separate copy."""
    def build(node: Solid) -> list[tuple[int, int]]:
        a = node.args
        if node.op == "cylinder":
            return [(3, occ.addCylinder(0, 0, 0, 0, 0, -a["length"], a["radius"]))]
        if node.op == "box":
            cx, cy = a["center"]
            return [(3, occ.addBox(cx - a["dx"] / 2, cy - a["dy"] / 2, -a["dz"], a["dx"], a["dy"], a["dz"]))]
        if node.op == "revolve":
            out = []
            for pts in a["points"]:
                pp = [occ.addPoint(r, 0, z) for r, z in pts]
                ll = [occ.addLine(pp[i], pp[(i + 1) % len(pp)]) for i in range(len(pp))]
                surf = occ.addPlaneSurface([occ.addCurveLoop(ll)])
                rev = occ.revolve([(2, surf)], 0, 0, 0, 0, 0, 1, 2 * math.pi)
                out += [dt for dt in rev if dt[0] == 3]
            return out
        if node.op == "translate":
            dts = build(node.children[0])
            occ.translate(dts, *a["d"])
            return dts
        if node.op == "cut":
            o, _ = occ.cut(build(node.children[0]), build(node.children[1]))
            return o
        if node.op == "fuse":
            o, _ = occ.fuse(build(node.children[0]), build(node.children[1]))
            return o
        raise ValueError(f"cannot realise {node.op} here")

    if s.op == "polar_array":
        child = s.children[0]
        bodies = []
        for i in range(s.args["count"]):
            ang = s.args["phase"] + i * 2 * math.pi / s.args["count"]
            x, y = s.args["radius"] * math.cos(ang), s.args["radius"] * math.sin(ang)
            dts = build(child)
            occ.translate(dts, x, y, dz)
            nm = (s.names or "copy_{i}").format(i=i)
            bodies.append(Body([t for d, t in dts if d == 3], child.material or s.material, child.excitation,
                               (x, y), _section_area(child), f"{name}.{nm}" if name else nm))
        return bodies
    dts = build(s)
    if dz:
        occ.translate(dts, 0, 0, dz)
    return [Body([t for d, t in dts if d == 3], s.material, s.excitation, (0.0, 0.0), _section_area(s), name)]
