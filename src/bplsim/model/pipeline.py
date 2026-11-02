"""Pipelines: named stages, each with a backend, fidelity, equivalence choices, exports, resources."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from bplsim.backends import get_backend
from bplsim.backends.base import Backend, StageConfig
from bplsim.core.errors import ConfigError
from bplsim.model.resolve import FidelitySpec, flatten
from bplsim.units import DIMS

PIPELINE_KEYS = {"description", "extends", "stages"}
STAGE_KEYS = {"backend", "fidelity", "equivalence", "exports", "inputs", "resources"}
RESOURCE_DIMS = {"cores": None, "gpus": None, "memory": DIMS["memory"], "runtime_hint": DIMS["time"],
                 "timeout": DIMS["time"], "restartable": None}


@dataclass
class Stage:
    name: str
    backend_spec: str
    backend: Backend
    fidelity_raw: dict
    fidelity_origins: dict
    equivalence: dict
    exports: dict
    inputs: dict
    resources: dict

    def config(self, design) -> StageConfig:
        return StageConfig(self.name, self.backend.name, design.fidelity(self.name), dict(self.equivalence),
                           dict(self.exports), dict(self.inputs), dict(self.resources))


@dataclass
class Pipeline:
    id: str
    stages: dict[str, Stage] = field(default_factory=dict)

    def order(self) -> list[str]:
        """Stages in dependency order (from `inputs` references)."""
        deps = {n: {v.split(".")[0] for v in s.inputs.values()} for n, s in self.stages.items()}
        out, seen = [], set()

        def visit(n, stack=()):
            if n in seen:
                return
            if n in stack:
                raise ConfigError(f"pipeline {self.id}: stage cycle through {n}")
            for d in deps[n]:
                if d not in self.stages:
                    raise ConfigError(f"pipeline {self.id}: stage {n} takes input from unknown stage {d}")
                visit(d, stack + (n,))
            seen.add(n)
            out.append(n)
        for n in self.stages:
            visit(n)
        return out

    def fidelity_spec(self) -> FidelitySpec:
        fs = FidelitySpec()
        for n, s in self.stages.items():
            fs.stages[n] = s.backend.fidelity_specs()
            fs.raw[n] = dict(s.fidelity_raw)
            fs.origins.update({f"{n}.{k}": o for k, o in s.fidelity_origins.items()})
        return fs


def load_pipeline(project, pipeline_id: str) -> Pipeline:
    chain, seen, cur = [], set(), pipeline_id
    while cur:
        if cur in seen:
            raise ConfigError(f"pipeline inheritance cycle at {cur}")
        seen.add(cur)
        doc = project.doc(cur, "pipelines")
        for k in doc.data or {}:
            if k not in PIPELINE_KEYS:
                raise doc.error(f"unknown key {k!r} in a pipeline", k)
        chain.append(doc)
        cur = (doc.data or {}).get("extends")
    merged: dict[str, dict] = {}
    origins: dict[str, dict] = {}
    for doc in reversed(chain):
        for name, spec in ((doc.data or {}).get("stages") or {}).items():
            if spec is None:
                merged.pop(name, None)
                continue
            for k in spec:
                if k not in STAGE_KEYS:
                    raise doc.error(f"unknown stage key {k!r} (allowed: {', '.join(sorted(STAGE_KEYS))})",
                                    "stages", name, k)
            m = merged.setdefault(name, {})
            o = origins.setdefault(name, {})
            for k, v in spec.items():
                if k == "fidelity":
                    for fk, fv in flatten(v or {}).items():
                        m.setdefault("fidelity", {})[fk] = copy.deepcopy(fv)
                        o[fk] = str(doc.loc("stages", name, "fidelity", *fk.split(".")))
                elif isinstance(v, dict) and isinstance(m.get(k), dict):
                    m[k].update(copy.deepcopy(v))
                else:
                    m[k] = copy.deepcopy(v)
    p = Pipeline(pipeline_id)
    for name, spec in merged.items():
        if "backend" not in spec:
            raise ConfigError(f"pipeline {pipeline_id}: stage {name} has no backend")
        backend = get_backend(spec["backend"])
        res = {}
        for k, v in (spec.get("resources") or {}).items():
            if k not in RESOURCE_DIMS:
                raise ConfigError(f"pipeline {pipeline_id}: unknown resource {k!r} (known: {', '.join(RESOURCE_DIMS)})")
            d = RESOURCE_DIMS[k]
            res[k] = project.units.to_si(v, d) if d is not None else v
        p.stages[name] = Stage(name, spec["backend"], backend, spec.get("fidelity") or {}, origins.get(name, {}),
                               spec.get("equivalence") or {}, spec.get("exports") or {}, spec.get("inputs") or {}, res)
    p.order()
    return p
