import pytest

from bplsim.errors import ExpressionError
from bplsim.expr import Expr, SlotPresent, coerce
from bplsim.units import DIMS, Q_, UnitSystem


U = UnitSystem({"magnetic_flux_density": "G"})


def test_bare_numbers_use_display_unit_of_target():
    assert U.to_si(18, DIMS["length"]) == pytest.approx(0.018)
    assert U.to_si(165, DIMS["magnetic_flux_density"]) == pytest.approx(0.0165)
    assert U.to_si(80, DIMS["temperature"]) == pytest.approx(353.15)
    assert U.to_si(4, DIMS["dimensionless"]) == 4


def test_unit_strings_and_mismatch():
    assert U.to_si("18 mm", DIMS["length"]) == pytest.approx(0.018)
    assert U.to_si("20 degC", DIMS["temperature"]) == pytest.approx(293.15)
    with pytest.raises(ValueError):
        U.to_si("3 A", DIMS["length"])


def _look(values):
    return lambda p: values[p]


def test_zero_rule_and_literal_rule():
    vals = {"a": Q_(0.01, "m"), "cap": None}
    assert Expr("${ a + 0 }").evaluate(_look(vals)).to("m").magnitude == pytest.approx(0.01)
    with pytest.raises(ExpressionError, match="only 0"):
        Expr("${ a + 1 }").evaluate(_look(vals))


def test_null_guard():
    vals = {"parts.cap": None, "parts.cap.t": Q_(1, "mm")}
    assert Expr("${ -parts.cap.t if parts.cap else 0 }").evaluate(_look(vals)) == 0
    with pytest.raises(ExpressionError, match="empty optional slot"):
        Expr("${ -parts.cap2.t }").evaluate(_look({"parts.cap2.t": None}))


def test_whitelist():
    for bad in ["${ __import__('os') }", "${ open('x') }", "${ [x for x in y] }", "${ a[0] }", "${ lambda: 1 }"]:
        with pytest.raises(ExpressionError):
            Expr(bad)


def test_coerce_dimension_check():
    v, d = coerce(Q_(2, "mm"), DIMS["length"], U)
    assert v == pytest.approx(0.002)
    with pytest.raises(ExpressionError):
        coerce(Q_(2, "A"), DIMS["length"], U, "x")
    assert coerce(0, DIMS["length"], U)[0] == 0


def test_gauss_is_si():
    assert Q_(165, "G").to("T").magnitude == pytest.approx(0.0165)
