"""Public API for metric authors: the @metric decorator (example §9).

A metric declares the *kind* of each input (``line[B]``, ``ring[B]``, ``regions[B]``, ``surface[B]``,
``points[B]``, ``scalars``), its outputs with units, and receives inputs and parameters by name,
plus ``design`` and ``op`` if its signature asks for them. Outputs: SI floats, or strings for "text".
"""
from __future__ import annotations

from .measure.data import ProbeData  # noqa: F401
from .parts import Slot  # noqa: F401
from .units import Angle, Length  # noqa: F401


def metric(version: str, inputs: dict[str, str] | None = None, outputs: dict[str, str] | str | None = None):
    def deco(fn):
        fn._bplsim = {"kind": "metric", "version": str(version), "inputs": dict(inputs or {}),
                      "outputs": outputs if outputs is not None else {}}
        return fn
    return deco


__all__ = ["metric", "ProbeData", "Slot", "Length", "Angle"]
