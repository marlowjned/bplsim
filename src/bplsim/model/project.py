"""Projects and libraries (rules R1-R3, plan §3).

A project is a folder with ``project.yaml``, a ``library/`` and ``studies/``. Libraries are folders of
entries under a namespace; ids come from paths: ``<ns>:<folder>/<file stem>``.
"""
from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bplsim.core.errors import ConfigError, ErrorList
from bplsim.model.materials import Material, Vocabulary, parse_property
from bplsim.units import UnitSystem
from bplsim.core.yamlio import YamlDoc, load_yaml

FOLDERS = {
    "materials": "material", "part_types": "part_type", "parts": "part", "assemblies": "assembly",
    "probes": "probe", "metrics": "metric", "references": "reference", "measurements": "measurement",
    "pipelines": "pipeline", "figures": "figure",
}
PY_FOLDERS = {"part_types", "probes", "metrics", "references", "figures"}
YAML_SUFFIXES = (".yaml", ".yml")
STD_ROOT = Path(__file__).parents[1] / "std"          # bplsim/std


@dataclass(frozen=True)
class Entry:
    id: str
    ns: str
    folder: str
    name: str
    path: Path

    @property
    def kind(self) -> str:
        return FOLDERS[self.folder]

    @property
    def is_python(self) -> bool:
        return self.path.suffix == ".py"

    @property
    def module_name(self) -> str:
        return f"{self.ns}.{self.folder}.{self.name}"


def split_id(entry_id: str) -> tuple[str, str, str]:
    try:
        ns, rest = entry_id.split(":", 1)
        folder, name = rest.split("/", 1)
    except ValueError:
        raise ConfigError(f"{entry_id!r} is not an entry id (expected <namespace>:<folder>/<name>)") from None
    return ns, folder, name


class Library:
    def __init__(self, ns: str, root: Path):
        self.ns, self.root = ns, Path(root)
        self.entries: dict[str, Entry] = {}
        self.vocabulary: dict = {}
        self.scan()

    def scan(self):
        if not self.root.is_dir():
            raise ConfigError(f"library folder not found: {self.root}")
        for folder in FOLDERS:
            d = self.root / folder
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if f.name.startswith(("_", ".")) or not f.is_file():
                    continue
                if folder in PY_FOLDERS and f.suffix == ".py" or f.suffix in YAML_SUFFIXES:
                    eid = f"{self.ns}:{folder}/{f.stem}"
                    if eid in self.entries:
                        raise ConfigError(f"two files define {eid}: {self.entries[eid].path.name} and {f.name}",
                                          str(f))
                    self.entries[eid] = Entry(eid, self.ns, folder, f.stem, f)
        voc = self.root / "vocabulary.yaml"
        if voc.exists():
            self.vocabulary = load_yaml(voc).data or {}


def _install_namespace(ns: str, root: Path):
    """Make `import <ns>.<folder>.<name>` load files from `root` (a fresh namespace each time)."""
    for name in [m for m in sys.modules if m == ns or m.startswith(ns + ".")]:
        del sys.modules[name]
    mod = types.ModuleType(ns)
    mod.__path__ = [str(root)]
    mod.__file__ = str(root / "__init__.py")
    mod.__bplsim_library__ = True
    sys.modules[ns] = mod
    importlib.invalidate_caches()


class Project:
    def __init__(self, root: Path, config: dict, libraries: dict[str, Library], units: UnitSystem,
                 config_doc: YamlDoc | None = None):
        self.root = Path(root)
        self.config = config
        self.name = config.get("name", self.root.name)
        self.namespace = config.get("namespace", self.name)
        self.libraries = libraries
        self.units = units
        self.config_doc = config_doc
        self.vocabulary = Vocabulary()
        for lib in libraries.values():
            if lib.vocabulary:
                self.vocabulary.add(lib.vocabulary, str(lib.root / "vocabulary.yaml"))
        for ns, lib in libraries.items():
            _install_namespace(ns, lib.root)
        self._cache: dict[str, Any] = {}

    # ---- loading ---------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path = ".", library_roots: dict[str, str | Path] | None = None) -> "Project":
        path = Path(path)
        file = path if path.is_file() else path / "project.yaml"
        doc = load_yaml(file)
        cfg = doc.data or {}
        allowed = {"name", "namespace", "bplsim", "libraries", "units", "description"}
        for k in cfg:
            if k not in allowed:
                raise doc.error(f"unknown key {k!r} (allowed: {', '.join(sorted(allowed))})", k)
        root = file.parent
        ns = cfg.get("namespace", cfg.get("name", root.name))
        roots: dict[str, Path] = {}
        for lib_ns, spec in (cfg.get("libraries") or {}).items():
            spec = spec or {}
            if spec.get("builtin"):
                if lib_ns != "std":
                    raise doc.error("only 'std' is builtin", "libraries", lib_ns)
                roots[lib_ns] = STD_ROOT
            elif "path" in spec:
                roots[lib_ns] = (root / spec["path"]).resolve()
            elif "git" in spec:
                roots[lib_ns] = _git_library(lib_ns, spec["git"], spec.get("ref", "main"))
            else:
                raise doc.error("a library needs builtin, path or git", "libraries", lib_ns)
        roots.setdefault("std", STD_ROOT)
        roots[ns] = root / "library"
        for k, v in (library_roots or {}).items():
            roots[k] = Path(v)
        try:
            units = UnitSystem(cfg.get("units") or {})
        except ValueError as e:
            raise doc.error(str(e), "units") from None
        libs = {k: Library(k, v) for k, v in roots.items()}
        return cls(root, cfg, libs, units, doc)

    # ---- entries ---------------------------------------------------------------------------------
    def entry(self, entry_id: str, folder: str | None = None) -> Entry:
        ns, f, name = split_id(entry_id)
        if folder and f != folder:
            raise ConfigError(f"{entry_id} is a {FOLDERS.get(f, f)}, but a {FOLDERS[folder]} is needed here")
        lib = self.libraries.get(ns)
        if lib is None:
            raise ConfigError(f"{entry_id}: unknown namespace {ns!r} (known: {', '.join(self.libraries)})")
        e = lib.entries.get(entry_id)
        if e is None:
            near = [k for k in lib.entries if k.split("/")[0] == f"{ns}:{f}"]
            raise ConfigError(f"no entry {entry_id}" + (f"; {f} has: {', '.join(n.split('/')[1] for n in near)}"
                                                         if near else ""))
        return e

    def entries(self, folder: str | None = None) -> list[Entry]:
        out = []
        for lib in self.libraries.values():
            out.extend(e for e in lib.entries.values() if folder is None or e.folder == folder)
        return out

    def doc(self, entry_id: str, folder: str | None = None) -> YamlDoc:
        e = self.entry(entry_id, folder)
        key = "doc:" + entry_id
        if key not in self._cache:
            if e.is_python:
                raise ConfigError(f"{entry_id} is a Python entry")
            self._cache[key] = load_yaml(e.path)
        return self._cache[key]

    def python_entry(self, entry_id: str, folder: str | None = None):
        e = self.entry(entry_id, folder)
        key = "py:" + entry_id
        if key in self._cache:
            return self._cache[key]
        if not e.is_python:
            raise ConfigError(f"{entry_id} is a YAML entry, not Python")
        try:
            mod = importlib.import_module(e.module_name)
        except Exception as ex:  # noqa: BLE001 - surface any import error with the file name
            raise ConfigError(f"cannot import: {type(ex).__name__}: {ex}", str(e.path)) from ex
        found = []
        for _, obj in inspect.getmembers(mod):
            if getattr(obj, "__module__", None) != mod.__name__:
                continue
            if e.folder == "part_types":
                from bplsim.parts import PartType
                if inspect.isclass(obj) and issubclass(obj, PartType) and obj is not PartType:
                    found.append(obj)
            else:
                info = getattr(obj, "_bplsim", None)
                if info and info.get("kind") == FOLDERS[e.folder]:
                    found.append(obj)
        if len(found) != 1:
            what = "PartType subclass" if e.folder == "part_types" else f"@{FOLDERS[e.folder]} function"
            raise ConfigError(f"must define exactly one {what}; found {len(found)}", str(e.path))
        obj = found[0]
        try:
            obj._entry_id = entry_id
        except (AttributeError, TypeError):
            pass
        self._cache[key] = obj
        return obj

    def part_type(self, entry_id: str):
        return self.python_entry(entry_id, "part_types")

    def probe(self, entry_id: str):
        return self.python_entry(entry_id, "probes")

    def metric(self, entry_id: str):
        return self.python_entry(entry_id, "metrics")

    def reference(self, entry_id: str):
        e = self.entry(entry_id, "references")
        return self.python_entry(entry_id) if e.is_python else self.doc(entry_id)

    def material(self, entry_id: str) -> Material:
        key = "mat:" + entry_id
        if key in self._cache:
            return self._cache[key]
        chain, seen, cur = [], set(), entry_id
        while cur:
            if cur in seen:
                raise ConfigError(f"material inheritance cycle at {cur}")
            seen.add(cur)
            d = self.doc(cur, "materials")
            chain.append((cur, d))
            cur = (d.data or {}).get("extends")
        props, description = {}, ""
        for mid, d in reversed(chain):
            data = d.data or {}
            for k in data:
                if k not in ("extends", "description", "sources", "properties"):
                    raise d.error(f"unknown key {k!r} in a material", k)
            description = data.get("description", description)
            seen_canon: dict[str, str] = {}
            for name, raw in (data.get("properties") or {}).items():
                canon = self.vocabulary.canonical(name)
                if canon in seen_canon:
                    raise d.error(f"{name!r} and {seen_canon[canon]!r} are the same property ({canon})",
                                  "properties", name)
                seen_canon[canon] = name
                try:
                    props[canon] = parse_property(name, raw, Path(d.file).parent, self.units, d.file)
                except ValueError as e:
                    raise d.error(str(e), "properties", name) from None
        mat = Material(entry_id, props, description, self.vocabulary)
        self._cache[key] = mat
        return mat

    # ---- checks ----------------------------------------------------------------------------------
    def load_all(self) -> list[BaseException]:
        """Load every entry; return all errors (used by `bplsim check`)."""
        errors: list[BaseException] = []
        for e in self.entries():
            try:
                if e.folder == "materials":
                    self.material(e.id)
                elif e.is_python:
                    self.python_entry(e.id)
                else:
                    self.doc(e.id)
            except ErrorList as el:
                errors.extend(el.errors)
            except ConfigError as ce:
                errors.append(ce)
        return errors


def _git_library(ns: str, url: str, ref: str) -> Path:
    cache = Path.home() / ".cache" / "bplsim" / "libs" / f"{ns}@{ref}"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, url, str(cache)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ConfigError(f"cannot clone library {ns} from {url}@{ref}: {r.stderr.strip()}")
    return cache / "library" if (cache / "library").is_dir() else cache
