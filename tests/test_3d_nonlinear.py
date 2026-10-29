"""Nonlinear 3-D magnetostatics on the coarse test design (open issue O1, fixed by the monotone reluctivity table):
every ramp step converges in a few Newton iterations, and the channel field matches the reference of the fix.
Needs GetDP (BPLSIM_TOOL_GETDP or ../HET/tools); about 8 min."""
import os
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import HET

GETDP = Path(__file__).resolve().parents[2] / "HET" / "tools" / "getdp-3.5.0-Windows64" / "getdp.exe"


@pytest.mark.slow
def test_nonlinear_3d_converges_and_matches_reference(tmp_path):
    if not os.environ.get("BPLSIM_TOOL_GETDP") and GETDP.exists():
        os.environ["BPLSIM_TOOL_GETDP"] = str(GETDP)
    from bplsim.pipeline import load_pipeline
    from bplsim.project import Project
    from bplsim.resolve import Resolver, RowSpec
    pr = Project.load(HET)
    pl = load_pipeline(pr, "het:pipelines/magnetostatics_3d_nl_coarse")
    rs = RowSpec(overrides={"op.circuits.inner.current": (2.0, "t"), "op.circuits.outer.current": (1.6, "t")})
    d = Resolver(pr, "het:assemblies/bn_screened", rs, fidelity=pl.fidelity_spec()).resolve()
    st = pl.stages["mag"]
    cfg = st.config(d)
    assert st.backend.check(d, cfg) == []
    inputs = st.backend.solve_inputs(d, cfg)
    basis = st.backend.bases(d, cfg, inputs)[0]
    st.backend.prepare(inputs, tmp_path)
    r = st.backend.execute(inputs, tmp_path, basis, {})
    assert r.status == "ok", r.reason
    log = (tmp_path / f"solve_{basis.name}.log").read_text()
    its = [int(n) for n in re.findall(r"IterativeLoop converged \((\d+) iterations", log)]
    # 4/4/4/3/3 with the monotone table (2026-10-29); the point table gave 5/32/61 (stalled)/52/12
    assert len(its) == 5 and max(its) <= 6, its
    ch = d.parts["channel"]
    rm = 0.5 * (float(ch.r_in) + float(ch.r_out))
    rm = rm * 1e-3 if rm > 1 else rm
    z = np.array([-0.005, 0.0])
    where = SimpleNamespace(r=np.full(2, rm), theta=np.zeros(2), z=z, shape=(2,), axes=("z",))
    b = st.backend.field_access(inputs, tmp_path, basis).sample(where).magnitude("B")
    assert b * 1e4 == pytest.approx([405.2, 364.8], rel=0.01)
