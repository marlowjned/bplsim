"""Public API for probe authors: the @probe decorator and sampling-geometry helpers (example §8).

Sampling geometry is described by `Where` objects in the global cylindrical frame (r, theta, z):
+z downstream, z = 0 at the exit plane. A backend's field access evaluates fields at them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .measure.data import ProbeData
from .parts import Slot  # noqa: F401  (re-exported)
from .units import Angle, Area, Current, FluxDensity, Length, Temperature  # noqa: F401

__all__ = ["probe", "Where", "points", "line", "ring", "grid_rtz", "radial_mean", "theta_mean", "Slot",
           "Length", "Angle", "ProbeData"]


def probe(version: str, kind: str = "points"):
    """Register a probe function `fn(design, sol, **params) -> ProbeData`."""
    def deco(fn):
        fn._bplsim = {"kind": "probe", "version": str(version), "probe_kind": kind}
        return fn
    return deco


@dataclass
class Where:
    """Sampling points (arrays of identical shape) plus a description backends may use to evaluate
    them efficiently (e.g. GetDP OnGrid)."""
    r: np.ndarray
    theta: np.ndarray
    z: np.ndarray
    axes: tuple[str, ...] = ()
    grid: dict = field(default_factory=dict)       # {"r": array, "theta": array, "z": array} for grids

    @property
    def shape(self):
        return np.shape(self.r)

    def rz_unique(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Unique (r, z) pairs and the inverse index (axisymmetric evaluation)."""
        rz = np.stack([np.ravel(self.r), np.ravel(self.z)], axis=1)
        uniq, inv = np.unique(np.round(rz, 12), axis=0, return_inverse=True)
        return uniq[:, 0], uniq[:, 1], inv.ravel()


def _theta_values(azimuth, n_theta):
    if isinstance(azimuth, str):
        if azimuth != "average":
            raise ValueError(f"azimuth must be an angle or 'average', got {azimuth!r}")
        return np.arange(n_theta) * 2 * np.pi / n_theta, True
    return np.array([float(azimuth)]), False


def points(r, theta, z) -> Where:
    r, theta, z = np.broadcast_arrays(np.asarray(r, float), np.asarray(theta, float), np.asarray(z, float))
    return Where(r.copy(), theta.copy(), z.copy(), ("i",) if r.ndim == 1 else ())


def line(r, z, n: int, azimuth=0.0, n_theta: int = 36) -> Where:
    """Axial line at radius r from z[0] to z[1] (n points). azimuth="average": n_theta angles."""
    zs = np.linspace(z[0], z[1], int(n))
    th, avg = _theta_values(azimuth, n_theta)
    Z, TH = np.meshgrid(zs, th, indexing="ij")
    R = np.full_like(Z, float(r))
    w = Where(R, TH, Z, ("z", "theta"), {"r": np.array([float(r)]), "theta": th, "z": zs})
    return w


def ring(r: float, z: float, n: int = 360) -> Where:
    th = np.arange(n) * 2 * np.pi / n
    return Where(np.full(n, float(r)), th, np.full(n, float(z)), ("theta",),
                 {"r": np.array([float(r)]), "theta": th, "z": np.array([float(z)])})


def grid_rtz(r: tuple, z: tuple, azimuth="average", n_theta: int = 36) -> Where:
    """Regular grid: r = (r0, r1, dr), z = (z0, z1, dz), both inclusive; theta from azimuth."""
    rs = np.arange(r[0], r[1] + r[2] * 1e-6, r[2])
    zs = np.arange(z[0], z[1] + z[2] * 1e-6, z[2])
    th, _ = _theta_values(azimuth, n_theta)
    R, TH, Z = np.meshgrid(rs, th, zs, indexing="ij")
    return Where(R, TH, Z, ("r", "theta", "z"), {"r": rs, "theta": th, "z": zs})


def theta_mean(d: ProbeData) -> ProbeData:
    if "theta" not in d.axes:
        return d
    ax = d.axes.index("theta")
    coords = {k: np.mean(v, axis=ax) for k, v in d.coords.items() if k != "theta"}
    coords["theta"] = np.zeros_like(next(iter(coords.values())))
    fields = {k: np.mean(v, axis=ax) for k, v in d.fields.items()}
    return ProbeData(coords, fields, dict(d.attrs), tuple(a for a in d.axes if a != "theta"))


def radial_mean(d: ProbeData, weight: str = "r") -> ProbeData:
    """Mean over the r axis (r-weighted: volume mean) and over theta if present -> data along z."""
    d = theta_mean(d)
    if "r" not in d.axes:
        return d
    ax = d.axes.index("r")
    r = d.coords["r"]
    w = r if weight == "r" else np.ones_like(r)
    wsum = np.sum(w, axis=ax)
    fields = {k: np.sum(np.asarray(v) * w, axis=ax) / wsum for k, v in d.fields.items()}
    coords = {k: np.mean(v, axis=ax) for k, v in d.coords.items() if k != "r"}
    coords["r"] = np.sum(r * w, axis=ax) / wsum
    return ProbeData(coords, fields, dict(d.attrs), tuple(a for a in d.axes if a != "r"))
