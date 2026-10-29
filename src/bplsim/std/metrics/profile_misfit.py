"""Misfit of a line profile against a reference, as % of the profile's peak."""
import numpy as np

from bplsim.measure import Reference
from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"profile": "line[B]"}, outputs={"rms_pct": "%", "max_pct": "%"})
def profile_misfit(profile, reference: Reference, component: str = "B_r", shape_only: bool = True):
    """Compared wherever the reference is defined. shape_only: compare profile/peak against
    reference/reference-peak (the legacy definition); otherwise absolute, in % of the reference peak."""
    z = np.ravel(profile["z"])
    b = np.ravel(profile[component])
    ref = reference(z)[component]
    mask = np.array([v is not None and np.isfinite(v) for v in ref])
    if not np.any(mask):
        raise ValueError("the reference is not defined anywhere on this profile")
    rv = np.array([float(v) for v in np.asarray(ref, dtype=object)[mask]])
    bv = b[mask]
    if shape_only:
        err = bv / np.max(bv) - rv / np.max(rv)
    else:
        err = (bv - rv) / np.max(np.abs(rv))
    return {"rms_pct": float(np.sqrt(np.mean(err ** 2)) * 100), "max_pct": float(np.max(np.abs(err)) * 100)}
