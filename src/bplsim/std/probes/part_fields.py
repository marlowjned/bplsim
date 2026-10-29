"""Field values over the volume of selected parts (element centroids with volume weights)."""
from bplsim.probes import ProbeData, probe


def _is_magnetic(part) -> bool:
    mat = getattr(part, "material", None)
    if mat is None or not hasattr(mat, "has"):
        return False
    return mat.has("bh_curve") or (mat.has("mu_r_linear") and float(mat.mu_r_linear) > 1.0)


@probe(version="1.0.0", kind="regions")
def part_fields(design, sol, select: str | list = "magnetic"):
    """select: 'magnetic' (parts whose material has mu_r > 1 or a B-H curve), 'all', or a list of slots.
    Returns all elements of the selected parts, with a 'part' label per element."""
    if select == "magnetic":
        slots = [s for s, p in design.parts.items() if "material" in p.specs and _is_magnetic(p)]
    elif select == "all":
        slots = list(design.parts)
    else:
        slots = list(select)
    items = [sol.region(s) for s in slots]
    return ProbeData.concat(items, "part", slots)
