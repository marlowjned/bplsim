"""Materials: open-ended sets of named properties with units (example §4).

A property is one of:
* a scalar (SI float; ``PropFloat`` so ``.at(T)`` also works);
* a linearly temperature-dependent scalar ``{value, at, temp_coeff}`` (``.at(T)`` applies it);
* a table ``{table: file.csv, columns: {name: unit, ...}}``;
* a plain string.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from bplsim.core.errors import ConfigError
from bplsim.core.hashing import quantize
from bplsim.units import DIMS, UnitSystem, dim_of


class PropFloat(float):
    """A scalar property. ``.at(T)`` returns the value at temperature T (kelvin)."""

    def __new__(cls, value: float, unit: str = "", ref_T: float | None = None, coeff: float | None = None):
        obj = super().__new__(cls, value)
        obj.unit, obj.ref_T, obj.coeff = unit, ref_T, coeff
        return obj

    def at(self, T: float) -> float:
        if self.coeff is None or self.ref_T is None:
            return float(self)
        return float(self) * (1 + self.coeff * (T - self.ref_T))

    def canonical(self):
        return {"value": quantize(float(self)), "unit": self.unit, "ref_T": self.ref_T, "coeff": self.coeff}


class Table:
    """Tabulated property; columns in SI."""

    def __init__(self, columns: dict[str, np.ndarray], units: dict[str, str], source: str):
        self.columns, self.units, self.source = columns, units, source

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]

    @property
    def names(self) -> list[str]:
        return list(self.columns)

    def interp(self, x_name: str, y_name: str, x):
        return np.interp(x, self.columns[x_name], self.columns[y_name])

    def canonical(self):
        h = hashlib.sha256()
        for k in sorted(self.columns):
            h.update(k.encode())
            h.update(np.ascontiguousarray(self.columns[k], dtype=float).tobytes())
        return {"table": h.hexdigest(), "units": self.units}


class Material:
    def __init__(self, id: str, props: dict[str, Any], description: str = "", vocabulary=None):  # noqa: A002
        self.id = id
        self.props = props
        self.description = description
        self._vocab = vocabulary

    def _canonical_name(self, name: str) -> str:
        return self._vocab.canonical(name) if self._vocab is not None else name

    def has(self, name: str) -> bool:
        return self._canonical_name(name) in self.props

    def get(self, name: str, default=None):
        return self.props.get(self._canonical_name(name), default)

    def __getattr__(self, name: str):
        if name.startswith("_") or name in ("id", "props", "description"):
            raise AttributeError(name)
        canon = self._canonical_name(name)
        if canon in self.props:
            return self.props[canon]
        raise AttributeError(f"material {self.id} has no property {name!r}"
                             + (f" (canonical name {canon!r})" if canon != name else "")
                             + f"; it has: {', '.join(sorted(self.props)) or 'nothing'}")

    def with_mu_r(self, mu_r: float) -> "Material":
        props = dict(self.props)
        props["mu_r_linear"] = PropFloat(float(mu_r))
        props.pop("bh_curve", None)        # an effective linear material has no B-H curve
        return Material(f"{self.id}[mu_r={quantize(mu_r, 9)}]", props, self.description, self._vocab)

    def canonical(self) -> dict:
        out = {}
        for k, v in sorted(self.props.items()):
            out[k] = v.canonical() if hasattr(v, "canonical") else v
        return {"id": self.id, "props": out}

    def __repr__(self) -> str:
        return f"Material({self.id})"


class Vocabulary:
    def __init__(self):
        self.alias_to: dict[str, str] = {}
        self.where: dict[str, str] = {}

    def add(self, mapping: dict[str, list[str]], source: str):
        for canon, aliases in (mapping or {}).items():
            for a in [canon] + list(aliases or []):
                if a in self.alias_to and self.alias_to[a] != canon:
                    raise ConfigError(f"vocabulary conflict: {a!r} means {self.alias_to[a]!r} in "
                                      f"{self.where[a]} but {canon!r} here", source)
                self.alias_to[a] = canon
                self.where[a] = source

    def canonical(self, name: str) -> str:
        return self.alias_to.get(name, name)


def _load_table(spec: dict, base: Path, units: UnitSystem, where: str) -> Table:
    path = base / spec["table"]
    cols = spec.get("columns") or {}
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline()
        header = any(c.isalpha() for c in first.replace("e", "").replace("E", ""))
        arr = np.loadtxt(path, delimiter=",", skiprows=1 if header else 0, ndmin=2)
    except OSError:
        raise ConfigError(f"table file not found: {path}", where) from None
    names = list(cols)
    if arr.shape[1] < len(names):
        raise ConfigError(f"{path} has {arr.shape[1]} columns, {len(names)} declared", where)
    out, unit_map = {}, {}
    for i, name in enumerate(names):
        unit = cols[name]
        q = units.parse(f"1 {unit}")
        d = dim_of(q)
        factor = units.quantity_to_si(q, d) if d.si else 1.0
        out[name] = arr[:, i] * factor
        unit_map[name] = d.si
    return Table(out, unit_map, str(path))


def parse_property(name: str, raw: Any, base: Path, units: UnitSystem, where: str):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return PropFloat(float(raw))
    if isinstance(raw, dict):
        if "table" in raw:
            return _load_table(raw, base, units, where)
        if "value" in raw:
            q = units.parse(raw["value"])
            d = dim_of(q)
            value = units.quantity_to_si(q, d) if d.si else float(q.magnitude)
            ref_T = units.to_si(raw["at"], DIMS["temperature"]) if "at" in raw else None
            coeff = None
            if "temp_coeff" in raw:
                cq = units.parse(raw["temp_coeff"])
                coeff = float(cq.to("1/K").magnitude)
            return PropFloat(value, d.si, ref_T, coeff)
        raise ConfigError(f"property {name!r}: a mapping needs 'table' or 'value'", where)
    if isinstance(raw, str):
        try:
            q = units.parse(raw)
        except ValueError:
            return raw
        d = dim_of(q)
        return PropFloat(units.quantity_to_si(q, d) if d.si else float(q.to("").magnitude), d.si)
    raise ConfigError(f"property {name!r}: unsupported value {raw!r}", where)
