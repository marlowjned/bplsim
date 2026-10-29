"""Stage chaining (plan §7.5): magnetostatics exports a field map (openPMD) at the run's normalized currents;
the PIC stage (a stand-in WarpX) reads it; metrics from both stages reach the study."""
import sys
from pathlib import Path

import numpy as np
import pytest

from conftest import HET, run_study


def test_mag_to_pic_chain(tmp_path, monkeypatch):
    from bplsim.analysis import Results
    from bplsim.measure.openpmd import read_field
    fake = Path(__file__).parent / "fake_warpx.py"
    monkeypatch.setenv("BPLSIM_TOOL_WARPX", f"{sys.executable} {fake}")
    d, s = run_study(HET, "mag_to_pic.yaml", tmp_path / "data")
    assert s.get("done") == 2, s
    res = Results(tmp_path / "data")
    df = res.study_table("mag_to_pic")
    assert {"shape.peak_Br", "pic.energy.total", "pic.energy.peakBr"} <= set(df.columns)
    assert np.allclose(df["shape.peak_Br"].astype(float), 0.0165)
    # the PIC stage saw the exported field at the normalized currents
    runs = res.db.query("SELECT run_id FROM row_runs WHERE stage='mag'")
    for r in runs:
        exp = tmp_path / "data" / "runs" / r["run_id"][:2] / r["run_id"] / "exports" / "fieldmap.h5"
        axes, comps = read_field(exp, "B")
        assert set(axes) == {"r", "z"} and comps["r"].shape == (len(axes["r"]), len(axes["z"]))
    peak_export = max(float(np.max(np.abs(read_field(tmp_path / "data" / "runs" / r["run_id"][:2] / r["run_id"] /
                                                         "exports" / "fieldmap.h5", "B")[1]["r"]))) for r in runs)
    assert df["pic.energy.peakBr"].astype(float).max() == pytest.approx(peak_export, rel=1e-9)


def test_nonlinear_normalization_iterates(tmp_path):
    """Without superposition the worker iterates on the current scale; the run records the final currents."""
    from bplsim.execute.folders import read_json
    d, s = run_study(HET, "loops_nl_norm.yaml", tmp_path / "data")
    assert s.get("done") == 2, s
    for case in (tmp_path / "data").glob("cases/*/*/case.json"):
        info = read_json(case)
        assert info["normalized_scale"]["k"] > 0 and len(info["normalized_scale"]["history"]) >= 2
    for m in (tmp_path / "data").glob("runs/*/*/metrics.json"):
        assert read_json(m)["shape.peak_Br"]["value"] == pytest.approx(0.0165, rel=2e-3)
