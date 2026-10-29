from math import pi, sqrt

from bplsim.geom import cad, rz
from bplsim.parts import Length, Material, Param, PartType, equivalence, margin
from bplsim.units import mm


class Plate(PartType):
    version = "1.0.0"
    doc = "Flat plate with a centre bore; square or round outline."
    frame = "front face at z = 0, toward -z"

    class Params:
        shape: str = Param("square", choices=["square", "round"])
        side: Length | None = Param(None)            # square
        radius: Length | None = Param(None)          # round
        thickness: Length = Param(min=0.1 * mm)
        bore_radius: Length = Param(0 * mm, min=0 * mm)
        material: Material = Param("het:materials/a36", needs=["mu_r_linear"])

    def axisymmetric(self, p):
        return p.shape == "round"

    def _disc(self, p, r):
        return rz.Region(rz.rect(p.bore_radius, r, -p.thickness, 0), material=p.material,
                         surfaces={"back_face": [0], "outer_face": [1], "front_face": [2], "bore_face": [3]})

    def checks(self, p):
        outer = (p.side or 0) / 2 if p.shape == "square" else (p.radius or 0)
        yield margin("has_outline", outer, min=1 * mm)
        yield margin("bore_inside_outline", outer - p.bore_radius, min=1 * mm)

    def profile_rz(self, p):
        return self._disc(p, p.radius)

    def footprint(self, p):
        if p.shape == "square":
            return [("square", (0.0, 0.0), p.side)]
        return [("circle", (0.0, 0.0), p.radius)]

    def shadow_rz(self, p):
        outer = p.side / sqrt(2) if p.shape == "square" else p.radius
        return rz.Region(rz.rect(p.bore_radius, outer, -p.thickness, 0))

    def solid_3d(self, p):
        if p.shape == "round":
            return cad.revolve(self.profile_rz(p))
        return cad.cut(cad.box(p.side, p.side, p.thickness, material=p.material),
                       cad.cylinder(p.bore_radius, p.thickness))

    @equivalence("equal_area_disc", valid_for="any")
    def equal_area_disc(self, p):
        """Square plate -> disc of the same area (legacy plate_r = side / sqrt(pi))."""
        return self._disc(p, p.side / sqrt(pi))
