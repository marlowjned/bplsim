"""Resolution: assembly + study row -> one ResolvedDesign (plan §5, example §12).

Values are evaluated lazily on demand (decision K5) with memoisation and cycle detection, so
``a if parts.pole_cap else 0`` never touches the untaken branch.
"""
from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, Callable

from .assembly import Tree, load_assembly
from .errors import ConfigError, ExpressionError, ResolveError
from .expr import Expr, SlotPresent, coerce, is_expr
from .hashing import quantize
from .materials import Material
from .parts import REQUIRED, Margin, ParamSpec, PartType, Slot, _analyze, params_of
from .units import DIMS, Q_, Dim, UnitSystem, dim_of

OP_SCHEMA: dict[str, Dim] = {"temperature": DIMS["temperature"]}


def op_dim(path: str) -> Dim | None:
    """Dimension of an op leaf path (without the leading 'op.')."""
    if path in OP_SCHEMA:
        return OP_SCHEMA[path]
    parts = path.split(".")
    if len(parts) == 3 and parts[0] == "circuits" and parts[2] == "current":
        return DIMS["current"]
    return None


def flatten(d: dict, prefix: str = "") -> dict[str, Any]:
    out = {}
    for k, v in (d or {}).items():
        p = f"{prefix}{k}"
        if isinstance(v, dict) and not _is_leaf_mapping(v):
            out.update(flatten(v, p + "."))
        else:
            out[p] = v
    return out


def _is_leaf_mapping(v: dict) -> bool:
    return False


# =================================================================================================
@dataclass
class RowSpec:
    """What a study row adds on top of the assembly."""
    overrides: dict[str, tuple[Any, str]] = field(default_factory=dict)       # path -> (raw, origin)
    slot_choices: dict[str, tuple[str | None, str]] = field(default_factory=dict)  # slot -> (part id|None, origin)
    variables: dict[str, tuple[Any, Dim | None, str]] = field(default_factory=dict)  # name -> (raw, dim, origin)
    assignments: dict[str, tuple[Any, str]] = field(default_factory=dict)     # path -> (raw or expr, origin)


@dataclass
class FidelitySpec:
    stages: dict[str, dict[str, ParamSpec]] = field(default_factory=dict)     # stage -> dotted key -> spec
    raw: dict[str, dict[str, Any]] = field(default_factory=dict)              # stage -> dotted key -> raw
    origins: dict[str, str] = field(default_factory=dict)                     # "stage.key" -> origin


# =================================================================================================
class ParamView:
    """`p` inside part-type code: attribute access to the part's parameters (SI floats, ints, ...)."""

    def __init__(self, part: "ResolvedPart"):
        object.__setattr__(self, "_part", part)

    def __getattr__(self, name: str):
        part = object.__getattribute__(self, "_part")
        if name in part.specs:
            return part.param(name)
        if not part._computing_derived and name in part.derived:
            return part.derived[name]
        raise AttributeError(f"{part.type_id} has no parameter {name!r}"
                             + (" (derived values are not available inside derived())" if part._computing_derived
                                else ""))

    def __setattr__(self, k, v):
        raise AttributeError("part parameters are read-only")


class ResolvedPart:
    """A slot's part with resolved values. Attributes: parameters, then derived values, then part-type
    methods (called without `p`)."""

    def __init__(self, design: "ResolvedDesign", slot: str, type_cls: type, at_path: str):
        self._design = design
        self.slot = slot
        self.type_cls = type_cls
        self.type_id = getattr(type_cls, "_entry_id", type_cls.__name__)
        self.specs = type_cls.param_specs()
        self._instance = type_cls()
        self._derived: dict | None = None
        self._computing_derived = False
        self.p = ParamView(self)

    @property
    def name(self) -> str:
        return self.slot

    @property
    def at(self) -> float:
        return self._design.value(f"parts.{self.slot}.at")

    def param(self, name: str):
        v = self._design.value(f"parts.{self.slot}.{name}")
        spec = self.specs[name]
        if spec.kind == "slot" and v is not None:
            return self._design.part(v)
        return v

    @property
    def derived(self) -> dict:
        if self._derived is None:
            self._computing_derived = True
            try:
                self._derived = dict(self._instance.derived(self.p) or {})
            finally:
                self._computing_derived = False
        return self._derived

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self.specs:
            return self.param(name)
        if name in self.derived:
            return self.derived[name]
        attr = getattr(self._instance, name, None)
        if attr is not None and callable(attr):
            return lambda *a, **k: attr(self.p, *a, **k)
        raise AttributeError(f"part {self.slot} ({self.type_id}) has no parameter, derived value or method {name!r}")

    @property
    def axisymmetric(self) -> bool:
        return bool(self._instance.axisymmetric(self.p))

    def checks(self) -> list[Margin]:
        return list(self._instance.checks(self.p) or [])

    def regions_rz(self, rule: str | None = None) -> list:
        from .geom.rz import as_regions
        if rule:
            eq = self.type_cls.equivalences().get(rule)
            if eq is None:
                raise ConfigError(f"part type {self.type_id} has no equivalence rule {rule!r} "
                                  f"(has: {', '.join(self.type_cls.equivalences()) or 'none'})")
            regs = as_regions(eq(self._instance, self.p))
        elif self.axisymmetric:
            regs = as_regions(self._instance.profile_rz(self.p))
        else:
            raise ConfigError(f"part {self.slot} ({self.type_id}) is not axisymmetric; choose an equivalence rule "
                              f"({', '.join(self.type_cls.equivalences()) or 'none defined'})")
        return [r.placed(self.at, name=self.slot) for r in regs]

    def solid(self):
        if self.type_cls.solid_3d is None:
            return None
        return self._instance.solid_3d(self.p)

    def __repr__(self) -> str:
        return f"<part {self.slot}: {self.type_id}>"


class Circuits:
    def __init__(self, op: "OpView"):
        self._op = op

    def __getitem__(self, name: str) -> "OpView":
        if f"circuits.{name}.current" not in self._op._design._op_paths():
            raise KeyError(f"no circuit {name!r} in the operating point")
        return OpView(self._op._design, f"circuits.{name}", self._op._record)

    def names(self) -> list[str]:
        return sorted({p.split(".")[1] for p in self._op._design._op_paths() if p.startswith("circuits.")})


class OpView:
    """`op` in metrics: attribute access to operating-point values; records which paths were read."""

    def __init__(self, design: "ResolvedDesign", prefix: str = "", record: list | None = None):
        self._design, self._prefix, self._record = design, prefix, record

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        path = f"{self._prefix}.{name}" if self._prefix else name
        if path == "circuits":
            return Circuits(self)
        leaves = self._design._op_paths()
        if path in leaves:
            if self._record is not None:
                self._record.append("op." + path)
            return self._design.value("op." + path)
        if any(p.startswith(path + ".") for p in leaves):
            return OpView(self._design, path, self._record)
        raise AttributeError(f"no operating-point value op.{path}")


class ResolvedDesign:
    """The design a row resolves to. Values are SI floats (dims in `dims`), ints, strings, Materials."""

    def __init__(self, project, assembly_id: str):
        self.project = project
        self.assembly_id = assembly_id
        self.values: dict[str, Any] = {}
        self.dims: dict[str, Dim | None] = {}
        self.origins: dict[str, str] = {}
        self.slots: dict[str, type] = {}           # occupied slot -> part type class
        self._parts: dict[str, ResolvedPart] = {}
        self._resolver: "Resolver | None" = None
        self.normalized: dict[str, float] = {}
        self.checks_spec: dict = {}
        self.declared_slots: set[str] = set()

    # ---- access ------------------------------------------------------------------------------
    def value(self, path: str):
        if path in self.normalized:
            return self.normalized[path]
        if path in self.values:
            return self.values[path]
        if self._resolver is not None:
            return self._resolver.value(path)
        raise KeyError(f"no value at {path}")

    def part(self, slot: str) -> ResolvedPart:
        if slot not in self.slots:
            raise KeyError(f"slot {slot!r} is empty or does not exist")
        if slot not in self._parts:
            self._parts[slot] = ResolvedPart(self, slot, self.slots[slot], f"parts.{slot}.at")
        return self._parts[slot]

    @property
    def parts(self) -> dict[str, ResolvedPart]:
        return {s: self.part(s) for s in self.slots}

    def parts_of(self, base: type) -> list[ResolvedPart]:
        return [self.part(s) for s, cls in self.slots.items() if issubclass(cls, base)]

    @property
    def op(self) -> OpView:
        return OpView(self)

    def op_view(self, record: list | None = None) -> OpView:
        return OpView(self, "", record)

    def _op_paths(self) -> set[str]:
        return {p[3:] for p in self.values if p.startswith("op.")} | \
               ({p[3:] for p in self._resolver.nodes if p.startswith("op.")} if self._resolver else set())

    def params(self, prefix: str) -> dict[str, Any]:
        n = len(prefix) + 1
        return {p[n:]: v for p, v in self.values.items() if p.startswith(prefix + ".")}

    def fidelity(self, stage: str) -> dict[str, Any]:
        return self.params(f"fidelity.{stage}")

    def evaluate(self, raw: Any, target: Dim | None = None, where: str = ""):
        """Evaluate a YAML value (number, unit string or expression) in this row's context."""
        if self._resolver is None:
            raise ResolveError("this design has no resolver (reconstructed in a worker)")
        return self._resolver.evaluate_raw(raw, target, where)

    # ---- geometry ----------------------------------------------------------------------------
    def regions_rz(self, equivalences: dict[str, str] | None = None) -> list:
        equivalences = equivalences or {}
        out = []
        for slot in self.slots:
            out.extend(self.part(slot).regions_rz(equivalences.get(slot)))
        return out

    # ---- canonical form ----------------------------------------------------------------------
    def canonical(self) -> dict:
        vals, dims, mats = {}, {}, {}
        for p, v in sorted(self.values.items()):
            if isinstance(v, Material):
                vals[p] = {"material": v.id}
                mats[v.id] = v.canonical()
            elif isinstance(v, float):
                vals[p] = quantize(v)
            else:
                vals[p] = v
            d = self.dims.get(p)
            if d is not None:
                dims[p] = d.name
        slots = {s: getattr(c, "_entry_id", c.__name__) for s, c in sorted(self.slots.items())}
        out = {"assembly": self.assembly_id, "slots": slots, "values": vals, "dims": dims, "materials": mats}
        if self.normalized:
            out["normalized"] = {k: quantize(v) for k, v in sorted(self.normalized.items())}
        return out

    @classmethod
    def from_canonical(cls, project, canon: dict) -> "ResolvedDesign":
        d = cls(project, canon["assembly"])
        for slot, tid in canon["slots"].items():
            d.slots[slot] = project.part_type(tid)
        for p, v in canon["values"].items():
            if isinstance(v, dict) and "material" in v:
                v = project.material(v["material"])
            d.values[p] = v
        for p, name in canon.get("dims", {}).items():
            d.dims[p] = DIMS.get(name)
        d.normalized = dict(canon.get("normalized", {}))
        return d

    def show(self, units: UnitSystem | None = None) -> list[tuple[str, str, str]]:
        units = units or self.project.units
        rows = []
        for p in sorted(self.values):
            v = self.values[p]
            d = self.dims.get(p)
            if isinstance(v, Material):
                s = v.id
            elif isinstance(v, float):
                s = units.show(v, d)
            else:
                s = str(v)
            rows.append((p, s, self.origins.get(p, "")))
        return rows


# =================================================================================================
class Resolver:
    def __init__(self, project, assembly_id: str, row: RowSpec | None = None,
                 fidelity: FidelitySpec | None = None):
        self.project = project
        self.units: UnitSystem = project.units
        self.assembly_id = assembly_id
        self.row = row or RowSpec()
        self.fid = fidelity or FidelitySpec()
        self.tree, self.docs = load_assembly(project, assembly_id)
        self.design = ResolvedDesign(project, assembly_id)
        self.design._resolver = self
        self.nodes: dict[str, dict] = {}       # path -> {"raw", "origin", "spec"|"dim"}
        self._busy: list[str] = []
        self._derived_busy: set[str] = set()
        self._apply_row_structure()
        self._build_nodes()

    # ---- structure -----------------------------------------------------------------------------
    def _apply_row_structure(self):
        t = self.tree
        for path, (raw, origin) in self.row.overrides.items():
            parts = path.split(".")
            if parts[0] == "fidelity":
                stage, key = parts[1], ".".join(parts[2:])
                self.fid.raw.setdefault(stage, {})[key] = raw
                self.fid.origins[f"{stage}.{key}"] = origin
                continue
            if parts[0] == "parts" and len(parts) >= 3 and parts[2] not in ("at",):
                t.set(("parts", parts[1], "params", *parts[2:]), raw, origin=origin)
            else:
                t.set(tuple(parts), raw, origin=origin)
        for slot, (choice, origin) in self.row.slot_choices.items():
            existing = t.get("parts", slot)
            if existing is None and slot not in (t.data.get("parts") or {}):
                raise ResolveError(f"study chooses slot {slot!r}, which the assembly does not have")
            if choice is None:
                if not (existing or {}).get("optional"):
                    raise ResolveError(f"slot {slot!r} is not optional, so the study cannot choose 'none'")
                keep = {k: existing[k] for k in ("at", "optional") if k in existing}
                keep["_empty"] = True
                t.set(("parts", slot), keep, origin=origin)
            else:
                keep = {k: existing[k] for k in ("at", "optional") if k in (existing or {})}
                kind = "use" if ":parts/" in choice else "type"
                keep[kind] = choice
                orig = {k: t.origin("parts", slot, k) for k in ("at", "optional") if k in keep}
                t.set(("parts", slot), keep, origin=origin)
                for k, o in orig.items():
                    t.origins[("parts", slot, k)] = o

    def _build_nodes(self):
        t, n = self.tree, self.nodes
        for k, raw in (t.get("params") or {}).items():
            n[f"params.{k}"] = {"raw": raw, "origin": t.origin("params", k), "dim": None}
        for slot, spec in (t.get("parts") or {}).items():
            if spec is None or spec.get("_empty"):
                continue
            type_id, part_params, part_origin = self._slot_type(slot, spec)
            cls = self.project.part_type(type_id)
            self.design.slots[slot] = cls
            specs = cls.param_specs()
            given = dict(part_params)
            given_orig = {k: part_origin.get(k) for k in part_params}
            for k, v in (spec.get("params") or {}).items():
                given[k] = v
                given_orig[k] = t.origin("parts", slot, "params", k)
            for k in given:
                if k not in specs:
                    raise ResolveError(f"part type {type_id} has no parameter {k!r} "
                                       f"(has: {', '.join(specs)})", path=f"parts.{slot}.params.{k}",
                                       file=given_orig[k])
            for name, ps in specs.items():
                if name in given:
                    n[f"parts.{slot}.{name}"] = {"raw": given[name], "origin": given_orig[name], "spec": ps}
                else:
                    n[f"parts.{slot}.{name}"] = {"raw": ps.default, "origin": f"{type_id} (default)",
                                                 "spec": ps, "default": True}
            n[f"parts.{slot}.at"] = {"raw": spec.get("at", 0), "origin": t.origin("parts", slot, "at"),
                                     "dim": DIMS["length"]}
        for p, raw in flatten(t.get("op") or {}).items():
            n[f"op.{p}"] = {"raw": raw, "origin": t.origin("op", *p.split(".")), "dim": op_dim(p),
                            "infer": op_dim(p) is None}
        for stage, specs in self.fid.stages.items():
            raw = self.fid.raw.get(stage, {})
            for k in raw:
                if k not in specs:
                    raise ResolveError(f"unknown fidelity setting {k!r} for stage {stage} "
                                       f"(known: {', '.join(specs)})", path=f"fidelity.{stage}.{k}")
            for k, ps in specs.items():
                if k in raw:
                    n[f"fidelity.{stage}.{k}"] = {"raw": raw[k], "origin": self.fid.origins.get(f"{stage}.{k}", "pipeline"),
                                                  "spec": ps}
                else:
                    n[f"fidelity.{stage}.{k}"] = {"raw": ps.default, "origin": "backend default", "spec": ps,
                                                  "default": True}
        for name, (raw, d, origin) in self.row.variables.items():
            n[name] = {"raw": raw, "origin": origin, "dim": d, "variable": True}
        writers: dict[str, str] = {}
        for path, (raw, origin) in self.row.assignments.items():
            if path in writers:
                raise ResolveError(f"{path} is written by both {writers[path]} and {origin}")
            writers[path] = origin
            if path not in n:
                raise ResolveError(f"{origin} targets {path}, which does not exist in this design")
            node = n[path]
            if node.get("spec") is not None and node["spec"].kind == "slot":
                pass
            node.update(raw=raw, origin=origin)
            node.pop("default", None)

    def _slot_type(self, slot: str, spec: dict) -> tuple[str, dict, dict]:
        if "use" in spec:
            pid = spec["use"]
            doc = self.project.doc(pid, "parts")
            data = doc.data or {}
            for k in data:
                if k not in ("type", "description", "params"):
                    raise doc.error(f"unknown key {k!r} in a part", k)
            if "type" not in data:
                raise doc.error("a part needs 'type'")
            params = data.get("params") or {}
            return data["type"], params, {k: str(doc.loc("params", k)) for k in params}
        if "type" in spec:
            return spec["type"], {}, {}
        raise ResolveError(f"slot {slot!r} needs 'use' or 'type'", file=self.tree.origin("parts", slot))

    # ---- evaluation ----------------------------------------------------------------------------
    def value(self, path: str):
        d = self.design
        if path in d.values:
            return d.values[path]
        if path not in self.nodes:
            return self._dynamic(path)
        if path in self._busy:
            cycle = self._busy[self._busy.index(path):] + [path]
            raise ResolveError("dependency cycle: " + " -> ".join(cycle))
        self._busy.append(path)
        try:
            node = self.nodes[path]
            v, dim = self._compute(path, node)
        finally:
            self._busy.pop()
        d.values[path] = v
        d.dims[path] = dim
        d.origins[path] = node["origin"] if not is_expr(node["raw"]) or node["origin"] not in ("", None) \
            else node["origin"]
        if is_expr(node["raw"]):
            d.origins[path] = f"{node['origin']}  [{node['raw']}]"
        return v

    def _dynamic(self, path: str):
        parts = path.split(".")
        if parts[0] == "parts" and len(parts) >= 2:
            slot = parts[1]
            if slot not in self.design.slots:
                if slot in (self.tree.get("parts") or {}):
                    return None
                raise ResolveError(f"no slot {slot!r} (slots: {', '.join(self.tree.get('parts') or {})})")
            if len(parts) == 2:
                return SlotPresent(slot)
            name = ".".join(parts[2:])
            key = f"parts.{slot}"
            if key in self._derived_busy:
                raise ResolveError(f"derived values of {slot} depend on themselves")
            self._derived_busy.add(key)
            try:
                derived = self.design.part(slot).derived
            finally:
                self._derived_busy.discard(key)
            if name in derived:
                return derived[name]
            raise ResolveError(f"part {slot} has no parameter or derived value {name!r}")
        raise ResolveError(f"unknown name {path!r}")

    def _lookup_q(self, path: str):
        """Expression lookup: quantities as pint Quantities."""
        v = self.value(path)
        d = self.design.dims.get(path)
        if d is None and path.startswith("parts.") and path.count(".") >= 2 and path not in self.nodes:
            slot, name = path.split(".")[1], ".".join(path.split(".")[2:])
            d = derived_dims(self.design.slots.get(slot)).get(name) if slot in self.design.slots else None
            if d is None and isinstance(v, float):
                raise ExpressionError(f"{path} is a derived value without a declared dimension; declare it in "
                                      f"the part type's 'Derived' class")
        if isinstance(v, bool) or v is None or isinstance(v, (str, SlotPresent, Material)):
            return v
        if isinstance(v, (int, float)) and d is not None and d.si:
            return Q_(v, d.si)
        return v

    def evaluate_raw(self, raw: Any, target: Dim | None, where: str = ""):
        if is_expr(raw):
            val = Expr(raw, where).evaluate(self._lookup_q)
            return coerce(val, target, self.units, where)
        if target is None:
            if isinstance(raw, str):
                try:
                    q = self.units.parse(raw)
                except ValueError:
                    return raw, None
                d = dim_of(q)
                return (self.units.quantity_to_si(q, d) if d.si else float(q.to("").magnitude)), d
            return raw, None
        try:
            return self.units.to_si(raw, target), target
        except ValueError as e:
            raise ResolveError(str(e), path=where) from None

    def _compute(self, path: str, node: dict):
        raw = node["raw"]
        spec: ParamSpec | None = node.get("spec")
        origin = node["origin"]
        where = path
        try:
            if spec is None:
                d = node.get("dim")
                if node.get("variable") and not is_expr(raw):
                    if isinstance(raw, str) and ":" in raw:
                        return raw, None
                    if d is None:
                        return raw, None
                    return self.units.to_si(raw, d), d
                v, dim = self.evaluate_raw(raw, d, where)
                if isinstance(v, float):
                    v = quantize(v)
                return v, dim
            return self._compute_param(path, raw, spec, node)
        except (ExpressionError, ResolveError) as e:
            if not e.file:
                e.file = origin
                e.path = e.path or path
                e.args = (e.format(),)
            raise
        except ValueError as e:
            raise ResolveError(str(e), file=origin, path=path) from None

    def _compute_param(self, path: str, raw: Any, spec: ParamSpec, node: dict):
        if raw is REQUIRED:
            slot = path.split(".")[1] if path.startswith("parts.") else ""
            raise ResolveError(f"required parameter has no value" + (f" (set it in the slot {slot!r})" if slot else ""),
                               path=path)
        if raw is None:
            if not spec.optional:
                raise ResolveError("this parameter cannot be empty", path=path)
            return None, None
        if is_expr(raw):
            val = Expr(raw, path).evaluate(self._lookup_q)
            if spec.kind == "quantity":
                v, d = coerce(val, spec.dim, self.units, path)
                v = quantize(v)
                self._bounds(path, v, spec)
                return v, d
            if spec.kind == "int":
                if hasattr(val, "magnitude"):
                    val = val.to("").magnitude
                if abs(val - round(val)) > 1e-9:
                    raise ResolveError(f"expected an integer, expression gives {val}", path=path)
                v = int(round(val))
                self._bounds(path, v, spec)
                return v, None
            raw = val
        k = spec.kind
        if k == "quantity":
            if node.get("default") and isinstance(raw, (int, float)) and not isinstance(raw, bool):
                v = float(raw)                       # part-type defaults are already SI
            elif isinstance(raw, str) and spec.alt_str:
                try:
                    v = self.units.to_si(raw, spec.dim)
                except ValueError:
                    return raw, None
            else:
                v = self.units.to_si(raw, spec.dim)
            v = quantize(v)
            self._bounds(path, v, spec)
            return v, spec.dim
        if k == "int":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or float(raw) != int(raw):
                raise ResolveError(f"expected an integer, got {raw!r}", path=path)
            v = int(raw)
            self._bounds(path, v, spec)
            return v, None
        if k == "bool":
            if not isinstance(raw, bool):
                raise ResolveError(f"expected true/false, got {raw!r}", path=path)
            return raw, None
        if k == "str":
            v = str(raw)
            if spec.choices is not None and v not in spec.choices:
                raise ResolveError(f"{v!r} is not one of {spec.choices}", path=path)
            return v, None
        if k == "material":
            mat = raw if isinstance(raw, Material) else self.project.material(str(raw))
            missing = [n for n in spec.needs if not mat.has(n)]
            if missing:
                raise ResolveError(f"material {mat.id} has no {', '.join(missing)}, needed by {path}", path=path)
            return mat, None
        if k == "slot":
            target = str(raw)
            if target not in self.design.slots:
                raise ResolveError(f"refers to slot {target!r}, which is empty or does not exist", path=path)
            if spec.slot_type:
                want = self.project.part_type(spec.slot_type)
                if not issubclass(self.design.slots[target], want):
                    raise ResolveError(f"slot {target!r} holds {self.design.slots[target]._entry_id}, but a "
                                       f"{spec.slot_type} is required", path=path)
            return target, None
        return raw, None

    def _bounds(self, path, v, spec: ParamSpec):
        if spec.min is not None and v < spec.min - 1e-15:
            raise ResolveError(f"{self._show(v, spec)} is below the minimum {self._show(spec.min, spec)}", path=path)
        if spec.max is not None and v > spec.max + 1e-15:
            raise ResolveError(f"{self._show(v, spec)} is above the maximum {self._show(spec.max, spec)}", path=path)
        if spec.choices is not None and v not in spec.choices:
            raise ResolveError(f"{v!r} is not one of {spec.choices}", path=path)

    def _show(self, v, spec):
        return self.units.show(v, spec.dim) if spec.kind == "quantity" else str(v)

    # ---- driver ----------------------------------------------------------------------------------
    def resolve(self) -> ResolvedDesign:
        errors = []
        for path in list(self.nodes):
            try:
                self.value(path)
            except (ResolveError, ExpressionError) as e:
                errors.append(e)
        seen, unique = set(), []
        for e in errors:
            if str(e) not in seen:
                seen.add(str(e))
                unique.append(e)
        errors = unique
        if errors:
            if len(errors) == 1:
                raise errors[0]
            from .errors import ErrorList
            raise ErrorList(errors)
        self.design.checks_spec = self.tree.get("checks") or {}
        self.design.declared_slots = set(self.tree.get("parts") or {})
        for slot in self.design.slots:              # derived values are part of the design
            for k, v in self.design.part(slot).derived.items():
                key = f"parts.{slot}.{k}"
                if key not in self.design.values:
                    self.design.values[key] = v
                    self.design.dims[key] = derived_dims(self.design.slots[slot]).get(k)
                    self.design.origins[key] = "derived"
        return self.design


def derived_dims(cls: type | None) -> dict[str, Dim | None]:
    if cls is None:
        return {}
    cache = cls.__dict__.get("_derived_dims")
    if cache is not None:
        return cache
    out: dict[str, Dim | None] = {}
    for klass in reversed(cls.__mro__):
        dcls = vars(klass).get("Derived")
        if dcls is None:
            continue
        try:
            hints = typing.get_type_hints(dcls, include_extras=True)
        except Exception:  # noqa: BLE001
            hints = getattr(dcls, "__annotations__", {})
        for k, ann in hints.items():
            kind, d, _, _ = _analyze(ann)
            out[k] = d if kind == "quantity" else None
    cls._derived_dims = out
    return out


# =================================================================================================
# Function parameters (probes, metrics, references, checks): coerce YAML values by annotation.
def function_params(fn: Callable, skip: set[str]) -> dict[str, ParamSpec]:
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True,
                                      localns={"Slot": Slot, "Material": Material})
    except Exception:  # noqa: BLE001
        hints = {}
    out = {}
    for name, p in sig.parameters.items():
        if name in skip or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        out[name] = _spec_for(name, hints.get(name, p.annotation if p.annotation is not p.empty else Any),
                              p.default)
    return out


def _spec_for(name, ann, default):
    from .parts import spec_from
    s = spec_from(name, ann, default)
    s._ann = ann
    return s


def coerce_function_param(design: ResolvedDesign, spec: ParamSpec, raw: Any, where: str):
    """Resolve one probe/metric/reference parameter value given in YAML (or its default)."""
    if raw is REQUIRED:
        raise ResolveError("required parameter not given", path=where)
    if isinstance(raw, Slot):
        raw = raw.default
    ann = getattr(spec, "_ann", Any)
    return _coerce_by_ann(design, ann, spec, raw, where)


def _coerce_by_ann(design, ann, spec, raw, where):
    units = design.project.units
    if is_expr(raw):
        res = design._resolver
        if res is None:
            raise ResolveError("expressions in parameters need the row context", path=where)
        val = Expr(raw, where).evaluate(res._lookup_q)
        target = spec.dim if spec and spec.kind == "quantity" else None
        v, _ = coerce(val, target, units, where)
        return v
    origin = typing.get_origin(ann)
    if origin in (list, tuple) and isinstance(raw, (list, tuple)):
        args = typing.get_args(ann)
        if origin is tuple and args and args[-1] is not Ellipsis:
            return [_coerce_by_ann(design, a, None, x, where) for a, x in zip(args, raw)]
        inner = args[0] if args else Any
        return [_coerce_by_ann(design, inner, None, x, where) for x in raw]
    if spec is None:
        from .parts import spec_from
        spec = spec_from("_", ann, inspect.Parameter.empty)
    if raw is None:
        return None
    k = spec.kind
    if k == "quantity":
        if isinstance(raw, str) and spec.alt_str:
            try:
                return units.to_si(raw, spec.dim)
            except ValueError:
                return raw
        if isinstance(raw, float) and spec.default is raw:
            return raw
        return units.to_si(raw, spec.dim)
    if k == "slot":
        target = str(raw)
        if target not in design.slots:
            if target in getattr(design, "declared_slots", set()):
                return target                      # an empty optional slot: callers skip it
            raise ResolveError(f"refers to slot {target!r}, which does not exist", path=where)
        if spec.slot_type:
            want = design.project.part_type(spec.slot_type)
            if not issubclass(design.slots[target], want):
                raise ResolveError(f"slot {target!r} is not a {spec.slot_type}", path=where)
        return target
    if k == "material":
        return design.project.material(str(raw))
    if k == "int":
        return int(raw)
    return raw
