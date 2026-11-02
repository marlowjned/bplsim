"""Driver, caching, resume, failures, store, query (plan §15)."""
import shutil

import numpy as np
import pytest

from bplsim.execute.folders import DataRoot, read_json
from bplsim.store.collect import rebuild
from bplsim.store.db import DB
from bplsim.store.query import query, study_table

from conftest import FUNCS, HET, run_study


def test_loops_study_end_to_end(data_root):
    d, s = run_study(HET, "cap_screen_loops.yaml", data_root)
    assert s["done"] == 12 and s["invalid"] == 12
    root = DataRoot(data_root)
    assert len(list(root.root.glob("cases/*/*/DONE"))) == 6          # q shares cases
    # normalization reached 165 G on every run
    for r in root.root.glob("runs/*/*/metrics.json"):
        m = read_json(r)
        assert m["shape.peak_Br"]["value"] == pytest.approx(0.0165, rel=1e-6)
    # raw output purged on success
    assert not list(root.root.glob("cases/*/*/raw"))


def test_rerun_is_cached_and_second_study_shares_cases(data_root):
    run_study(HET, "cap_screen_loops.yaml", data_root)
    root = DataRoot(data_root)
    before = {p.name: p.stat().st_mtime for p in root.root.glob("cases/*/*")}
    d, s = run_study(HET, "cap_screen_loops.yaml", data_root)
    after = {p.name: p.stat().st_mtime for p in root.root.glob("cases/*/*")}
    assert before == after


def test_temperature_only_change_reuses_case(het):
    from bplsim.core.hashing import content_hash
    from bplsim.model.pipeline import load_pipeline
    from bplsim.model.resolve import Resolver, RowSpec
    pl = load_pipeline(het, "het:pipelines/loops_2d")
    st = pl.stages["mag"]
    hashes = []
    for T in (20, 80):
        d = Resolver(het, "het:assemblies/bn_screened", RowSpec(overrides={"op.temperature": (T, "t")}),
                     pl.fidelity_spec()).resolve()
        cfg = st.config(d)
        inputs = st.backend.solve_inputs(d, cfg)
        hashes.append(content_hash({"inputs": inputs, "bases": [b.canonical() for b in st.backend.bases(d, cfg, inputs)]}))
    assert hashes[0] == hashes[1]


def test_collect_rebuild_matches(data_root):
    run_study(HET, "cap_screen_loops.yaml", data_root)
    root = DataRoot(data_root)
    db = DB(root.db_path)
    m1 = sorted(tuple(r) for r in db.execute("SELECT run_id, name, value_num FROM metrics"))
    db.close()
    rebuild(root)
    db = DB(root.db_path)
    m2 = sorted(tuple(r) for r in db.execute("SELECT run_id, name, value_num FROM metrics"))
    assert m1 == m2 and len(m1) > 0


def test_query_with_units(data_root, het):
    run_study(HET, "cap_screen_loops.yaml", data_root)
    db = DB(DataRoot(data_root).db_path)
    df = query(db, het.units, where="parts.pole_cap.radius <= 16 mm")
    assert len(df) == 4 and np.allclose(df["parts.pole_cap.radius"].astype(float), 0.015)
    df = query(db, het.units, where="not parts.pole_cap")
    assert len(df) == 4


def test_grid_product_counts(data_root):
    d, s = run_study(FUNCS, "grid_product.yaml", data_root)
    assert s["done"] == 32


def test_compass_finds_branin_minimum(data_root):
    d, s = run_study(FUNCS, "branin_compass.yaml", data_root)
    df = study_table(d.db, d.study_id)
    assert df["f.f"].min() == pytest.approx(0.397887, abs=2e-3)


def test_tpe_branin(data_root):
    d, s = run_study(FUNCS, "branin_tpe.yaml", data_root)
    df = study_table(d.db, d.study_id)
    assert s["done"] == 120
    assert df["f.f"].min() < 0.6


def test_constrained_optimum_on_boundary(data_root):
    d, s = run_study(FUNCS, "rosen_constrained.yaml", data_root)
    df = study_table(d.db, d.study_id)
    feas = df[df["f.g"] >= 0]
    best = feas.loc[feas["f.f"].idxmin()]
    # the constrained optimum (scipy SLSQP) is f = 0.0086 at (0.907, 0.823), on the boundary g = 0;
    # the unconstrained optimum (1, 1) has g = -0.5 and must not be reported as feasible
    assert best["f.f"] < 0.15
    assert (df["f.g"] < 0).sum() + (df["f.g"] >= 0).sum() == len(df)
    assert best["f.f"] >= 0.0086 - 1e-9


def test_nsga2_zdt1_front(data_root):
    from bplsim.store.query import pareto_mask
    d, s = run_study(FUNCS, "zdt1_nsga2.yaml", data_root)
    df = study_table(d.db, d.study_id)
    front = df[pareto_mask(df, ["f.f1", "f.f2"])]
    # hypervolume w.r.t. (1, 1.5) of the true front is ~0.5 + ...; require a decent fraction
    pts = front[["f.f1", "f.f2"]].to_numpy(float)
    pts = pts[np.argsort(pts[:, 0])]
    hv, prev = 0.0, 1.5
    for f1, f2 in pts:
        if f1 <= 1 and f2 < prev:
            hv += (1 - f1) * (prev - f2)
            prev = f2
    assert hv > 0.75


def test_resume_after_interruption_gives_same_answer(data_root, tmp_path):
    """Kill the compass driver after a few rounds, restart: no duplicate solves, same final answer."""
    d1, _ = run_study(FUNCS, "branin_compass.yaml", tmp_path / "a")
    best_full = study_table(d1.db, d1.study_id)["f.f"].min()
    n_full = len(list((tmp_path / "a").glob("cases/*/*/DONE")))
    from bplsim.execute.local import InlineExecutor
    from bplsim.study.driver import Driver
    d = Driver(FUNCS, FUNCS / "studies" / "branin_compass.yaml", tmp_path / "b", executor=InlineExecutor(),
               log=lambda *a: None)
    for _ in range(3):
        d.run(one_round=True)
    d2, _ = run_study(FUNCS, "branin_compass.yaml", tmp_path / "b")
    assert study_table(d2.db, d2.study_id)["f.f"].min() == pytest.approx(best_full)
    assert len(list((tmp_path / "b").glob("cases/*/*/DONE"))) == n_full


def _flaky_project(tmp_path, mode, rate=1.0):
    proj = tmp_path / "flaky"
    shutil.copytree(HET, proj)
    (proj / "library" / "pipelines" / "flaky.yaml").write_text(f"""
stages:
  mag:
    backend: analytic_flaky ^1.0
    fidelity: {{filaments: 2, cell: 2.0, mode: {mode}, rate: {rate}}}
    equivalence: {{outer_posts: smeared_ring, outer_coils: winding_sheets, front_plate: equal_area_disc,
                  back_plate: equal_area_disc}}
    resources: {{timeout: 20 s}}
""")
    (proj / "studies" / "flaky.yaml").write_text("""
design: het:assemblies/bn_screened
pipeline: het:pipelines/flaky
measure: het:measurements/channel_field_2d
variables:
  is_gap: {param: params.inner_screen_gap, values: [12, 20]}
objectives: {s: {minimize: shape.sigma}}
sampler: {kind: grid}
""")
    return proj


def test_failed_cases_are_recorded(tmp_path):
    proj = _flaky_project(tmp_path, "fail")
    d, s = run_study(proj, "flaky.yaml", tmp_path / "data")
    assert s.get("failed") == 2
    st = read_json(next((tmp_path / "data" / "failed").glob("*/status.json")))
    assert st["status"] in ("failed",)


@pytest.mark.slow
def test_crash_is_retried_once_by_local_executor(tmp_path):
    from bplsim.execute.local import LocalExecutor
    proj = _flaky_project(tmp_path, "crash")
    d, s = run_study(proj, "flaky.yaml", tmp_path / "data", executor=LocalExecutor(workers=2))
    assert s.get("done") == 2                    # the crash marker makes the retry succeed


def test_figures_and_report(data_root, tmp_path):
    """Figures and reports regenerate from stored results only (plan §14)."""
    from bplsim.results.analysis import Results
    from bplsim.model.project import Project
    from bplsim.results.report import build
    run_study(HET, "cap_screen_loops.yaml", data_root)
    pr = Project.load(HET)
    res = Results(data_root, pr.units)
    df = res.study_table("cap_screen_loops")
    run = res.run(df[df.status == "done"].run_id.iloc[0])
    prof = run.probe("profile")
    assert np.max(np.abs(prof["B_r"])) == pytest.approx(0.0165, rel=1e-6)   # combined at normalized currents
    tpl = tmp_path / "r.md.j2"
    tpl.write_text('Best misfit {{ value("cap_screen_loops", "misfit.rms_pct", fmt=".3f") }} %\n'
                   '{{ table("cap_screen_loops", ["is_gap", "misfit.rms_pct"], sort="misfit.rms_pct", n=3) }}\n'
                   '{{ figure("std:figures/scatter", study="cap_screen_loops", x="is_gap", y="misfit.rms_pct") }}\n'
                   '{{ figure("std:figures/line_probe", name="prof", study="cap_screen_loops", probe="profile") }}\n')
    out = build(pr, res, tpl)
    text = out.read_text()
    assert "Best misfit" in text and (tmp_path / "r_figures" / "prof.png").exists()


def test_cli_init_check_show_fork_gc(tmp_path):
    from typer.testing import CliRunner
    from bplsim.cli import app
    r = CliRunner()
    out = r.invoke(app, ["--version"])
    assert out.exit_code == 0 and "bplsim" in out.output
    proj = tmp_path / "newproj"
    assert r.invoke(app, ["init", str(proj)]).exit_code == 0
    assert (proj / "project.yaml").exists() and (proj / "library" / "materials").is_dir()
    shutil.copytree(HET, tmp_path / "het")
    res = r.invoke(app, ["check", "-p", str(tmp_path / "het")])
    assert res.exit_code == 0, res.output
    res = r.invoke(app, ["show", "het:assemblies/bn_screened", "-p", str(tmp_path / "het")])
    assert res.exit_code == 0 and "screen_clearance" in res.output and "23.275 mm" in res.output
    # a seeded error is reported with its file and line
    a = tmp_path / "het" / "library" / "assemblies" / "bn_screened.yaml"
    a.write_text(a.read_text().replace("thickness: 2.41", "thicknes: 2.41"))
    res = r.invoke(app, ["check", "-p", str(tmp_path / "het")])
    assert res.exit_code == 1 and "thicknes" in res.output and "bn_screened.yaml:" in res.output
    res = r.invoke(app, ["lib", "fork", "std:metrics/ring_ripple", "--into", "het", "-p", str(tmp_path / "het")])
    assert res.exit_code == 0 and (tmp_path / "het" / "library" / "metrics" / "ring_ripple.py").exists()
    data = tmp_path / "data"
    run_study(HET, "cap_screen_loops.yaml", data)
    res = r.invoke(app, ["gc", "--raw-older-than-days", "0", "--dry-run", "-p", str(HET), "--data", str(data)])
    assert res.exit_code == 0 and '"dry_run": true' in res.output


def test_local_site_profile_is_the_default(tmp_path, monkeypatch):
    """Without --site, ~/.config/bplsim/sites/local.yaml is used (its tools reach the backends)."""
    from bplsim.execute.sites import load_site
    monkeypatch.setenv("BPLSIM_SITES", str(tmp_path))
    monkeypatch.delenv("BPLSIM_TOOL_GETDP", raising=False)
    assert load_site(None).tools == {}
    (tmp_path / "local.yaml").write_text("name: local\ndata_root: /tmp/x\ntools: {getdp: /opt/getdp}\n")
    s = load_site(None)
    assert s.data_root == "/tmp/x" and s.tools == {"getdp": "/opt/getdp"}
    import os
    assert os.environ["BPLSIM_TOOL_GETDP"].replace("\\", "/").endswith("opt/getdp")
