"""Scalar outputs a backend reports (energy, iterations, test-function values, ...)."""
from bplsim.probes import probe


@probe(version="1.0.0", kind="scalars")
def scalars(design, sol, names: list | None = None):
    return sol.scalars(names)
