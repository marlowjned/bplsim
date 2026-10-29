"""getdp_3d against getdp_axisym on the same design (plan §17 phase 6): the angle-averaged channel profile of
a coarse linear 3-D solve agrees with the 2-D model, and 3-D shows the azimuthal ripple 2-D cannot.
Needs GetDP (BPLSIM_TOOL_GETDP or ../HET/tools); a few minutes."""
import os
from pathlib import Path

import pytest

from conftest import HET

GETDP = Path(__file__).resolve().parents[2] / "HET" / "tools" / "getdp-3.5.0-Windows64" / "getdp.exe"


@pytest.mark.slow
def test_3d_matches_2d_on_angle_averaged_profile(tmp_path):
    if not os.environ.get("BPLSIM_TOOL_GETDP") and GETDP.exists():
        os.environ["BPLSIM_TOOL_GETDP"] = str(GETDP)
    from bplsim.measure.engine import (compute_metrics, define_measurements, evaluate_probe, load_measurement_set,
                                       normalize)
    from bplsim.pipeline import load_pipeline
    from bplsim.project import Project
    from bplsim.resolve import Resolver
    pr = Project.load(HET)
    out = {}
    for pid in ("het:pipelines/magnetostatics_2d", "het:pipelines/magnetostatics_3d_coarse"):
        pl = load_pipeline(pr, pid)
        d = Resolver(pr, "het:assemblies/bn_screened", fidelity=pl.fidelity_spec()).resolve()
        st = pl.stages["mag"]
        cfg = st.config(d)
        inputs = st.backend.solve_inputs(d, cfg)
        bases = st.backend.bases(d, cfg, inputs)
        w = tmp_path / pid.split("/")[-1]
        w.mkdir()
        st.backend.prepare(inputs, w)
        for b in bases:
            assert st.backend.execute(inputs, w, b, {}).status == "ok"
        ms = load_measurement_set(pr, "het:measurements/channel_field_3d")
        pdefs, mdefs = define_measurements(pr, d, ms)
        case = {p.def_hash: {b.name: evaluate_probe(pr, d, p, st.backend.field_access(inputs, w, b)) for b in bases}
                for p in pdefs.values()}
        bd = [b.canonical() for b in bases]
        nz = normalize(pr, d, mdefs, case, bd, {"value": "shape.peak_Br", "target_si": 0.0165,
                                                "scale": ["op.circuits.inner.current", "op.circuits.outer.current"]}, True)
        out[pid] = (nz, compute_metrics(pr, d, mdefs, case, bd))
    (n2, m2), (n3, m3) = out.values()
    assert n3["op.circuits.inner.current"] == pytest.approx(n2["op.circuits.inner.current"], rel=0.03)
    assert m3["shape"]["sigma"] == pytest.approx(m2["shape"]["sigma"], abs=0.5e-3)
    assert m3["shape"]["exit_Br_pct"] == pytest.approx(m2["shape"]["exit_Br_pct"], abs=3.0)
    assert m2["ripple_exit"]["ripple_pct"] == 0.0 and m3["ripple_exit"]["ripple_pct"] > 1.0
