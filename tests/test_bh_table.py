"""The reluctivity table handed to GetDP must keep H(B) monotone (open issue O1).

Interpolating nu = H/B at the B-H table points only made H(B) decrease between 0.65 and 0.80 T for the het a36
table: an unphysical, non-convex material law that stalled Newton in the 3-D nonlinear solve."""
from pathlib import Path

import numpy as np
import pytest
from scipy.interpolate import Akima1DInterpolator

from bplsim.backends.getdp_3d import nu_table
from bplsim.errors import BackendError

TABLE = Path(__file__).parent / "fixtures/het_example/library/materials/a36_bh.csv"


def _table():
    t = np.loadtxt(TABLE, delimiter=",", skiprows=1)
    return t[:, 0], t[:, 1]


def test_nu_table_is_monotone_under_akima_and_passes_through_the_table():
    H, B = _table()
    b2, nu = nu_table(H, B)
    a = Akima1DInterpolator(b2, nu)
    x = np.linspace(1e-3, B[-1], 20000)
    assert np.all(np.diff(a(x ** 2) * x) > 0)
    for h, b in zip(H[1:], B[1:]):
        assert abs(a(b ** 2) * b - h) / h < 2e-3


def test_nu_table_is_monotone_under_linear_interpolation():
    H, B = _table()
    b2, nu = nu_table(H, B, check="linear")
    x = np.linspace(1e-3, B[-1], 20000)
    assert np.all(np.diff(np.interp(x ** 2, b2, nu) * x) > 0)


def test_point_table_was_not_monotone():
    """Documents the cause of O1: nu at the table points only, Akima in B^2."""
    H, B = _table()
    nu = np.concatenate([[H[1] / B[1]], H[1:] / B[1:]])
    b2 = np.concatenate([[0.0], B[1:] ** 2])
    x = np.linspace(0.6, 0.85, 500)
    assert np.any(np.diff(Akima1DInterpolator(b2, nu)(x ** 2) * x) < 0)


def test_nu_table_rejects_a_decreasing_table():
    with pytest.raises(BackendError):
        nu_table([0.0, 100.0, 90.0], [0.0, 0.5, 1.0])
