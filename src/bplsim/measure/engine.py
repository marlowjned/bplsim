"""Measurement engine: measurement sets, probe/metric definitions, evaluation, combine, normalization
(plan §8)."""
from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import brentq

from ..errors import ConfigError, ResolveError
from ..hashing import content_hash, major_minor
from ..parts import REQUIRED
from ..resolve import coerce_function_param, function_params
from . import Reference
from .data import ProbeData

INJECTED = {"design", "op", "sol"}


# ---- definitions ---------------------------------------------------------------------------------
@dataclass
class ProbeDef:
    alias: str
    probe_id: str
    version: str
    params: dict
    def_hash: str = ""
    stage: str | None = None          # pipeline stage it measures (None: the last stage); not hashed

    def __post_init__(self):
        self.def_hash = content_hash({"probe": self.probe_id, "v": major_minor(self.version), "params": self.params})

    def canonical(self):
        return {"alias": self.alias, "probe": self.probe_id, "version": self.version, "params": self.params,
                "hash": self.def_hash}


@dataclass
class MetricDef:
    alias: str
    metric_id: str
    version: str
    inputs: dict          # argument name -> probe alias
    params: dict
    input_hashes: dict = field(default_factory=dict)   # argument -> probe def hash
    def_hash: str = ""
    design_only: bool = False
    outputs: dict = field(default_factory=dict)
    stage: str | None = None

    def finish(self):
        self.design_only = not self.inputs
        self.def_hash = content_hash({"metric": self.metric_id, "v": major_minor(self.version),
                                      "inputs": self.input_hashes, "params": self.params})

    def canonical(self):
        return {"alias": self.alias, "metric": self.metric_id, "version": self.version, "inputs": self.inputs,
                "input_hashes": self.input_hashes, "params": self.params, "hash": self.def_hash,
                "outputs": self.outputs}


@dataclass
class MeasurementSet:
    probes: dict = field(default_factory=dict)     # alias -> {"probe": id, "with": {...}}
    metrics: dict = field(default_factory=dict)    # alias -> {"metric": id, "inputs": {...}, "with": {...}}


def load_measurement_set(project, ms_id: str | None, add: dict | None = None) -> MeasurementSet:
    ms = MeasurementSet()
    chain, seen, cur = [], set(), ms_id
    while cur:
        if cur in seen:
            raise ConfigError(f"measurement set inheritance cycle at {cur}")
        seen.add(cur)
        doc = project.doc(cur, "measurements")
        for k in doc.data or {}:
            if k not in ("description", "extends", "probes", "metrics"):
                raise doc.error(f"unknown key {k!r} in a measurement set", k)
        chain.append(doc.data or {})
        cur = (doc.data or {}).get("extends")
    for data in reversed(chain):
        _merge_ms(ms, data, f"measurement set")
    if add:
        # study shorthand: `add:` lists metric aliases directly; `add: {probes: ..., metrics: ...}` also works
        if set(add) <= {"probes", "metrics"}:
            _merge_ms(ms, add, "study measure.add")
        else:
            _merge_ms(ms, {"metrics": add}, "study measure.add")
    return ms


def _merge_ms(ms: MeasurementSet, data: dict, where: str):
    unknown = set(data) - {"probes", "metrics", "description", "extends"}
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)} (allowed: probes, metrics)")
    for alias, spec in (data.get("probes") or {}).items():
        if spec is None:
            ms.probes.pop(alias, None)
            continue
        if "probe" not in spec:
            raise ConfigError(f"{where}: probe alias {alias!r} needs 'probe'")
        bad = set(spec) - {"probe", "with", "stage"}
        if bad:
            raise ConfigError(f"{where}: probe alias {alias!r}: unknown key(s) {sorted(bad)}")
        ms.probes[alias] = {"probe": spec["probe"], "with": dict(spec.get("with") or {}), "stage": spec.get("stage")}
    for alias, spec in (data.get("metrics") or {}).items():
        if spec is None:
            ms.metrics.pop(alias, None)
            continue
        if "metric" not in spec:
            raise ConfigError(f"{where}: metric alias {alias!r} needs 'metric'")
        bad = set(spec) - {"metric", "inputs", "with", "stage"}
        if bad:
            raise ConfigError(f"{where}: metric alias {alias!r}: unknown key(s) {sorted(bad)}")
        ms.metrics[alias] = {"metric": spec["metric"], "inputs": dict(spec.get("inputs") or {}),
                             "with": dict(spec.get("with") or {}), "stage": spec.get("stage")}


def _resolve_params(design, fn, raw: dict, skip: set, where: str, project) -> dict:
    specs = function_params(fn, skip)
    for k in raw:
        if k not in specs:
            raise ResolveError(f"unknown parameter {k!r} (has: {', '.join(specs) or 'none'})", path=where)
    out = {}
    for name, spec in specs.items():
        ann = getattr(spec, "_ann", None)
        value = raw.get(name, spec.default)
        if ann is Reference or (isinstance(ann, type) and issubclass(ann, Reference)):
            if value is REQUIRED or value is None:
                raise ResolveError(f"parameter {name!r} needs a reference", path=where)
            out[name] = _resolve_reference(design, value, f"{where}.{name}", project)
            continue
        if value is REQUIRED:
            raise ResolveError(f"required parameter {name!r} not given", path=where)
        out[name] = coerce_function_param(design, spec, value, f"{where}.{name}")
    return out


def _resolve_reference(design, value, where, project) -> dict:
    if isinstance(value, str):
        rid, raw = value, {}
    else:
        rid, raw = value.get("id"), value.get("with") or {}
    e = project.entry(rid, "references")
    if not e.is_python:
        return {"reference": rid, "params": {}}
    fn = project.reference(rid)
    params = _resolve_params(design, fn, raw, {"design", "z"}, where, project)
    return {"reference": rid, "params": params}


def define_measurements(project, design, ms: MeasurementSet, extra_probes: dict | None = None) \
        -> tuple[dict[str, ProbeDef], dict[str, MetricDef]]:
    """Resolve probe and metric parameters in this row's context."""
    probes: dict[str, ProbeDef] = {}
    all_probes = dict(ms.probes)
    all_probes.update(extra_probes or {})
    for alias, spec in all_probes.items():
        fn = project.probe(spec["probe"])
        params = _resolve_params(design, fn, spec["with"], {"design", "sol"}, f"probes.{alias}", project)
        probes[alias] = ProbeDef(alias, spec["probe"], fn._bplsim["version"], params, stage=spec.get("stage"))
    metrics: dict[str, MetricDef] = {}
    for alias, spec in ms.metrics.items():
        fn = project.metric(spec["metric"])
        info = fn._bplsim
        declared = info["inputs"]
        for arg in declared:
            if arg not in spec["inputs"]:
                raise ResolveError(f"metric {spec['metric']} needs input {arg!r} ({declared[arg]}); "
                                   "connect it to a probe alias", path=f"metrics.{alias}.inputs")
        for arg, palias in spec["inputs"].items():
            if arg not in declared:
                raise ResolveError(f"metric {spec['metric']} has no input {arg!r}", path=f"metrics.{alias}.inputs")
            if palias not in probes:
                raise ResolveError(f"no probe alias {palias!r} (probes: {', '.join(probes)})",
                                   path=f"metrics.{alias}.inputs.{arg}")
        skip = INJECTED | set(declared)
        params = _resolve_params(design, fn, spec["with"], skip, f"metrics.{alias}", project)
        md = MetricDef(alias, spec["metric"], info["version"], dict(spec["inputs"]), params,
                       {a: probes[p].def_hash for a, p in spec["inputs"].items()},
                       outputs=info["outputs"] if isinstance(info["outputs"], dict) else {},
                       stage=spec.get("stage"))
        md.finish()
        stages = {probes[p].stage for p in spec["inputs"].values()}
        if len(stages) > 1:
            raise ResolveError(f"metric inputs come from different stages {sorted(map(str, stages))}",
                               path=f"metrics.{alias}")
        if stages and md.stage is None:
            md.stage = next(iter(stages))
        metrics[alias] = md
    return probes, metrics


# ---- evaluation ----------------------------------------------------------------------------------
def evaluate_probe(project, design, pdef: ProbeDef, sol) -> ProbeData:
    fn = project.probe(pdef.probe_id)
    data = fn(design, sol, **pdef.params)
    if not isinstance(data, ProbeData):
        raise ConfigError(f"probe {pdef.probe_id} returned {type(data).__name__}, not ProbeData")
    data.attrs.setdefault("probe", pdef.probe_id)
    return data


def _call(fn, kwargs: dict, design, op):
    sig = inspect.signature(fn)
    if "design" in sig.parameters:
        kwargs["design"] = design
    if "op" in sig.parameters:
        kwargs["op"] = op
    return fn(**kwargs)


def _bind_params(project, design, params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if isinstance(v, dict) and "reference" in v and set(v) <= {"reference", "params"}:
            fn = project.reference(v["reference"])
            out[k] = Reference(fn, design, v["params"], v["reference"])
        else:
            out[k] = v
    return out


def evaluate_metric(project, design, mdef: MetricDef, inputs: dict[str, ProbeData], op=None) -> dict:
    fn = project.metric(mdef.metric_id)
    kwargs = {arg: inputs[arg] for arg in mdef.inputs}
    kwargs.update(_bind_params(project, design, mdef.params))
    res = _call(fn, kwargs, design, op if op is not None else design.op)
    if not isinstance(res, dict):
        raise ConfigError(f"metric {mdef.metric_id} returned {type(res).__name__}, not a dict")
    declared = mdef.outputs
    if declared:
        missing = [k for k in declared if k not in res]
        if missing:
            raise ConfigError(f"metric {mdef.metric_id} did not return {', '.join(missing)}")
    return res


def call_design_metric(design, metric_id: str, raw_with: dict, where: str) -> dict:
    """Evaluate a design-only metric (assembly checks)."""
    project = design.project
    fn = project.metric(metric_id)
    if fn._bplsim["inputs"]:
        raise ConfigError(f"{metric_id} needs probe inputs, so it cannot be a design check", path=where)
    params = _resolve_params(design, fn, raw_with, INJECTED, where, project)
    return _call(fn, _bind_params(project, design, params), design, design.op)


def reads_paths(project, design, mdef: MetricDef) -> list[str]:
    """Run a design-only metric with a recording op proxy; return the op paths it read."""
    rec: list[str] = []
    fn = project.metric(mdef.metric_id)
    try:
        _call(fn, _bind_params(project, design, mdef.params), design, design.op_view(rec))
    except Exception:  # noqa: BLE001 - only the access pattern matters here
        pass
    return rec


# ---- combine and normalization -------------------------------------------------------------------
def basis_weights(design, bases: list[dict]) -> dict[str, float]:
    """Weight of each basis for this design's (possibly normalized) currents."""
    w = {}
    for b in bases:
        if b["name"] == "all" or not b["currents"]:
            w[b["name"]] = 1.0
        else:
            (circ,) = [c for c, v in b["currents"].items() if v]
            w[b["name"]] = float(design.value(f"op.circuits.{circ}.current"))
    return w


def combined(case_data: dict[str, dict[str, ProbeData]], def_hash: str, weights: dict[str, float]) -> ProbeData:
    per_basis = case_data[def_hash]
    return ProbeData.combine([(weights[b], d) for b, d in per_basis.items()])


def compute_metrics(project, design, mdefs: dict[str, MetricDef], case_data, bases: list[dict],
                    only: list[str] | None = None) -> dict[str, dict]:
    weights = basis_weights(design, bases)
    out = {}
    for alias, md in mdefs.items():
        if only is not None and alias not in only:
            continue
        inputs = {arg: combined(case_data, h, weights) for arg, h in md.input_hashes.items()}
        out[alias] = evaluate_metric(project, design, md, inputs)
    return out


def normalize(project, design, mdefs, case_data, bases, spec: dict, superposed: bool) -> dict[str, float]:
    """Find k so that `so_that.value` equals the target with every `scale` path multiplied by k.
    Returns {path: normalized SI value}; also stores them in design.normalized."""
    if not superposed:
        raise ConfigError("normalization of a non-superposed (nonlinear) case needs iterative solves; "
                          "run it through the driver's nonlinear normalization")
    alias, _, output = spec["value"].partition(".")
    if alias not in mdefs:
        raise ConfigError(f"normalize: no metric alias {alias!r}")
    md = mdefs[alias]
    target = spec["target_si"]
    paths = spec["scale"]
    base = {p: float(design.value(p)) for p in paths}

    def f(k):
        design.normalized = {p: k * v for p, v in base.items()}
        r = compute_metrics(project, design, {alias: md}, case_data, bases)[alias][output]
        return float(r) - target

    f1 = f(1.0) + target
    if f1 == 0 or not math.isfinite(f1):
        raise ConfigError(f"normalize: {spec['value']} is {f1} at the nominal values; cannot scale")
    k = target / f1
    fk = f(k)
    if abs(fk) > 1e-9 * max(1.0, abs(target)):
        lo, hi = k / 2, k * 2
        for _ in range(60):
            if np.sign(f(lo)) != np.sign(f(hi)):
                break
            lo, hi = lo / 2, hi * 2
        k = brentq(f, lo, hi, xtol=1e-14, rtol=1e-12)
    design.normalized = {p: k * v for p, v in base.items()}
    return dict(design.normalized)
