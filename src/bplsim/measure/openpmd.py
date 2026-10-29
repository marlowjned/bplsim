"""Minimal openPMD 1.1 (HDF5) field files, written with h5py: the format WarpX reads for external fields
(`warpx.B_ext_grid_init_style = read_from_file`) and writes for its own field diagnostics.

Cartesian 3-D: axes x, y, z. Axisymmetric: geometry thetaMode with mode 0 only, axes r, z.
"""
from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

# unitDimension: powers of (L, M, T, I, theta, N, J)
UNIT_DIM = {"B": [0, 1, -2, -1, 0, 0, 0], "E": [1, 1, -3, -1, 0, 0, 0], "rho": [-3, 0, 1, 1, 0, 0, 0],
            "j": [-2, 0, 0, 1, 0, 0, 0]}


def write_field(path, axes: dict[str, np.ndarray], fields: dict[str, np.ndarray], iteration: int = 0,
                time: float = 0.0) -> Path:
    """axes: {"x": xs, "y": ys, "z": zs} (cartesian) or {"r": rs, "z": zs} (thetaMode m=0).
    fields: name -> array of shape (*grid, ncomp) with components (x, y, z) or (r, t, z)."""
    path = Path(path)
    names = list(axes)
    cyl = names == ["r", "z"]
    with h5py.File(path, "w") as f:
        f.attrs["openPMD"] = np.bytes_("1.1.0")
        f.attrs["openPMDextension"] = np.uint32(0)
        f.attrs["basePath"] = np.bytes_("/data/%T/")
        f.attrs["meshesPath"] = np.bytes_("meshes/")
        f.attrs["iterationEncoding"] = np.bytes_("groupBased")
        f.attrs["iterationFormat"] = np.bytes_("/data/%T/")
        f.attrs["software"] = np.bytes_("bplsim")
        it = f.create_group(f"data/{iteration}")
        it.attrs["time"] = float(time)
        it.attrs["dt"] = 1.0
        it.attrs["timeUnitSI"] = 1.0
        meshes = it.create_group("meshes")
        spacing = [float(axes[a][1] - axes[a][0]) if len(axes[a]) > 1 else 1.0 for a in names]
        offset = [float(axes[a][0]) for a in names]
        for name, arr in fields.items():
            g = meshes.create_group(name)
            g.attrs["geometry"] = np.bytes_("thetaMode" if cyl else "cartesian")
            if cyl:
                g.attrs["geometryParameters"] = np.bytes_("m=0;imag=+")
            g.attrs["dataOrder"] = np.bytes_("C")
            g.attrs["axisLabels"] = np.array([np.bytes_(a) for a in names])
            g.attrs["gridSpacing"] = np.array(spacing)
            g.attrs["gridGlobalOffset"] = np.array(offset)
            g.attrs["gridUnitSI"] = 1.0
            g.attrs["unitDimension"] = np.array(UNIT_DIM.get(name, [0] * 7), dtype=float)
            g.attrs["timeOffset"] = 0.0
            comps = ["r", "t", "z"] if cyl else ["x", "y", "z"]
            for i, c in enumerate(comps[:arr.shape[-1]]):
                data = arr[..., i]
                if cyl:
                    data = data[None, ...]                     # mode index first (one mode: m = 0)
                ds = g.create_dataset(c, data=np.ascontiguousarray(data, dtype=float))
                ds.attrs["unitSI"] = 1.0
                ds.attrs["position"] = np.zeros(len(names))
    return path


def read_field(path, name: str = "B", iteration: int | None = None) -> tuple[dict, dict]:
    """(axes, components) of one mesh record; components {comp: array} on the grid."""
    with h5py.File(path, "r") as f:
        its = sorted(int(k) for k in f["data"].keys())
        it = its[-1] if iteration is None else iteration
        g = f[f"data/{it}/meshes/{name}"]
        labels = [x.decode() if isinstance(x, bytes) else str(x) for x in g.attrs["axisLabels"]]
        spacing, offset = g.attrs["gridSpacing"], g.attrs["gridGlobalOffset"]
        comps = {k: g[k][()] for k in g.keys()}
        geom = g.attrs["geometry"]
        geom = geom.decode() if isinstance(geom, bytes) else str(geom)
        if geom == "thetaMode":
            comps = {k: v[0] for k, v in comps.items()}
        shape = next(iter(comps.values())).shape
        axes = {lab: offset[i] + spacing[i] * np.arange(shape[i]) for i, lab in enumerate(labels)}
    return axes, comps
