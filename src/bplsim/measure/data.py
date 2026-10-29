"""Probe data: named coordinate and field arrays (decision K3: plain arrays + HDF5, no xarray).

Fields are linear in the excitation (B components, potentials), so data from basis solves combine by
weighted sums. Anything nonlinear (|B|, angles, fits) is computed by metrics after combining.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


@dataclass
class ProbeData:
    coords: dict[str, np.ndarray]
    fields: dict[str, np.ndarray]
    attrs: dict = field(default_factory=dict)
    axes: tuple[str, ...] = ()

    def __getitem__(self, name: str) -> np.ndarray:
        if name in self.fields:
            return self.fields[name]
        if name in self.coords:
            return self.coords[name]
        raise KeyError(f"probe data has no {name!r} (fields: {list(self.fields)}, coords: {list(self.coords)})")

    def __contains__(self, name: str) -> bool:
        return name in self.fields or name in self.coords

    @property
    def shape(self) -> tuple:
        for v in self.fields.values():
            return np.shape(v)
        for v in self.coords.values():
            return np.shape(v)
        return ()

    def magnitude(self, prefix: str = "B") -> np.ndarray:
        comps = [k for k in self.fields if k.startswith(prefix + "_")]
        return np.sqrt(sum(np.asarray(self.fields[c]) ** 2 for c in comps))

    def scaled(self, k: float) -> "ProbeData":
        return ProbeData(dict(self.coords), {n: k * np.asarray(v) for n, v in self.fields.items()},
                         dict(self.attrs), self.axes)

    @staticmethod
    def combine(parts: Iterable[tuple[float, "ProbeData"]]) -> "ProbeData":
        parts = list(parts)
        if not parts:
            raise ValueError("nothing to combine")
        w0, d0 = parts[0]
        out = {n: w0 * np.asarray(v, dtype=float) for n, v in d0.fields.items()}
        for w, d in parts[1:]:
            for n, v in d.fields.items():
                out[n] = out[n] + w * np.asarray(v, dtype=float)
        return ProbeData(dict(d0.coords), out, dict(d0.attrs), d0.axes)

    def select(self, mask) -> "ProbeData":
        return ProbeData({k: np.asarray(v)[mask] for k, v in self.coords.items()},
                         {k: np.asarray(v)[mask] for k, v in self.fields.items()}, dict(self.attrs), ())

    @staticmethod
    def concat(items: list["ProbeData"], label_name: str, labels: list[str]) -> "ProbeData":
        coords: dict[str, list] = {}
        fields: dict[str, list] = {}
        lab = []
        for d, name in zip(items, labels):
            n = int(np.prod(d.shape)) if d.shape else 0
            for k, v in d.coords.items():
                coords.setdefault(k, []).append(np.ravel(v))
            for k, v in d.fields.items():
                fields.setdefault(k, []).append(np.ravel(v))
            lab.extend([name] * n)
        c = {k: np.concatenate(v) for k, v in coords.items()}
        c[label_name] = np.array(lab, dtype=object)
        return ProbeData(c, {k: np.concatenate(v) for k, v in fields.items()},
                         dict(items[0].attrs) if items else {}, ())

    # ---- HDF5 -------------------------------------------------------------------------------------
    def to_h5(self, group) -> None:
        g = group
        for k, v in self.coords.items():
            arr = np.asarray(v)
            if arr.dtype == object:
                g.create_dataset("coords/" + k, data=np.array([str(x) for x in arr.ravel()], dtype="S"))
                g["coords/" + k].attrs["shape"] = arr.shape
            else:
                g.create_dataset("coords/" + k, data=arr)
        for k, v in self.fields.items():
            g.create_dataset("fields/" + k, data=np.asarray(v, dtype=float))
        g.attrs["attrs"] = json.dumps(self.attrs, default=str)
        g.attrs["axes"] = json.dumps(list(self.axes))

    @classmethod
    def from_h5(cls, group) -> "ProbeData":
        coords = {}
        for k, ds in group.get("coords", {}).items():
            arr = ds[()]
            if arr.dtype.kind == "S":
                arr = np.array([x.decode() for x in arr], dtype=object).reshape(tuple(ds.attrs["shape"]))
            coords[k] = arr
        fields = {k: ds[()] for k, ds in group.get("fields", {}).items()}
        return cls(coords, fields, json.loads(group.attrs.get("attrs", "{}")),
                   tuple(json.loads(group.attrs.get("axes", "[]"))))
