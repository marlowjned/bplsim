"""Iron saturation from region data, against each part material's saturation_knee."""
import numpy as np

from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"parts": "regions[B]"},
        outputs={"max_fraction": "1", "worst_part": "text", "peak_ratio": "1", "peak_part": "text"})
def saturation(parts, design, percentile: float = 99.9):
    """max_fraction: largest volume fraction of any part with |B| above its knee.
    peak_ratio: largest (percentile of |B|) / knee over parts (the legacy 'sat' proxy)."""
    bmag = parts.magnitude("B")
    labels = parts["part"]
    w = parts["weight"]
    best_f, worst, best_r, peak = 0.0, "", 0.0, ""
    for slot in sorted(set(labels.tolist())):
        m = labels == slot
        part = design.part(slot)
        mat = part.material
        if not mat.has("saturation_knee"):
            continue
        knee = float(mat.saturation_knee)
        frac = float(np.sum(w[m] * (bmag[m] > knee)) / np.sum(w[m])) if np.sum(w[m]) > 0 else 0.0
        ratio = float(np.percentile(bmag[m], percentile) / knee) if np.any(m) else 0.0
        if frac >= best_f:
            best_f, worst = frac, slot if frac > 0 else worst
        if ratio >= best_r:
            best_r, peak = ratio, slot
    return {"max_fraction": best_f, "worst_part": worst, "peak_ratio": best_r, "peak_part": peak}
