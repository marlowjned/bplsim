from bplsim.geom import cad, rz
from bplsim.parts import Param, Slot

from het.part_types._winding import Winding


class Solenoid(Winding):
    version = "1.0.0"
    doc = "A layered coil wound directly on a core, on the thruster axis."
    frame = "front end at z = 0, coil toward -z"

    class Params(Winding.Params):
        on: Slot = Param(type="het:part_types/core")

    def core_radius(self, p):
        return p.on.radius

    def profile_rz(self, p):
        w = self.winding(p)
        r0 = p.on.radius
        return rz.Region(rz.rect(r0, r0 + w["build"], -w["length"], 0), material=p.wire,
                         surfaces={"back_face": [0], "outer_face": [1], "front_face": [2], "inner_face": [3]},
                         excitation={"circuit": p.circuit, "turns": p.turns, "sign": 1})

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))
