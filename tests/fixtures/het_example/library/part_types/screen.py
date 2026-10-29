from bplsim.geom import cad, rz
from bplsim.parts import Length, Material, Param, PartType
from bplsim.units import mm


class Screen(PartType):
    version = "1.0.0"
    doc = "Cylindrical magnetic screen (tube)."
    frame = "tip at z = 0, tube toward -z"

    class Params:
        r_inner: Length = Param(min=0 * mm)
        thickness: Length = Param(min=0.1 * mm)
        length: Length = Param(min=0.1 * mm)
        material: Material = Param("het:materials/a36", needs=["mu_r_linear"])

    def profile_rz(self, p):
        return rz.Region(rz.rect(p.r_inner, p.r_inner + p.thickness, -p.length, 0), material=p.material,
                         surfaces={"root_face": [0], "outer_face": [1], "tip_face": [2], "inner_face": [3]})

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))
