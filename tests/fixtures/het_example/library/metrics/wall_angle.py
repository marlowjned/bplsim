import numpy as np

from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"surface": "surface[B]"}, outputs={"mean_angle": "rad", "max_angle": "rad"})
def wall_angle(surface):
    """Angle between B and the wall surface (0 = along the wall), area-weighted."""
    bn = surface["B_r"] * surface["n_r"] + surface["B_z"] * surface["n_z"]
    b = surface.magnitude("B")
    ang = np.arcsin(np.clip(np.abs(bn) / np.maximum(b, 1e-30), 0, 1))
    w = surface["weight"]
    return {"mean_angle": float(np.sum(ang * w) / np.sum(w)), "max_angle": float(np.max(ang))}
