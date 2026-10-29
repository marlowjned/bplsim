import shutil

import pytest

from bplsim.checks import prescreen
from bplsim.errors import ConfigError, ResolveError
from bplsim.project import Project
from bplsim.resolve import Resolver, RowSpec

from conftest import HET


def test_example_show_values(het):
    """Example doc §7: the values `bplsim show het:assemblies/bn_screened` prints."""
    d = Resolver(het, "het:assemblies/bn_screened").resolve()
    v = d.values
    assert v["params.front_plate_inner_z"] == pytest.approx(-9.525e-3)
    assert v["params.cap_back_z"] == pytest.approx(-9.525e-3)
    assert v["params.screen_tip_z"] == pytest.approx(-27.525e-3)
    assert v["parts.inner_core.length"] == pytest.approx(41.275e-3)
    assert v["parts.inner_coil.length"] == pytest.approx(40.94e-3)
    assert v["parts.inner_coil.build"] == pytest.approx(4.45e-3)
    assert v["parts.inner_screen.length"] == pytest.approx(23.275e-3)
    assert v["parts.back_plate.bore_radius"] == pytest.approx(3.4e-3)
    assert v["parts.outer_posts.pitch"] == pytest.approx(3.14159265 / 2)
    assert d.origins["parts.back_plate.bore_radius"].endswith("bpl1000_bn.yaml:10")
    assert "pole_cap_flat (default)" in d.origins["parts.pole_cap.chamfer_width"]


def test_example_checks(het):
    d = Resolver(het, "het:assemblies/bn_screened").resolve()
    ps = prescreen(d, d.checks_spec)
    assert ps.ok
    by = {i.name: i for i in ps.items}
    assert by["cap_in_bore"].slack == pytest.approx(0.12e-3 - 0.1e-3, abs=1e-9)
    assert by["posts_on_plate"].slack == pytest.approx(3.175e-3 - 1e-3, abs=1e-9)
    assert by["screen_clearance"].slack == pytest.approx(0.26e-3 - 0.1e-3, abs=1e-9)
    assert by["outer_posts.posts_do_not_touch"].slack == pytest.approx(70.7526e-3, abs=1e-6)
    assert by["outer_coils.coils_do_not_touch"].slack == pytest.approx(63.6326e-3, abs=1e-6)


def test_slot_none_guard_and_core_extends(het):
    rs = RowSpec(slot_choices={"pole_cap": (None, "test")})
    d = Resolver(het, "het:assemblies/bn_screened", rs).resolve()
    assert d.values["params.cap_back_z"] == 0
    assert d.values["parts.inner_core.length"] == pytest.approx(50.8e-3)
    assert "pole_cap" not in d.slots
    assert prescreen(d, d.checks_spec).ok


def test_slot_choice_keeps_placement(het):
    rs = RowSpec(slot_choices={"pole_cap": ("het:parts/cap_flat_r15_t3", "test")})
    d = Resolver(het, "het:assemblies/bn_screened", rs).resolve()
    assert d.values["parts.pole_cap.radius"] == pytest.approx(15e-3)
    assert d.values["parts.pole_cap.at"] == 0
    assert d.values["parts.inner_core.at"] == pytest.approx(-3e-3)


def test_non_optional_slot_cannot_be_emptied(het):
    with pytest.raises(ResolveError, match="not optional"):
        Resolver(het, "het:assemblies/bn_screened", RowSpec(slot_choices={"channel": (None, "t")}))


def test_overlap_detected(het):
    rs = RowSpec(assignments={"parts.inner_screen.thickness": ("3 mm", "t")})
    d = Resolver(het, "het:assemblies/bn_screened", rs).resolve()
    ps = prescreen(d, d.checks_spec)
    assert not ps.ok
    assert any("overlap" in f.name for f in ps.failures)


def test_bounds_error_has_location(het):
    rs = RowSpec(assignments={"parts.pole_cap.radius": (2, "study variable r")})
    with pytest.raises(ResolveError, match="below the minimum"):
        Resolver(het, "het:assemblies/bn_screened", rs).resolve()


def test_unknown_param_names_file_and_line(tmp_path):
    proj = tmp_path / "p"
    shutil.copytree(HET, proj)
    a = proj / "library" / "assemblies" / "bpl1000_bn.yaml"
    a.write_text(a.read_text().replace("radius: 9.525\n      length:", "radius: 9.525\n      lenght: 3\n      length:"))
    pr = Project.load(proj)
    with pytest.raises(ResolveError) as ei:
        Resolver(pr, "het:assemblies/bn_screened").resolve()
    msg = str(ei.value)
    assert "lenght" in msg and "bpl1000_bn.yaml:" in msg


def test_cycle_detected(tmp_path):
    proj = tmp_path / "p"
    shutil.copytree(HET, proj)
    a = proj / "library" / "assemblies" / "bn_screened.yaml"
    a.write_text(a.read_text().replace("inner_screen_gap: 18 mm", 'inner_screen_gap: "${ params.screen_tip_z }"'))
    pr = Project.load(proj)
    with pytest.raises(Exception, match="cycle"):
        Resolver(pr, "het:assemblies/bn_screened").resolve()


def test_material_inheritance_and_alias(het):
    m = het.material("het:materials/steel_1018")
    assert float(m.mu_r_linear) == 2200
    assert float(m.mu_r) == 2200                         # alias
    assert float(m.density) == 7850                       # inherited
    w = het.material("het:materials/wire_awg20_mw16c")
    assert w.resistivity.at(293.15) == pytest.approx(1.724e-8)
    assert w.resistivity.at(353.15) == pytest.approx(1.724e-8 * (1 + 0.00393 * 60))


def test_ids_and_wrong_kind(het):
    with pytest.raises(ConfigError, match="no entry"):
        het.entry("het:materials/unobtainium")
    with pytest.raises(ConfigError):
        het.material("het:parts/cap_flat_r17p6")


def test_material_swap_through_an_assembly_parameter(tmp_path):
    """One variable switches the material of several parts: an assembly param holds a material id."""
    proj = tmp_path / "p"
    shutil.copytree(HET, proj)
    a = proj / "library" / "assemblies" / "bpl1000_bn.yaml"
    text = a.read_text()
    text = text.replace("  cap_back_z:", "  iron: het:materials/a36\n  cap_back_z:", 1)
    text = text.replace("      material: het:materials/steel_1018", '      material: "${ params.iron }"')
    text = text.replace("      material: het:materials/a36", '      material: "${ params.iron }"')
    a.write_text(text)
    pr = Project.load(proj)
    d = Resolver(pr, "het:assemblies/bn_screened").resolve()
    assert d.values["parts.inner_core.material"].id == "het:materials/a36"
    rs = RowSpec(assignments={"params.iron": ("het:materials/steel_1018", "study variable iron")})
    d = Resolver(pr, "het:assemblies/bn_screened", rs).resolve()
    assert d.values["parts.inner_core.material"].id == "het:materials/steel_1018"
    assert d.values["parts.outer_posts.material"].id == "het:materials/steel_1018"
