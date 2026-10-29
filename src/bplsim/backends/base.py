"""Backend interface (plan §7.1).

A backend turns a resolved design into a solve and gives probes access to the solution through
FieldAccess. Everything it writes goes into the workdir it is given.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import BackendError
from ..parts import Param, ParamSpec, spec_from


@dataclass(frozen=True)
class Capabilities:
    dims: int = 2
    symmetry: str = "axisymmetric"              # "axisymmetric" | "none"
    superposable: bool = True                   # linear in circuit currents when the fidelity is linear
    consumes: tuple[str, ...] = ()
    restartable: bool = False


@dataclass
class Basis:
    """One solve of a case. currents: circuit -> A applied in this solve."""
    name: str
    currents: dict[str, float]

    def canonical(self):
        return {"name": self.name, "currents": self.currents}


@dataclass
class StageConfig:
    """A pipeline stage as seen by its backend, with this row's fidelity values (SI)."""
    name: str
    backend: str
    fidelity: dict[str, Any] = field(default_factory=dict)
    equivalence: dict[str, str] = field(default_factory=dict)
    exports: dict[str, dict] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)

    def canonical(self):
        return {"name": self.name, "backend": self.backend, "fidelity": self.fidelity,
                "equivalence": self.equivalence}


@dataclass
class ExecResult:
    status: str = "ok"                 # ok | failed | incomplete
    reason: str = ""
    restart_token: Any = None


class FieldAccess:
    """How probes read a solution. Points are in the global (r, theta, z) frame; vector fields are
    returned as cylindrical components (B_r, B_theta, B_z)."""
    symmetry: str = "axisymmetric"
    fields: tuple[str, ...] = ("B",)

    def sample(self, where, fields=("B",)):
        raise BackendError(f"{type(self).__name__} cannot sample points")

    def region(self, part: str, fields=("B",)):
        raise BackendError(f"{type(self).__name__} cannot return region data")

    def boundary(self, surface: str, fields=("B",)):
        raise BackendError(f"{type(self).__name__} cannot return boundary data")

    def scalars(self, names=None):
        raise BackendError(f"{type(self).__name__} has no scalar outputs")

    def export_grid(self, grid: dict, fields=("B",), fmt: str = "npz", path: Path | None = None):
        raise BackendError(f"{type(self).__name__} cannot export grids")


class Backend:
    name: str = ""
    version: str = "0.0.0"
    capabilities: Capabilities = Capabilities()
    FIDELITY: dict[str, Any] = {}            # dotted key -> Param (with dim=...) or plain default

    @classmethod
    def fidelity_specs(cls) -> dict[str, ParamSpec]:
        out = {}
        for k, v in cls.FIDELITY.items():
            if isinstance(v, Param):
                ann = bool if isinstance(v.default, bool) else (int if isinstance(v.default, int) and v.dim is None
                                                               else (str if isinstance(v.default, str) else float))
                out[k] = spec_from(k, ann, v)
            else:
                ann = type(v) if v is not None else str
                out[k] = spec_from(k, ann, v)
        return out

    def superposed(self, stage: StageConfig) -> bool:
        return self.capabilities.superposable and not stage.fidelity.get("nonlinear", False)

    # ---- the interface ----------------------------------------------------------------------------
    def check(self, design, stage: StageConfig) -> list[str]:
        return []

    def solve_inputs(self, design, stage: StageConfig) -> dict:
        raise NotImplementedError

    def bases(self, design, stage: StageConfig, inputs: dict) -> list[Basis]:
        circuits = sorted({c for c in inputs.get("circuits", [])})
        if self.superposed(stage):
            return [Basis(c, {cc: (1.0 if cc == c else 0.0) for cc in circuits}) for c in circuits] or \
                [Basis("none", {})]
        currents = {c: float(design.value(f"op.circuits.{c}.current")) for c in circuits}
        return [Basis("all", currents)]

    def prepare(self, inputs: dict, workdir: Path) -> None:
        pass

    def execute(self, inputs: dict, workdir: Path, basis: Basis, resources: dict) -> ExecResult:
        return ExecResult()

    def field_access(self, inputs: dict, workdir: Path, basis: Basis) -> FieldAccess:
        raise NotImplementedError

    def tool_version(self) -> str:
        return ""


def regions_inputs(design, stage: StageConfig, linear: bool) -> tuple[list, dict, list[str]]:
    """Placed r-z regions for a 2-D backend, the materials they use, and the circuits present."""
    regions = []
    for slot in design.slots:
        part = design.part(slot)
        rule = stage.equivalence.get(slot)
        if rule is None and not part.axisymmetric:
            eqs = part.type_cls.equivalences()
            defaults = [n for n, f in eqs.items() if f._bplsim_equivalence.get("default")]
            if len(defaults) == 1:
                rule = defaults[0]
            else:
                raise BackendError(f"part {slot} ({part.type_id}) is not axisymmetric; choose an equivalence "
                                   f"rule in the pipeline ({', '.join(eqs) or 'none defined'})")
        if rule is not None:
            info = part.type_cls.equivalences()[rule]._bplsim_equivalence
            if info.get("valid_for") == "linear" and not linear:
                raise BackendError(f"equivalence rule {rule!r} of {slot} is only valid for linear materials, "
                                   "but this stage is nonlinear")
        regions.extend(part.regions_rz(rule))
    circuits = sorted({r.excitation["circuit"] for r in regions if r.excitation})
    return regions, {}, circuits
