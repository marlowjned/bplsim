from bplsim.geom import cad, rz
from bplsim.parts import Length, Material, Param, PartType, margin
from bplsim.units import mm


class ChannelInsulator(PartType):
    version = "1.0.0"
    doc = "Insulator body containing the annular discharge channel, with a front lip and a centre bore."
    frame = "exit plane at z = 0, body toward -z"

    class Params:
        r_in: Length = Param()
        r_out: Length = Param()
        depth: Length = Param(min=1 * mm)              # exit plane to anode face
        bore_radius: Length = Param(min=0 * mm)
        lip_radius: Length = Param()
        lip_length: Length = Param(min=0 * mm)
        body_radius: Length = Param()
        total_length: Length = Param()
        material: Material = Param("het:materials/bn")

    def checks(self, p):
        yield margin("inner_wall", p.r_in - p.bore_radius, min=0.5 * mm)
        yield margin("outer_wall", p.lip_radius - p.r_out, min=0.5 * mm)
        yield margin("channel_floor", p.total_length - p.depth, min=0.5 * mm)
        yield margin("lip_within_body", p.body_radius - p.lip_radius, min=0 * mm)

    def profile_rz(self, p):
        pts = [(p.bore_radius, 0), (p.r_in, 0), (p.r_in, -p.depth), (p.r_out, -p.depth), (p.r_out, 0),
               (p.lip_radius, 0), (p.lip_radius, -p.lip_length), (p.body_radius, -p.lip_length),
               (p.body_radius, -p.total_length), (p.bore_radius, -p.total_length)]
        return rz.Region(pts, material=p.material,
                         surfaces={"inner_wall": [1], "anode_face": [2], "outer_wall": [3], "back_face": [8],
                                   "bore_face": [9]})

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))
