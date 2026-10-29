from bplsim.geom import cad, rz
from bplsim.parts import Length, Material, Param, PartType
from bplsim.units import mm


class Core(PartType):
    version = "1.0.0"
    doc = "Solid cylindrical core on the axis."
    frame = "front face at z = 0, toward -z"

    class Params:
        radius: Length = Param(9.525 * mm, min=0.5 * mm)
        length: Length = Param(min=0.1 * mm)
        material: Material = Param("het:materials/steel_1018", needs=["mu_r_linear"])

    def profile_rz(self, p):
        return rz.Region(rz.rect(0, p.radius, -p.length, 0), material=p.material,
                         surfaces={"back_face": [0], "outer_face": [1], "front_face": [2]})

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))
