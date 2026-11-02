"""warpx: particle-in-cell stage (plan §7.6), consuming a field map exported by an upstream stage.

The WarpX input deck is a Jinja template from the project (fidelity `deck`, a path relative to the project
root), rendered with:
    fid      this stage's fidelity values (SI)          op      operating-point values (SI)
    params   assembly parameters (SI)                  parts   {slot: {param: value}} (SI)
    inputs   {input name: path of the upstream export file (openPMD)}
The rendered deck is part of the case hash. WarpX writes openPMD (HDF5) field diagnostics, which field
access interpolates, and reduced diagnostics (text), which `scalars()` returns (last row).

The bundled `default_rz.j2` is a starting point to validate against the installed WarpX version: WarpX
parameter names change between releases.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import numpy as np

from bplsim.core.errors import BackendError
from bplsim.parts import Param
from bplsim.execute.sites import find_tool
from bplsim.backends.base import Backend, Basis, Capabilities, ExecResult, FieldAccess, StageConfig

HERE = Path(__file__).parent


def _render(text: str, ctx: dict) -> str:
    import jinja2
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    return env.from_string(text).render(**ctx)


class WarpX(Backend):
    name = "warpx"
    version = "0.1.0"
    capabilities = Capabilities(dims=2, symmetry="axisymmetric", superposable=False, consumes=("fieldmap",),
                                restartable=True)
    measure_needs_raw = True
    FIDELITY = {
        "deck": Param(""),                    # template path relative to the project root; "" = bundled default
        "geometry": Param("rz", choices=["rz", "3d"]),
        "cells": Param("64 128"),
        "steps": Param(1000),
        "particles_per_cell": Param(8),
        "diag_period": Param(100),
        "mpi_ranks": Param(1),
    }

    def check(self, design, stage: StageConfig) -> list[str]:
        return [] if stage.inputs else ["the warpx stage needs an upstream field map (pipeline `inputs`)"]

    def solve_inputs(self, design, stage: StageConfig) -> dict:
        f = dict(stage.fidelity)
        deck_path = f.get("deck") or ""
        text = (Path(design.project.root) / deck_path).read_text() if deck_path else \
            (HERE / "default_rz.j2").read_text()
        values = design.values
        ctx = {"params": {k[7:]: v for k, v in values.items() if k.startswith("params.")},
               "op": {k[3:]: v for k, v in values.items() if k.startswith("op.")},
               "parts": {}}
        for k, v in values.items():
            if k.startswith("parts."):
                _, slot, name = k.split(".", 2)
                ctx["parts"].setdefault(slot, {})[name] = v if not hasattr(v, "id") else v.id
        ctx["op"].update({k[3:]: v for k, v in design.normalized.items() if k.startswith("op.")})
        return {"deck_template": text, "context": ctx, "fidelity": f, "circuits": []}

    def bases(self, design, stage, inputs):
        return [Basis("all", {})]

    def prepare(self, inputs: dict, workdir: Path) -> None:
        workdir = Path(workdir)
        ctx = dict(inputs["context"], fid=inputs["fidelity"], inputs=inputs.get("_upstream_files", {}))
        missing = [k for k, p in ctx["inputs"].items() if not Path(p).exists()]
        if missing:
            raise BackendError(f"upstream export(s) missing: {missing}")
        (workdir / "inputs").write_text(_render(inputs["deck_template"], ctx))

    def execute(self, inputs: dict, workdir: Path, basis: Basis, resources: dict) -> ExecResult:
        workdir = Path(workdir)
        exe = find_tool("warpx", ("warpx.rz", "warpx.3d", "warpx.2d"))
        if not exe:
            raise BackendError("WarpX not found: set tools.warpx in the site profile, BPLSIM_TOOL_WARPX, or PATH")
        cmd = shlex.split(exe, posix=False)
        ranks = int(inputs["fidelity"].get("mpi_ranks", 1))
        if ranks > 1:
            cmd = ["mpiexec", "-n", str(ranks)] + cmd
        chk = sorted((workdir / "diags").glob("chk*")) if (workdir / "diags").exists() else []
        args = ["inputs"] + ([f"amr.restart={chk[-1].as_posix()}"] if chk else [])
        timeout = float(resources.get("timeout") or 48 * 3600)
        try:
            r = subprocess.run(cmd + args, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            chk = sorted((workdir / "diags").glob("chk*")) if (workdir / "diags").exists() else []
            if chk:
                return ExecResult("incomplete", "walltime reached", restart_token=str(chk[-1]))
            return ExecResult("failed", f"warpx timed out after {timeout:.0f} s with no checkpoint")
        (workdir / "warpx.log").write_text(r.stdout + r.stderr)
        if r.returncode != 0:
            return ExecResult("failed", f"warpx failed: {(r.stdout + r.stderr)[-1500:]}")
        return ExecResult()

    def field_access(self, inputs: dict, workdir: Path, basis: Basis) -> FieldAccess:
        return WarpXField(Path(workdir))


class WarpXField(FieldAccess):
    symmetry = "axisymmetric"

    def __init__(self, workdir: Path):
        self.dir = workdir

    def _last_diag(self) -> Path:
        files = sorted((self.dir / "diags").rglob("openpmd_*.h5"))
        if not files:
            raise BackendError(f"no openPMD field diagnostics in {self.dir / 'diags'}")
        return files[-1]

    def sample(self, where, fields=("B",)):
        from scipy.interpolate import RegularGridInterpolator
        from bplsim.measure.data import ProbeData
        from bplsim.measure.openpmd import read_field
        out = {}
        for name in fields:
            axes, comps = read_field(self._last_diag(), name)
            labels = list(axes)
            r, th, z = np.ravel(where.r), np.ravel(where.theta), np.ravel(where.z)
            if labels == ["r", "z"]:
                pts = np.column_stack([r, z])
                for c, arr in comps.items():
                    f = RegularGridInterpolator((axes["r"], axes["z"]), arr, bounds_error=False, fill_value=np.nan)
                    key = {"r": "r", "t": "theta", "z": "z"}.get(c, c)
                    out[f"{name}_{key}"] = f(pts).reshape(where.shape)
            else:
                pts = np.column_stack([r * np.cos(th), r * np.sin(th), z])
                vals = {c: RegularGridInterpolator(tuple(axes[a] for a in labels), arr, bounds_error=False,
                                                   fill_value=np.nan)(pts) for c, arr in comps.items()}
                if {"x", "y"} <= set(vals):
                    out[f"{name}_r"] = (vals["x"] * np.cos(th) + vals["y"] * np.sin(th)).reshape(where.shape)
                    out[f"{name}_theta"] = (-vals["x"] * np.sin(th) + vals["y"] * np.cos(th)).reshape(where.shape)
                    out[f"{name}_z"] = vals["z"].reshape(where.shape)
                else:
                    out.update({f"{name}_{c}": v.reshape(where.shape) for c, v in vals.items()})
        return ProbeData({"r": where.r, "theta": where.theta, "z": where.z}, out, {"symmetry": "axisymmetric"},
                         where.axes)

    def scalars(self, names=None):
        """Last row of every reduced diagnostic (diags/reducedfiles/*.txt); columns named file.column."""
        from bplsim.measure.data import ProbeData
        vals = {}
        for f in sorted((self.dir / "diags" / "reducedfiles").glob("*.txt")):
            lines = [ln for ln in f.read_text().splitlines() if ln.strip()]
            header = lines[0].lstrip("#").split()
            last = lines[-1].split()
            for h, v in zip(header, last):
                col = h.split("]", 1)[-1].split("(")[0]
                vals[f"{f.stem}.{col}"] = float(v)
        if names:
            vals = {k: v for k, v in vals.items() if k in names}
        return ProbeData({}, {k: np.array(v) for k, v in vals.items()}, {})
