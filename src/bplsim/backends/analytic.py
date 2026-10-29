"""Analytic backends (plan §7.5): exercise the whole framework without external tools.

* analytic_loops: winding regions become coaxial current loops; B in closed form (elliptic
  integrals). Magnetic materials are ignored (air core). Superposable.
* analytic_functions: optimizer test functions of the assembly parameters x1, x2, ...
* analytic_flaky: analytic_loops with injected failures, timeouts and crashes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import numpy as np
from scipy.special import ellipe, ellipk
from shapely.geometry import Point, Polygon

from ..errors import BackendError
from ..hashing import content_hash
from ..parts import Param
from ..units import mm
from .base import Backend, Basis, Capabilities, ExecResult, FieldAccess, StageConfig, regions_inputs

MU0 = 4e-7 * math.pi


# ------------------------------------------------------------------------------------------------
def loop_field(a: float, z0: float, current: float, r: np.ndarray, z: np.ndarray):
    """(B_r, B_z) of a circular loop of radius a at z0 carrying `current` in +theta."""
    r = np.asarray(r, float)
    dz = np.asarray(z, float) - z0
    br = np.zeros(np.broadcast(r, dz).shape)
    bz = np.zeros_like(br)
    on_axis = r < 1e-12
    rr, dd = np.broadcast_arrays(r, dz)
    # on axis
    bz[on_axis] = MU0 * current * a ** 2 / (2 * (a ** 2 + dd[on_axis] ** 2) ** 1.5)
    m = ~on_axis
    if np.any(m):
        rm, dm = rr[m], dd[m]
        denom = (a + rm) ** 2 + dm ** 2
        k2 = np.clip(4 * a * rm / denom, 0, 1 - 1e-15)
        K, E = ellipk(k2), ellipe(k2)
        q = (a - rm) ** 2 + dm ** 2
        q = np.maximum(q, 1e-30)
        c = MU0 * current / (2 * math.pi * np.sqrt(denom))
        bz[m] = c * (K + (a ** 2 - rm ** 2 - dm ** 2) / q * E)
        br[m] = c * dm / rm * (-K + (a ** 2 + rm ** 2 + dm ** 2) / q * E)
    return br, bz


class LoopsField(FieldAccess):
    symmetry = "axisymmetric"

    def __init__(self, inputs: dict, basis: Basis, cell: float, edge_points: int):
        self.inputs, self.basis, self.cell, self.edge_points = inputs, basis, cell, edge_points
        self.loops = []           # (radius, z, current)
        n = int(inputs["filaments"])
        for reg in inputs["regions"]:
            exc = reg.get("excitation")
            if not exc:
                continue
            current = basis.currents.get(exc["circuit"], 0.0) * exc["turns"] * exc.get("sign", 1)
            if current == 0:
                continue
            poly = Polygon(reg["points"])
            r0, z0, r1, z1 = poly.bounds
            pts = [(r0 + (i + 0.5) * (r1 - r0) / n, z0 + (j + 0.5) * (z1 - z0) / n)
                   for i in range(n) for j in range(n)]
            inside = [p for p in pts if poly.contains(Point(p))] or pts
            for (rr, zz) in inside:
                self.loops.append((rr, zz, current / len(inside)))

    def _b(self, r, z):
        br = np.zeros(np.shape(r))
        bz = np.zeros(np.shape(r))
        for a, z0, cur in self.loops:
            dbr, dbz = loop_field(a, z0, cur, r, z)
            br += dbr
            bz += dbz
        return br, bz

    def sample(self, where, fields=("B",)):
        from ..measure.data import ProbeData
        ru, zu, inv = where.rz_unique()
        br, bz = self._b(ru, zu)
        shape = where.shape
        return ProbeData({"r": where.r, "theta": where.theta, "z": where.z},
                         {"B_r": br[inv].reshape(shape), "B_theta": np.zeros(shape), "B_z": bz[inv].reshape(shape)},
                         {"symmetry": "axisymmetric"}, where.axes)

    def _regions_named(self, slot):
        regs = [r for r in self.inputs["regions"] if r["name"] == slot]
        if not regs:
            raise BackendError(f"no region for part {slot!r}")
        return regs

    def region(self, part: str, fields=("B",)):
        from ..measure.data import ProbeData
        rs, zs, ws = [], [], []
        for reg in self._regions_named(part):
            poly = Polygon(reg["points"])
            r0, z0, r1, z1 = poly.bounds
            nr = max(2, int(math.ceil((r1 - r0) / self.cell)))
            nz = max(2, int(math.ceil((z1 - z0) / self.cell)))
            dr, dz = (r1 - r0) / nr, (z1 - z0) / nz
            for i in range(nr):
                for j in range(nz):
                    rc, zc = r0 + (i + 0.5) * dr, z0 + (j + 0.5) * dz
                    if poly.contains(Point(rc, zc)):
                        rs.append(rc)
                        zs.append(zc)
                        ws.append(2 * math.pi * rc * dr * dz)
        r, z = np.array(rs), np.array(zs)
        br, bz = self._b(r, z)
        return ProbeData({"r": r, "theta": np.zeros_like(r), "z": z, "weight": np.array(ws)},
                         {"B_r": br, "B_theta": np.zeros_like(r), "B_z": bz}, {"symmetry": "axisymmetric"})

    def boundary(self, surface: str, fields=("B",)):
        from ..measure.data import ProbeData
        slot, name = surface.split(".", 1)
        rs, zs, nr_, nz_, ls = [], [], [], [], []
        for reg in self._regions_named(slot):
            idx = reg["surfaces"].get(name)
            if idx is None:
                continue
            pts = reg["points"]
            poly = Polygon(pts)
            for i in idx:
                (ra, za), (rb, zb) = pts[i], pts[(i + 1) % len(pts)]
                L = math.hypot(rb - ra, zb - za)
                tr, tz = (rb - ra) / L, (zb - za) / L
                nr, nz = tz, -tr                         # a normal; flip to point out of the part
                mr, mz = (ra + rb) / 2, (za + zb) / 2
                if poly.contains(Point(mr + 1e-7 * nr, mz + 1e-7 * nz)):
                    nr, nz = -nr, -nz
                k = self.edge_points
                for s in range(k):
                    t = (s + 0.5) / k
                    rs.append(ra + t * (rb - ra))
                    zs.append(za + t * (zb - za))
                    nr_.append(nr)
                    nz_.append(nz)
                    ls.append(L / k)
        if not rs:
            raise BackendError(f"no surface {surface!r}")
        r, z = np.array(rs), np.array(zs)
        # evaluate just outside the part (fields are continuous here anyway: no iron)
        br, bz = self._b(r + 1e-7 * np.array(nr_), z + 1e-7 * np.array(nz_))
        return ProbeData({"r": r, "theta": np.zeros_like(r), "z": z, "n_r": np.array(nr_), "n_z": np.array(nz_),
                          "weight": 2 * math.pi * r * np.array(ls)},
                         {"B_r": br, "B_theta": np.zeros_like(r), "B_z": bz}, {"symmetry": "axisymmetric"})

    def export_grid(self, grid, fields=("B",), fmt="npz", path=None):
        r = np.arange(grid["r"][0], grid["r"][1] + 1e-12, grid["spacing"])
        z = np.arange(grid["z"][0], grid["z"][1] + 1e-12, grid["spacing"])
        R, Z = np.meshgrid(r, z, indexing="ij")
        br, bz = self._b(R, Z)
        np.savez(path, r=r, z=z, B_r=br, B_z=bz)
        return path


class AnalyticLoops(Backend):
    measure_needs_raw = False       # fields are recomputed from the inputs
    name = "analytic_loops"
    version = "1.0.0"
    capabilities = Capabilities(dims=2, symmetry="axisymmetric", superposable=True)
    FIDELITY = {"filaments": Param(4, min=1), "cell": Param(0.5 * mm, dim="length"),
                "edge_points": Param(8, min=1), "nonlinear": Param(False)}

    def solve_inputs(self, design, stage: StageConfig) -> dict:
        regions, _, circuits = regions_inputs(design, stage, linear=True)
        return {"regions": [_region_dict(r) for r in regions], "circuits": circuits,
                "filaments": int(stage.fidelity["filaments"]), "cell": float(stage.fidelity["cell"]),
                "edge_points": int(stage.fidelity["edge_points"])}

    def field_access(self, inputs, workdir, basis):
        return LoopsField(inputs, basis, float(inputs["cell"]), int(inputs["edge_points"]))


def _region_dict(r) -> dict:
    mat = r.material
    mat_c = mat.canonical() if hasattr(mat, "canonical") else mat
    return {"name": r.name, "points": [list(p) for p in r.points], "surfaces": r.surfaces,
            "excitation": r.excitation, "material": mat_c}


# ------------------------------------------------------------------------------------------------
def rosenbrock(x):
    return sum(100 * (x[i + 1] - x[i] ** 2) ** 2 + (1 - x[i]) ** 2 for i in range(len(x) - 1))


def branin(x):
    a, b, c, r, s, t = 1, 5.1 / (4 * math.pi ** 2), 5 / math.pi, 6, 10, 1 / (8 * math.pi)
    return a * (x[1] - b * x[0] ** 2 + c * x[0] - r) ** 2 + s * (1 - t) * math.cos(x[0]) + s


def zdt1(x):
    f1 = x[0]
    g = 1 + 9 * sum(x[1:]) / max(1, len(x) - 1)
    return f1, g * (1 - math.sqrt(f1 / g))


class ScalarField(FieldAccess):
    symmetry = "none"

    def __init__(self, values: dict):
        self.values = values

    def scalars(self, names=None):
        from ..measure.data import ProbeData
        names = names or list(self.values)
        return ProbeData({}, {n: np.array(float(self.values[n])) for n in names}, {})


class AnalyticFunctions(Backend):
    measure_needs_raw = False
    name = "analytic_functions"
    version = "1.0.0"
    capabilities = Capabilities(dims=0, symmetry="none", superposable=False)
    FIDELITY = {"function": Param("rosenbrock", choices=["rosenbrock", "branin", "zdt1", "constrained_rosenbrock"]),
                "noise": Param(0.0)}

    def solve_inputs(self, design, stage):
        xs = [(k, float(v)) for k, v in sorted(design.params("params").items()) if k.startswith("x")]
        xs.sort(key=lambda kv: int(kv[0][1:]) if kv[0][1:].isdigit() else kv[0])
        return {"function": stage.fidelity["function"], "x": [v for _, v in xs], "circuits": []}

    def bases(self, design, stage, inputs):
        return [Basis("all", {})]

    def field_access(self, inputs, workdir, basis):
        f = inputs["function"]
        x = inputs["x"]
        if f == "rosenbrock":
            vals = {"f": rosenbrock(x)}
        elif f == "branin":
            vals = {"f": branin(x)}
        elif f == "zdt1":
            f1, f2 = zdt1(x)
            vals = {"f1": f1, "f2": f2}
        else:  # constrained_rosenbrock: minimise rosenbrock subject to x0^2 + x1^2 <= 1.5
            vals = {"f": rosenbrock(x), "g": 1.5 - (x[0] ** 2 + x[1] ** 2)}
        return ScalarField(vals)


# ------------------------------------------------------------------------------------------------
class AnalyticFlaky(AnalyticLoops):
    """Loops with deliberate trouble. fidelity.mode: fail | timeout | crash | none; fidelity.rate: share of
    cases affected (deterministic in the case inputs); fidelity.sleep: seconds per solve."""
    name = "analytic_flaky"
    version = "1.0.0"
    FIDELITY = {**AnalyticLoops.FIDELITY, "mode": Param("none", choices=["none", "fail", "timeout", "crash"]),
                "rate": Param(1.0), "sleep": Param(0.0)}

    def solve_inputs(self, design, stage):
        d = super().solve_inputs(design, stage)
        d.update(mode=stage.fidelity["mode"], rate=float(stage.fidelity["rate"]), sleep=float(stage.fidelity["sleep"]))
        return d

    def execute(self, inputs, workdir, basis, resources):
        h = int(hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:8], 16)
        hit = (h % 1000) / 1000 < inputs["rate"]
        if inputs["sleep"]:
            time.sleep(inputs["sleep"])
        if hit and inputs["mode"] == "fail":
            return ExecResult("failed", "injected failure")
        if hit and inputs["mode"] == "timeout":
            time.sleep(float(resources.get("timeout", 1.0)) + 5)
        if hit and inputs["mode"] == "crash":
            tmpdir = Path(workdir).parent
            marker = tmpdir.parent / (tmpdir.name.split(".tmp")[0] + ".crashed_once")
            if not marker.exists():
                marker.write_text("x")
                os._exit(17)
        return ExecResult()
