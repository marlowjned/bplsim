from math import pi, sin

from bplsim.geom import cad, rz
from bplsim.parts import Length, Param, Slot, equivalence, margin
from bplsim.units import mm

from het.part_types._winding import Winding


class PostCoils(Winding):
    version = "1.0.0"
    doc = "One identical coil on each post of a post_array, all on one circuit."
    frame = "front ends at z = 0, coils toward -z"

    class Params(Winding.Params):
        on: Slot = Param(type="het:part_types/post_array")

    class Derived(Winding.Derived):
        outer_radius: Length

    def coil_count(self, p):
        return p.on.count

    def core_radius(self, p):
        return p.on.post_radius

    def derived(self, p):
        d = super().derived(p)
        return {**d, "outer_radius": p.on.post_radius + d["build"]}

    def checks(self, p):
        chord = 2 * p.on.ring_radius * sin(pi / p.on.count)
        build = self.winding(p)["build"]
        yield margin("coils_do_not_touch", chord - 2 * (p.on.post_radius + build), min=0 * mm)

    def shadow_rz(self, p):
        w = self.winding(p)
        big_r, rc, b = p.on.ring_radius, p.on.post_radius, w["build"]
        return rz.Region(rz.rect(big_r - rc - b, big_r + rc + b, -w["length"], 0))

    def solid_3d(self, p):
        w = self.winding(p)
        ring = cad.cut(cad.cylinder(p.on.post_radius + w["build"], w["length"]),
                       cad.cylinder(p.on.post_radius, w["length"]))
        ring.material = p.wire
        # clockwise seen from +z (sign -1 about each post's own axis): the side of each coil nearest the
        # thruster axis then carries +theta current, as the inner winding sheet of the 2-D smear does, so the
        # posts carry the return flux (-z)
        ring.excitation = {"circuit": p.circuit, "turns": p.turns, "sign": -1, "around": "post"}
        return cad.polar_array(ring, p.on.count, p.on.ring_radius, p.on.phase, names="coil_{i}")

    @equivalence("winding_sheets", valid_for="any")
    def winding_sheets(self, p):
        """Legacy smear: two annular current sheets at ring_radius -/+ post_radius, each carrying the
        per-coil ampere-turns with opposite signs (inner sheet in the same sense as the inner coil)."""
        w = self.winding(p)
        big_r, rc, b = p.on.ring_radius, p.on.post_radius, w["build"]
        exc = {"circuit": p.circuit, "turns": p.turns}
        return [rz.Region(rz.rect(big_r - rc - b, big_r - rc, -w["length"], 0), material=p.wire,
                          excitation={**exc, "sign": 1}, name="inner_sheet"),
                rz.Region(rz.rect(big_r + rc, big_r + rc + b, -w["length"], 0), material=p.wire,
                          excitation={**exc, "sign": -1}, name="outer_sheet")]
