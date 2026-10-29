"""Part types: the Python side of the design model (example §5).

A part type declares its parameters in an inner ``Params`` class (annotations + ``Param()``), and may
define ``checks``, ``derived``, ``profile_rz`` (exact axisymmetric geometry), ``solid_3d`` and named
equivalence rules for 2-D backends.
"""
from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .units import DIMS, Angle, Area, Current, Dim, Dimensionless, FluxDensity, Length, Mass, Power, \
    Temperature, Time, Voltage  # noqa: F401  (re-exported for library authors)

REQUIRED = object()


class Slot:
    """A reference to another slot of the assembly. As a default value: ``Slot("channel", type=...)``."""

    def __init__(self, default: str | None = None, type: str | None = None):  # noqa: A002
        self.default = default
        self.type = type

    def __repr__(self) -> str:
        return f"Slot({self.default!r}, type={self.type!r})"


class Param:
    """Declares one parameter: default (SI), bounds (SI), material needs, slot type, choices."""

    def __init__(self, default: Any = REQUIRED, *, min: float | None = None, max: float | None = None,  # noqa: A002
                 needs: Iterable[str] | None = None, type: str | None = None,  # noqa: A002
                 choices: Iterable[Any] | None = None, dim: Dim | str | None = None, doc: str = ""):
        self.default = default
        self.min, self.max = min, max
        self.needs = list(needs or [])
        self.slot_type = type
        self.choices = list(choices) if choices is not None else None
        self.dim = DIMS[dim] if isinstance(dim, str) else dim
        self.doc = doc


@dataclass
class ParamSpec:
    name: str
    kind: str                     # quantity | int | float | str | bool | material | slot | any
    dim: Dim | None = None
    optional: bool = False
    alt_str: bool = False         # a quantity that may also be a plain string ("average")
    default: Any = REQUIRED
    min: float | None = None
    max: float | None = None
    needs: list = field(default_factory=list)
    slot_type: str | None = None
    choices: list | None = None
    doc: str = ""

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


def _analyze(ann: Any) -> tuple[str, Dim | None, bool, bool]:
    """(kind, dim, optional, alt_str) from a type annotation."""
    optional = alt_str = False
    origin = typing.get_origin(ann)
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        args = [a for a in typing.get_args(ann)]
        if type(None) in args:
            optional = True
            args = [a for a in args if a is not type(None)]
        if str in args and len(args) > 1:
            alt_str = True
            args = [a for a in args if a is not str]
        ann = args[0] if len(args) == 1 else Any
        origin = typing.get_origin(ann)
    if origin is typing.Annotated:
        base, *meta = typing.get_args(ann)
        d = next((m for m in meta if isinstance(m, Dim)), None)
        if d is not None:
            return "quantity", d, optional, alt_str
        ann = base
    if ann is bool:
        return "bool", None, optional, alt_str
    if ann is int:
        return "int", None, optional, alt_str
    if ann is float:
        return "quantity", DIMS["dimensionless"], optional, alt_str
    if ann is str:
        return "str", None, optional, alt_str
    if isinstance(ann, type) and ann.__name__ == "Material":
        return "material", None, optional, alt_str
    if ann is Slot or (isinstance(ann, type) and issubclass(ann, Slot)):
        return "slot", None, optional, alt_str
    return "any", None, optional, alt_str


def spec_from(name: str, ann: Any, default: Any) -> ParamSpec:
    kind, d, optional, alt_str = _analyze(ann)
    s = ParamSpec(name, kind, d, optional, alt_str)
    if isinstance(default, Param):
        s.default, s.min, s.max, s.needs = default.default, default.min, default.max, default.needs
        s.slot_type, s.choices, s.doc = default.slot_type, default.choices, default.doc
        if default.dim is not None:
            s.kind, s.dim = "quantity", default.dim
    elif isinstance(default, Slot):
        s.kind = "slot"
        s.default = default.default if default.default is not None else REQUIRED
        s.slot_type = default.type
    elif default is not inspect.Parameter.empty:
        s.default = default
    if s.default is None:
        s.optional = True
    return s


def params_of(params_cls: type) -> dict[str, ParamSpec]:
    """ParamSpecs of a Params class, including inherited ones."""
    hints = {}
    for klass in reversed(params_cls.__mro__):
        if klass is object:
            continue
        try:
            hints.update(typing.get_type_hints(klass, include_extras=True,
                                               localns={"Material": _material_cls(), "Slot": Slot}))
        except NameError:
            hints.update(getattr(klass, "__annotations__", {}))
    out = {}
    for name, ann in hints.items():
        if name.startswith("_"):
            continue
        out[name] = spec_from(name, ann, getattr(params_cls, name, inspect.Parameter.empty))
    return out


def _material_cls():
    from .materials import Material as M
    return M


# ------------------------------------------------------------------------------------------------
@dataclass
class Margin:
    name: str
    value: float
    min: float = 0.0
    detail: str = ""

    @property
    def slack(self) -> float:
        return self.value - self.min

    @property
    def ok(self) -> bool:
        return self.slack >= -1e-12


def margin(name: str, value: float, min: float = 0.0, detail: str = "") -> Margin:  # noqa: A002
    return Margin(name, float(value), float(min), detail)


def equivalence(name: str, valid_for: str = "any", default: bool = False) -> Callable:
    """Mark a PartType method as a named 2-D equivalence rule (valid_for: 'any' | 'linear')."""
    def deco(fn):
        fn._bplsim_equivalence = {"name": name, "valid_for": valid_for, "default": default}
        return fn
    return deco


class PartType:
    """Base class of every part type."""
    version: str = "0.0.0"
    doc: str = ""
    frame: str = ""
    _entry_id: str = ""

    class Params:
        pass

    @classmethod
    def param_specs(cls) -> dict[str, ParamSpec]:
        cache = cls.__dict__.get("_spec_cache")
        if cache is None:
            cache = params_of(cls.Params)
            cls._spec_cache = cache
        return cache

    @classmethod
    def is_axisymmetric(cls) -> bool:
        return cls.profile_rz is not None

    @classmethod
    def equivalences(cls) -> dict[str, Callable]:
        out = {}
        for klass in reversed(cls.__mro__):
            for v in vars(klass).values():
                info = getattr(v, "_bplsim_equivalence", None)
                if info:
                    out[info["name"]] = v
        return out

    profile_rz = None   # override with def profile_rz(self, p) for exact axisymmetric geometry
    solid_3d = None     # override with def solid_3d(self, p)

    def axisymmetric(self, p) -> bool:
        """True if profile_rz is exact for these parameters (override when it depends on them)."""
        return type(self).profile_rz is not None

    def checks(self, p) -> Iterable[Margin]:
        return []

    def derived(self, p) -> dict[str, Any]:
        return {}


__all__ = ["PartType", "Param", "Slot", "Material", "margin", "Margin", "equivalence", "Length", "Area",
           "Angle", "Current", "Temperature", "FluxDensity", "Power", "Voltage", "Time", "Mass",
           "Dimensionless", "REQUIRED"]


def __getattr__(name):  # makes `from bplsim.parts import Material` give the real Material class
    if name == "Material":
        return _material_cls()
    raise AttributeError(name)
