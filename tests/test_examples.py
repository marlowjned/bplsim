"""The hand-out projects in examples/ keep working: they validate, their studies run and give the results their
READMEs quote, and their reports build. The magnet sweep needs GetDP (slow)."""
import os
import shutil
from pathlib import Path

import pytest

from bplsim.store.query import study_table
from conftest import run_study

EXAMPLES = Path(__file__).parents[1] / "examples"
GETDP = os.environ.get("BPLSIM_TOOL_GETDP") or shutil.which("getdp")


def _copy(name, tmp_path):
    """Work on a copy: building a report writes next to its template."""
    dst = tmp_path / name
    shutil.copytree(EXAMPLES / name, dst, ignore=shutil.ignore_patterns(".bplsim", "__pycache__"))
    return dst


@pytest.mark.parametrize("name", ["functions", "magnet"])
def test_example_checks(name):
    from typer.testing import CliRunner

    from bplsim.cli import app
    res = CliRunner().invoke(app, ["check", "-p", str(EXAMPLES / name)])
    assert res.exit_code == 0, res.output


def test_functions_example(tmp_path):
    from bplsim.model.project import Project
    from bplsim.results.analysis import Results
    from bplsim.results.report import build
    proj, data = _copy("functions", tmp_path), tmp_path / "data"
    d, _ = run_study(proj, "branin_grid.yaml", data)
    assert len(study_table(d.db, d.study_id)) == 32
    d, _ = run_study(proj, "branin_compass.yaml", data)
    assert study_table(d.db, d.study_id)["f.f"].min() == pytest.approx(0.397887, abs=2e-3)
    pr = Project.load(proj)
    text = build(pr, Results(data, pr.units), proj / "reports" / "summary.md.j2").read_text()
    assert "compass search | 0.398" in text and (proj / "reports" / "summary_figures" / "sweep.png").exists()


@pytest.mark.slow
@pytest.mark.skipif(not GETDP, reason="needs GetDP")
def test_magnet_example(tmp_path):
    from bplsim.model.project import Project
    from bplsim.results.analysis import Results
    from bplsim.results.report import build
    proj, data = _copy("magnet", tmp_path), tmp_path / "data"
    d, _ = run_study(proj, "gap_sweep.yaml", data)
    df = study_table(d.db, d.study_id)
    best = df.loc[df["misfit.rms_pct"].astype(float).idxmin()]
    assert (df["status"] == "done").all() and best["is_gap"] == 14
    assert float(best["misfit.rms_pct"]) == pytest.approx(4.71, abs=0.05)
    pr = Project.load(proj)
    assert "14 mm" in build(pr, Results(data, pr.units), proj / "reports" / "gap_sweep.md.j2").read_text()
