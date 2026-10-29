from bplsim.metrics import metric

from het.part_types._winding import Winding


@metric(version="1.0.0", inputs={}, outputs={"total": "W"})
def coil_power(design, op):
    """The one power formula: I^2 R per coil, R from turns, mean turn length, wire area, temperature."""
    total = 0.0
    for coil in design.parts_of(Winding):
        current = op.circuits[coil.circuit].current
        total += coil.coil_count * current ** 2 * coil.resistance(op.temperature)
    return {"total": total}
