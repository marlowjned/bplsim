"""`bplsim check`, `init` and `lib fork`."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from bplsim.core.errors import BplsimError, ConfigError, ErrorList
from bplsim.core.hashing import content_hash, major_minor


def check_project(project_dir: Path, fingerprints: bool = True) -> list[BaseException]:
    from bplsim.model.checks import prescreen
    from bplsim.measure.engine import define_measurements, load_measurement_set
    from bplsim.model.pipeline import load_pipeline
    from bplsim.model.project import Project
    from bplsim.model.resolve import Resolver
    try:
        pr = Project.load(project_dir)
    except BplsimError as e:
        return [e]
    errors: list[BaseException] = list(pr.load_all())
    designs = {}
    for e in pr.entries("assemblies"):
        try:
            d = Resolver(pr, e.id).resolve()
            ps = prescreen(d, d.checks_spec)
            for f in ps.failures:
                errors.append(ConfigError(f"baseline fails check {f.name}: {f.detail}", str(e.path)))
            designs[e.id] = d
        except ErrorList as el:
            errors.extend(el.errors)
        except BplsimError as ex:
            errors.append(ex if getattr(ex, "file", None) else ConfigError(str(ex), str(e.path)))
    for e in pr.entries("pipelines"):
        try:
            load_pipeline(pr, e.id)
        except BplsimError as ex:
            errors.append(ConfigError(str(ex), str(e.path)))
    for e in pr.entries("measurements"):
        try:
            ms = load_measurement_set(pr, e.id)
            for alias, spec in ms.probes.items():
                pr.probe(spec["probe"])
            for alias, spec in ms.metrics.items():
                pr.metric(spec["metric"])
            # define against the first assembly that accepts it (parameters, slots, wiring)
            ok = False
            last = None
            for d in designs.values():
                try:
                    define_measurements(pr, d, ms)
                    ok = True
                    break
                except BplsimError as ex:
                    last = ex
            if designs and not ok and last is not None:
                errors.append(ConfigError(f"no assembly accepts this measurement set: {last}", str(e.path)))
        except BplsimError as ex:
            errors.append(ConfigError(str(ex), str(e.path)))
    if fingerprints and not errors:
        errors.extend(check_fingerprints(pr, designs))
    return errors


def check_fingerprints(pr, designs: dict) -> list[BaseException]:
    """R8: run every probe and metric of every measurement set on the analytic loops backend; if an
    entry's output changed while its MAJOR.MINOR version did not, report it."""
    from bplsim.backends.analytic import AnalyticLoops
    from bplsim.backends.base import StageConfig
    from bplsim.measure.engine import compute_metrics, define_measurements, evaluate_probe, load_measurement_set
    store = pr.root / ".bplsim" / "fingerprints.json"
    old = json.loads(store.read_text()) if store.exists() else {}
    new, errors = {}, []
    be = AnalyticLoops()
    for e in pr.entries("measurements"):
        ms = load_measurement_set(pr, e.id)
        for aid, d in designs.items():
            try:
                pdefs, mdefs = define_measurements(pr, d, ms)
                eqs = {}
                for s in d.slots:
                    part = d.part(s)
                    if not part.axisymmetric:
                        names = list(part.type_cls.equivalences())
                        if names:
                            eqs[s] = names[0]
                cfg = StageConfig("fp", be.name, {"filaments": 2, "cell": 2e-3, "edge_points": 2, "nonlinear": False},
                                  eqs)
                inputs = be.solve_inputs(d, cfg)
                bases = be.bases(d, cfg, inputs)
                case = {p.def_hash: {b.name: evaluate_probe(pr, d, p, be.field_access(inputs, None, b)) for b in bases}
                        for p in pdefs.values()}
                mets = compute_metrics(pr, d, mdefs, case, [b.canonical() for b in bases])
            except BplsimError:
                continue
            except Exception:  # noqa: BLE001 - entries that cannot run on air-core loops are skipped
                continue
            for alias, p in pdefs.items():
                data = {b: {k: _round(v) for k, v in dd.fields.items()} for b, dd in case[p.def_hash].items()}
                new[f"{p.probe_id}|{aid}|{p.def_hash[:12]}"] = [major_minor(p.version), content_hash(data)]
            for alias, m in mdefs.items():
                new[f"{m.metric_id}|{aid}|{m.def_hash[:12]}"] = [major_minor(m.version),
                                                                  content_hash({k: _round(v) for k, v in mets[alias].items()})]
            break
    for k, (ver, h) in new.items():
        if k in old and old[k][0] == ver and old[k][1] != h:
            errors.append(ConfigError(f"{k.split('|')[0]}: output changed but version {ver} did not; bump MINOR "
                                      "(R8) or revert the change"))
    if not errors:
        store.parent.mkdir(exist_ok=True)
        store.write_text(json.dumps({**old, **new}, indent=1, sort_keys=True))
    return errors


def _round(v):
    import numpy as np
    if isinstance(v, str):
        return v
    a = np.asarray(v, dtype=float)
    return np.round(a, 9).tolist() if a.ndim else float(np.round(a, 9))


PROJECT_TEMPLATE = """name: {name}
namespace: {name}
bplsim: ">=0.1,<0.2"
libraries:
  std: {{builtin: true}}
units:
  length: mm
  angle: deg
  current: A
  temperature: degC
  magnetic_flux_density: G
  power: W
"""


def init_project(directory: Path, name: str):
    directory = Path(directory)
    if (directory / "project.yaml").exists():
        raise ConfigError(f"{directory} already has a project.yaml")
    for sub in ("materials", "part_types", "parts", "assemblies", "probes", "metrics", "references",
                "measurements", "pipelines"):
        (directory / "library" / sub).mkdir(parents=True, exist_ok=True)
    (directory / "studies").mkdir(exist_ok=True)
    (directory / "project.yaml").write_text(PROJECT_TEMPLATE.format(name=name))
    (directory / "library" / "vocabulary.yaml").write_text(
        "mu_r_linear: [mu_r, relative_permeability]\nresistivity: [rho_e, electrical_resistivity]\n")
    (directory / ".gitignore").write_text(".bplsim/\n__pycache__/\n")


def fork_entry(project_dir: Path, entry_id: str, into: str) -> Path:
    from bplsim.model.project import Project, split_id
    pr = Project.load(project_dir)
    e = pr.entry(entry_id)
    ns, folder, name = split_id(entry_id)
    if into != pr.namespace:
        raise ConfigError(f"can only fork into this project's namespace {pr.namespace!r}")
    dst = pr.root / "library" / folder / e.path.name
    if dst.exists():
        raise ConfigError(f"{dst} already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(e.path, dst)
    return dst
