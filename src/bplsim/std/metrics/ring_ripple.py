"""Azimuthal ripple of B_r around a ring (0 for axisymmetric data)."""
import numpy as np

from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"ring": "ring[B]"}, outputs={"ripple_pct": "%", "mean_Br": "T"})
def ring_ripple(ring, component: str = "B_r"):
    b = np.ravel(ring[component])
    mean = float(np.mean(b))
    ripple = float((np.max(b) - np.min(b)) / abs(mean) * 100) if mean != 0 else float("inf")
    return {"ripple_pct": ripple, "mean_Br": mean}
