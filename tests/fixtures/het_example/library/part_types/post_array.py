from math import cos, pi, sin

from bplsim.geom import cad, rz
from bplsim.parts import Angle, Length, Material, Param, PartType, equivalence, margin
from bplsim.units import deg, mm


class PostArray(PartType):
    version = "1.0.0"
    doc = "N cylindrical posts on a circle."
    frame = "front ends at z = 0, posts toward -z, post #1 at theta = phase"

    class Params:
        count: int = Param(4, min=2, max=16)
        ring_radius: Length = Param(63.5 * mm)
        post_radius: Length = Param(9.525 * mm, min=1 * mm)
        length: Length = Param(41.275 * mm, min=1 * mm)
        phase: Angle = Param(0 * deg)
        material: Material = Param("het:materials/a36", needs=["mu_r_linear"])

    class Derived:
        pitch: Angle

    def derived(self, p):
        return {"pitch": 2 * pi / p.count}

    def checks(self, p):
        chord = 2 * p.ring_radius * sin(pi / p.count)
        yield margin("posts_do_not_touch", chord - 2 * p.post_radius, min=0 * mm)

    def footprint(self, p):
        """Top view (x, y): one circle per post."""
        return [("circle", (p.ring_radius * cos(p.phase + i * p.pitch), p.ring_radius * sin(p.phase + i * p.pitch)),
                 p.post_radius) for i in range(p.count)]

    def shadow_rz(self, p):
        """Projection onto the r-z half-plane (exact for clearance checks against axisymmetric parts)."""
        return rz.Region(rz.rect(p.ring_radius - p.post_radius, p.ring_radius + p.post_radius, -p.length, 0))

    def solid_3d(self, p):
        post = cad.cylinder(p.post_radius, p.length, material=p.material)
        return cad.polar_array(post, p.count, p.ring_radius, p.phase, names="post_{i}")

    @equivalence("smeared_ring", valid_for="linear", default=True)
    def smeared_ring(self, p):
        """Legacy ring_geometry(): a ring of width 2 r_post with mu_r scaled by the iron fraction."""
        fill = p.count * pi * p.post_radius ** 2 / (2 * pi * p.ring_radius * 2 * p.post_radius)
        ring = rz.rect(p.ring_radius - p.post_radius, p.ring_radius + p.post_radius, -p.length, 0)
        return rz.Region(ring, material=p.material.with_mu_r(1 + fill * (p.material.mu_r_linear - 1)))
