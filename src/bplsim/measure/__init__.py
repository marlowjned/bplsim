"""Measurement: probe data, references, measurement sets, combine and normalization."""
from __future__ import annotations

from ..parts import Slot  # noqa: F401
from .data import ProbeData  # noqa: F401


def reference(version: str, kind: str = "line[B]"):
    """Register a reference function `fn(design, z, **params) -> {field: values}`."""
    def deco(fn):
        fn._bplsim = {"kind": "reference", "version": str(version), "ref_kind": kind}
        return fn
    return deco


class Reference:
    """A reference bound to a design and parameters; call with sample coordinates."""

    def __init__(self, fn, design, params: dict, entry_id: str):
        self.fn, self.design, self.params, self.id = fn, design, params, entry_id

    def __call__(self, z):
        return self.fn(self.design, z, **self.params)

    def canonical(self):
        return {"id": self.id, "params": self.params}


__all__ = ["reference", "Reference", "Slot", "ProbeData"]
