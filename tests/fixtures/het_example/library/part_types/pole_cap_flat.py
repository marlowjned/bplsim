from bplsim.geom import cad, rz
from bplsim.parts import Length, Material, Param, PartType, margin
from bplsim.units import mm


class PoleCapFlat(PartType):
    version = "1.1.0"
    doc = "Flat pole cap disc, optional chamfer between edge face and back face."
    frame = "front face at z = 0, body toward -z, axis on z"

    class Params:
        radius: Length = Param(17.6 * mm, min=5 * mm)
        thickness: Length = Param(9.525 * mm, min=0.5 * mm)
        edge_length: Length | None = Param(None)
        chamfer_width: Length = Param(0 * mm, min=0 * mm)
        material: Material = Param("het:materials/steel_1018", needs=["mu_r_linear"])

    def checks(self, p):
        t = p.edge_length or p.thickness
        yield margin("edge_within_thickness", p.thickness - t, min=0 * mm)
        yield margin("chamfer_within_radius", p.radius - p.chamfer_width, min=1 * mm)
        if p.chamfer_width > 0:
            yield margin("chamfer_has_height", p.thickness - t, min=0.1 * mm)

    def profile_rz(self, p):
        t = p.edge_length or p.thickness
        if p.chamfer_width == 0:
            pts = [(0, 0), (p.radius, 0), (p.radius, -p.thickness), (0, -p.thickness)]
            surfaces = {"front_face": [0], "edge_face": [1], "back_face": [2]}
        else:
            pts = [(0, 0), (p.radius, 0), (p.radius, -t), (p.radius - p.chamfer_width, -p.thickness),
                   (0, -p.thickness)]
            surfaces = {"front_face": [0], "edge_face": [1], "chamfer": [2], "back_face": [3]}
        return rz.Region(pts, material=p.material, surfaces=surfaces)

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))
