"""Units.

Inside bplsim every value is an SI float. Units appear only at the edges:

* YAML strings such as ``"18 mm"`` or ``"20 degC"`` are parsed with pint;
* bare YAML numbers are read in the project's display unit for the target's dimension;
* Python library entries use the float multipliers below (``17.6 * mm`` is 0.0176) and declare
  dimensions with annotations (``Length``, ``Angle``, ...).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Any

import re

import pint

# pint's "gauss" is the CGS-Gaussian unit, which does not convert to tesla. bplsim's G is the SI
# gauss (1e-4 T); the preprocessor maps "G" and "gauss" to it.
_GAUSS = re.compile(r"(?<![A-Za-z_])(G|gauss)(?![A-Za-z_])")
ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True,
                         preprocessors=[lambda text: _GAUSS.sub("Gs", text)])
ureg.define("Gs = 1e-4 * tesla")
Q_ = ureg.Quantity

# --- SI float multipliers for Python entries -------------------------------------------------------
m = 1.0
cm = 1e-2
mm = 1e-3
um = 1e-6
inch = 0.0254
rad = 1.0
deg = math.pi / 180
A = 1.0
mA = 1e-3
T = 1.0
mT = 1e-3
G = 1e-4
W = 1.0
V = 1.0
ohm = 1.0
s = 1.0
minute = 60.0
hour = 3600.0
kg = 1.0
K = 1.0
GB = 1024.0 ** 3


def celsius(value: float) -> float:
    """Temperature in degrees Celsius -> kelvin (temperatures are offsets, not multipliers)."""
    return value + 273.15


# --- dimensions ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Dim:
    """A named physical dimension with its SI unit and a default display unit."""
    name: str
    si: str
    display: str

    def __repr__(self) -> str:
        return f"Dim({self.name})"


DIMS: dict[str, Dim] = {d.name: d for d in [
    Dim("dimensionless", "", ""),
    Dim("length", "m", "mm"),
    Dim("area", "m**2", "mm**2"),
    Dim("volume", "m**3", "mm**3"),
    Dim("angle", "rad", "deg"),
    Dim("current", "A", "A"),
    Dim("temperature", "K", "degC"),
    Dim("magnetic_flux_density", "T", "G"),
    Dim("magnetic_field_strength", "A/m", "A/m"),
    Dim("power", "W", "W"),
    Dim("voltage", "V", "V"),
    Dim("resistance", "ohm", "ohm"),
    Dim("resistivity", "ohm*m", "ohm*m"),
    Dim("time", "s", "s"),
    Dim("mass", "kg", "kg"),
    Dim("density", "kg/m**3", "kg/m**3"),
    Dim("frequency", "Hz", "Hz"),
    Dim("mass_flow", "kg/s", "mg/s"),
    Dim("memory", "byte", "GB"),
]}

# Annotated aliases used in Params classes and probe/metric signatures.
Length = Annotated[float, DIMS["length"]]
Area = Annotated[float, DIMS["area"]]
Angle = Annotated[float, DIMS["angle"]]
Current = Annotated[float, DIMS["current"]]
Temperature = Annotated[float, DIMS["temperature"]]
FluxDensity = Annotated[float, DIMS["magnetic_flux_density"]]
Power = Annotated[float, DIMS["power"]]
Voltage = Annotated[float, DIMS["voltage"]]
Time = Annotated[float, DIMS["time"]]
Mass = Annotated[float, DIMS["mass"]]
Dimensionless = Annotated[float, DIMS["dimensionless"]]


def dim(name: str) -> Dim:
    return DIMS[name]


def _dimensionality(unit: str):
    return Q_(1, unit).dimensionality if unit else Q_(1).dimensionality


def dim_of(q: pint.Quantity) -> Dim:
    """The registered Dim matching a quantity, or an ad-hoc one named after its dimensionality."""
    d = q.dimensionality
    for cand in DIMS.values():
        if cand.name in ("angle",):
            continue
        if _dimensionality(cand.si) == d:
            return cand
    base = q.to_base_units()
    return Dim(str(d), f"{base.units:~}" if str(base.units) != "dimensionless" else "", f"{base.units:~}")


class UnitSystem:
    """Display units of a project: how bare numbers are read and values are shown."""

    def __init__(self, display: dict[str, str] | None = None):
        self.display = {n: d.display for n, d in DIMS.items()}
        for name, unit in (display or {}).items():
            if name not in DIMS:
                raise ValueError(f"unknown dimension {name!r} in display units (known: {', '.join(DIMS)})")
            Q_(1, unit).to(DIMS[name].si) if DIMS[name].si else None
            self.display[name] = unit

    # parsing ---------------------------------------------------------------
    def parse(self, raw: Any) -> pint.Quantity:
        """A YAML scalar with explicit units ('18 mm', '20 degC') -> pint Quantity."""
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return Q_(float(raw))
        text = str(raw).strip()
        parts = text.split(None, 1)
        try:
            if len(parts) == 2:
                num = float(parts[0])
                return Q_(num, parts[1])            # Q_(value, unit) handles offset units (degC)
            return Q_(text)
        except (ValueError, pint.errors.PintError) as e:
            raise ValueError(f"cannot parse {raw!r} as a quantity: {e}") from None

    def to_si(self, raw: Any, target: Dim) -> float:
        """Convert a YAML value for a target dimension to an SI float.

        Bare numbers are read in the display unit of the target dimension; strings must carry
        units compatible with it (or none, for dimensionless targets)."""
        if isinstance(raw, bool):
            raise ValueError(f"expected a {target.name} value, got a boolean")
        if isinstance(raw, (int, float)):
            unit = self.display.get(target.name, target.si)
            if not unit:
                return float(raw)
            return float(Q_(float(raw), unit).to(target.si).magnitude)
        q = self.parse(raw)
        return self.quantity_to_si(q, target)

    def quantity_to_si(self, q: pint.Quantity, target: Dim) -> float:
        if not target.si:
            if not q.dimensionless:
                raise ValueError(f"expected a dimensionless value, got {q:~}")
            return float(q.to("").magnitude)
        try:
            return float(q.to(target.si).magnitude)
        except pint.errors.DimensionalityError:
            raise ValueError(f"expected a {target.name} value (e.g. {target.display}), got {q:~}") from None

    def quantity(self, value_si: float, d: Dim) -> pint.Quantity:
        return Q_(value_si, d.si) if d.si else Q_(value_si)

    # display ---------------------------------------------------------------
    def show(self, value_si: float, d: Dim | None, digits: int = 6) -> str:
        if d is None or not d.si:
            return f"{value_si:.{digits}g}"
        unit = self.display.get(d.name, d.display)
        v = Q_(value_si, d.si).to(unit).magnitude
        return f"{v:.{digits}g} {unit}"

    def from_si(self, value_si: float, d: Dim) -> float:
        if not d.si:
            return value_si
        return float(Q_(value_si, d.si).to(self.display.get(d.name, d.display)).magnitude)


DEFAULT_UNITS = UnitSystem()
