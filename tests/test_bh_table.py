"""The reluctivity table handed to GetDP must keep H(B) monotone (open issue O1).

Interpolating nu = H/B at the B-H table points only made H(B) decrease between 0.65 and 0.80 T for the het a36
table: an unphysical, non-convex material law that stalled Newton in the 3-D nonlinear solve."""
from pathlib import Path

import numpy as np
import pytest
from scipy.interpolate import Akima1DInterpolator

from bplsim.backends.getdp_3d import bh_issues, nu_table
from bplsim.core.errors import BackendError

from conftest import HET

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


def test_bh_issues_names_the_bad_material():
    H, B = _table()
    issues = bh_issues({"het:materials/a36": {"H": H, "B": B},
                        "het:materials/bad": {"H": [0.0, 100.0, 90.0], "B": [0.0, 0.5, 1.0]}})
    assert len(issues) == 1 and issues[0].startswith("material het:materials/bad")


def test_check_validates_bh_curves_before_meshing(monkeypatch):
    """getdp_3d.check() runs the B-H validation for nonlinear stages (the study driver marks the design
    invalid before any mesh is built); linear stages skip it."""
    import bplsim.backends.getdp_3d as g3
    from bplsim.model.pipeline import load_pipeline
    from bplsim.model.project import Project
    from bplsim.model.resolve import Resolver
    pr = Project.load(HET)
    pl = load_pipeline(pr, "het:pipelines/magnetostatics_3d_nl_coarse")
    d = Resolver(pr, "het:assemblies/bn_screened", fidelity=pl.fidelity_spec()).resolve()
    st = pl.stages["mag"]
    cfg = st.config(d)
    assert st.backend.check(d, cfg) == []

    def bad(H, B, n=160, check="akima"):
        raise BackendError("not monotone (test)")

    monkeypatch.setattr(g3, "nu_table", bad)
    issues = st.backend.check(d, cfg)
    assert issues and all("not monotone (test)" in i for i in issues)
    lin = load_pipeline(pr, "het:pipelines/magnetostatics_3d_coarse")
    d_lin = Resolver(pr, "het:assemblies/bn_screened", fidelity=lin.fidelity_spec()).resolve()
    assert lin.stages["mag"].backend.check(d_lin, lin.stages["mag"].config(d_lin)) == []
