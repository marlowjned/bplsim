"""Study specs and variables (example §12-13, plan §9.1-9.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ConfigError
from ..expr import is_expr
from ..hashing import content_hash
from ..resolve import FidelitySpec, Resolver, RowSpec
from ..units import DIMS, Dim, dim_of
from ..yamlio import YamlDoc, load_yaml

STUDY_KEYS = {"description", "production", "design", "pipeline", "measure", "overrides", "variables", "normalize",
              "objectives", "constraints", "sampler", "budget", "retention", "pin"}
VAR_KEYS = {"param", "slot", "range", "values", "choices", "scale", "sets", "unit", "type"}


@dataclass
class Variable:
    name: str
    kind: str                    # continuous | discrete | categorical
    target: str | None = None    # parameter path (param) or slot name (slot)
    target_kind: str = "param"   # param | slot | sets
    lo: float | None = None      # display units
    hi: float | None = None
    log: bool = False
    integer: bool = False
    values: list = field(default_factory=list)
    sets: dict = field(default_factory=dict)
    unit: str = ""               # display unit of continuous/discrete values
    dim: Dim | None = None

    def contains(self, v) -> bool:
        if self.kind == "continuous":
            return self.lo - 1e-12 <= float(v) <= self.hi + 1e-12
        return v in self.values

    def to_row(self, v) -> Any:
        if self.kind == "continuous" and self.integer:
            return int(round(v))
        return v


@dataclass
class Objective:
    name: str
    value: str                   # alias.output
    direction: str               # minimize | maximize


@dataclass
class Constraint:
    name: str
    value: str
    lo: float | None = None      # SI (or as stored for % and dimensionless)
    hi: float | None = None


@dataclass
class StudySpec:
    path: Path
    doc: YamlDoc
    data: dict
    name: str
    design: str
    pipeline: str
    measure_use: str | None
    measure_add: dict
    overrides: dict
    variables: dict[str, Variable]
    normalize: dict | None
    objectives: dict[str, Objective]
    constraints: dict[str, Constraint]
    sampler: dict
    budget: dict
    retention: dict
    pin: list
    production: bool

    @property
    def spec_hash(self) -> str:
        return content_hash(self.data)


def _dim_from_unit(units, unit: str) -> Dim:
    return dim_of(units.parse(f"1 {unit}")) if unit else DIMS["dimensionless"]


def load_study(project, path: str | Path) -> StudySpec:
    path = Path(path)
    doc = load_yaml(path)
    data = doc.data or {}
    for k in data:
        if k not in STUDY_KEYS:
            raise doc.error(f"unknown key {k!r} in a study (allowed: {', '.join(sorted(STUDY_KEYS))})", k)
    for req in ("design", "pipeline", "sampler"):
        if req not in data:
            raise doc.error(f"a study needs {req!r}")
    measure = data.get("measure") or {}
    if isinstance(measure, str):
        measure = {"use": measure}
    for k in measure:
        if k not in ("use", "add"):
            raise doc.error(f"unknown key {k!r} in measure (allowed: use, add)", "measure", k)
    from ..pipeline import load_pipeline
    pipeline = load_pipeline(project, data["pipeline"])
    # resolve the baseline once, to learn the targets' types and dimensions
    base = Resolver(project, data["design"], fidelity=pipeline.fidelity_spec())
    variables = {}
    for name, spec in (data.get("variables") or {}).items():
        variables[name] = _variable(project, doc, base, name, spec or {})
    objectives = {}
    for name, spec in (data.get("objectives") or {}).items():
        if not isinstance(spec, dict) or len({"minimize", "maximize"} & set(spec)) != 1:
            raise doc.error("an objective is {minimize: alias.output} or {maximize: alias.output}", "objectives", name)
        direction = "minimize" if "minimize" in spec else "maximize"
        objectives[name] = Objective(name, spec[direction], direction)
    constraints = {}
    for name, spec in (data.get("constraints") or {}).items():
        if "value" not in spec or not ({"min", "max"} & set(spec)):
            raise doc.error("a constraint is {value: alias.output, min: x and/or max: y}", "constraints", name)
        constraints[name] = Constraint(name, spec["value"], spec.get("min"), spec.get("max"))
    norm = data.get("normalize")
    if norm is not None:
        if not isinstance(norm, dict) or "scale" not in norm or "so_that" not in norm:
            raise doc.error("normalize needs 'scale' (paths) and 'so_that' {value, equals}", "normalize")
        st = norm["so_that"]
        norm = {"scale": list(norm["scale"]), "value": st["value"], "equals": st["equals"]}
    return StudySpec(path, doc, data, path.stem, data["design"], data["pipeline"], measure.get("use"),
                     measure.get("add") or {}, dict(data.get("overrides") or {}), variables, norm, objectives,
                     constraints, dict(data["sampler"]), dict(data.get("budget") or {}),
                     dict(data.get("retention") or {}), list(data.get("pin") or []), bool(data.get("production", False)))


def _variable(project, doc, base: Resolver, name: str, spec: dict) -> Variable:
    for k in spec:
        if k not in VAR_KEYS:
            raise doc.error(f"unknown variable key {k!r} (allowed: {', '.join(sorted(VAR_KEYS))})", "variables", name, k)
    units = project.units
    if name in ("params", "parts", "op", "fidelity"):
        raise doc.error(f"{name!r} is a reserved word", "variables", name)
    if "slot" in spec:
        if "choices" not in spec:
            raise doc.error("a slot variable needs 'choices' (part ids or none)", "variables", name)
        slots = base.tree.get("parts") or {}
        if spec["slot"] not in slots:
            raise doc.error(f"no slot {spec['slot']!r} in {base.assembly_id}", "variables", name, "slot")
        choices = [None if (c is None or str(c).lower() == "none") else str(c) for c in spec["choices"]]
        for c in choices:
            if c is not None:
                project.entry(c)
        return Variable(name, "categorical", spec["slot"], "slot", values=["none" if c is None else c for c in choices])
    if "sets" in spec:
        if "range" not in spec and "values" not in spec:
            raise doc.error("a 'sets' variable needs 'range' or 'values'", "variables", name)
        for path, expr in spec["sets"].items():
            if not is_expr(expr):
                raise doc.error("'sets' values must be expressions \"${ ... }\"", "variables", name, "sets", path)
        unit = spec.get("unit", "")
        v = _domain(doc, name, spec, unit, _dim_from_unit(units, unit))
        v.target_kind, v.sets = "sets", dict(spec["sets"])
        return v
    if "param" not in spec:
        raise doc.error("a variable needs 'param', 'slot' or 'sets'", "variables", name)
    path = spec["param"]
    node = base.nodes.get(path)
    if node is None:
        raise doc.error(f"no parameter {path} in {base.assembly_id} (did you mean one of: "
                        f"{', '.join(sorted(k for k in base.nodes if k.split('.')[-1] == path.split('.')[-1]))[:200]})",
                        "variables", name, "param")
    if is_expr(node["raw"]) and not node.get("default"):
        raise doc.error(f"{path} is derived ({node['raw']}); sweep the values it is computed from instead (R10)",
                        "variables", name, "param")
    pspec = node.get("spec")
    if "choices" in spec:
        return Variable(name, "categorical", path, "param", values=list(spec["choices"]))
    if pspec is not None:
        d = pspec.dim if pspec.kind == "quantity" else DIMS["dimensionless"]
        integer = pspec.kind == "int"
    else:
        raw_v, d = base.evaluate_raw(node["raw"], node.get("dim"), path)
        d = d or DIMS["dimensionless"]
        integer = isinstance(raw_v, int)
    unit = units.display.get(d.name, d.display) if d.si else ""
    v = _domain(doc, name, spec, unit, d)
    v.target = path
    v.integer = v.integer or integer or spec.get("type") == "int"
    if pspec is not None and pspec.kind == "quantity" and v.kind == "continuous":
        lo_si, hi_si = units.to_si(v.lo, d), units.to_si(v.hi, d)
        if pspec.min is not None and lo_si < pspec.min - 1e-15:
            raise doc.error(f"range starts below the parameter's minimum (R10)", "variables", name, "range")
        if pspec.max is not None and hi_si > pspec.max + 1e-15:
            raise doc.error(f"range ends above the parameter's maximum (R10)", "variables", name, "range")
    return v


def _domain(doc, name, spec, unit: str, d: Dim) -> Variable:
    if "range" in spec:
        lo, hi = spec["range"]
        if not lo < hi:
            raise doc.error("range must be [low, high] with low < high", "variables", name, "range")
        log = spec.get("scale", "linear") == "log"
        if log and lo <= 0:
            raise doc.error("a log scale needs a positive range", "variables", name, "range")
        return Variable(name, "continuous", lo=float(lo), hi=float(hi), log=log, unit=unit, dim=d,
                        integer=spec.get("type") == "int")
    if "values" in spec:
        return Variable(name, "discrete", values=list(spec["values"]), unit=unit, dim=d)
    raise doc.error("a variable needs 'range', 'values' or 'choices'", "variables", name)


def row_spec(spec: StudySpec, values: dict[str, Any]) -> RowSpec:
    """Turn sampled study-variable values into what the resolver applies."""
    rs = RowSpec()
    for path, raw in spec.overrides.items():
        rs.overrides[path] = (raw, f"study override ({spec.name})")
    for name, var in spec.variables.items():
        v = values[name]
        origin = f"study variable {name}"
        if var.target_kind == "slot":
            rs.slot_choices[var.target] = (None if v == "none" else v, origin)
        elif var.target_kind == "param":
            val = var.to_row(v)
            if var.unit and not isinstance(val, str) and var.dim is not None and var.dim.si:
                val = f"{val} {var.unit}"          # explicit units: works with and without a target schema
            rs.assignments[var.target] = (val, origin)
        else:
            raw = f"{v} {var.unit}" if var.unit else v
            rs.variables[name] = (raw, var.dim, origin)
            for path, expr in var.sets.items():
                rs.assignments[path] = (expr, f"{origin} (sets)")
        if var.target_kind != "sets":
            rs.variables[name] = (f"{v} {var.unit}" if var.unit and not isinstance(v, str) else v,
                                  var.dim if not isinstance(v, str) else None, origin)
    return rs
