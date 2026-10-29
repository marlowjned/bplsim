"""Site profiles (example §14): where things run. Stored in ~/.config/bplsim/sites/<name>.yaml.

Fields: name, data_root, executor (local | slurm), local {workers, memory_limit}, slurm {...},
container, tools {getdp: path, ...}. Without a profile, the implicit 'local' site is used.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .units import DIMS, DEFAULT_UNITS
from .yamlio import load_yaml

SITE_KEYS = {"name", "data_root", "executor", "local", "slurm", "container", "tools", "description", "remote"}


def sites_dir() -> Path:
    return Path(os.environ.get("BPLSIM_SITES", Path.home() / ".config" / "bplsim" / "sites"))


@dataclass
class Site:
    name: str = "local"
    data_root: str = str(Path.home() / "bplsim_data")
    executor: str = "local"
    local: dict = field(default_factory=dict)
    slurm: dict = field(default_factory=dict)
    container: str | None = None
    tools: dict = field(default_factory=dict)
    remote: dict = field(default_factory=dict)

    def apply_tools(self):
        """Expose tool paths to backends (and to worker processes) as BPLSIM_TOOL_<NAME>."""
        for name, path in self.tools.items():
            os.environ[f"BPLSIM_TOOL_{name.upper()}"] = str(Path(path).expanduser())

    def make_executor(self, workers: int | None = None):
        if self.executor == "local":
            from .execute.local import LocalExecutor
            mem = self.local.get("memory_limit")
            mem = DEFAULT_UNITS.to_si(mem, DIMS["memory"]) if isinstance(mem, str) else mem
            return LocalExecutor(workers or self.local.get("workers") if self.local.get("workers") != "auto" else workers,
                                 memory_limit=mem)
        if self.executor == "inline":
            from .execute.local import InlineExecutor
            return InlineExecutor()
        if self.executor == "slurm":
            from .execute.slurm import SlurmExecutor
            return SlurmExecutor(self)
        raise ConfigError(f"site {self.name}: unknown executor {self.executor!r}")


def load_site(name: str | None) -> Site:
    name = name or "local"                     # no --site: the 'local' profile if it exists, else defaults
    if name == "local" and not (sites_dir() / "local.yaml").exists():
        s = Site()
    else:
        path = Path(name) if name.endswith((".yaml", ".yml")) else sites_dir() / f"{name}.yaml"
        doc = load_yaml(path)
        data = doc.data or {}
        for k in data:
            if k not in SITE_KEYS:
                raise doc.error(f"unknown site key {k!r} (allowed: {', '.join(sorted(SITE_KEYS))})", k)
        s = Site(name=data.get("name", path.stem), data_root=data.get("data_root", Site.data_root),
                 executor=data.get("executor", "local"), local=data.get("local") or {}, slurm=data.get("slurm") or {},
                 container=data.get("container"), tools=data.get("tools") or {}, remote=data.get("remote") or {})
    s.apply_tools()
    return s


def find_tool(name: str, default_names: tuple[str, ...] = ()) -> str | None:
    """A tool's executable: BPLSIM_TOOL_<NAME>, then PATH."""
    import shutil
    env = os.environ.get(f"BPLSIM_TOOL_{name.upper()}")
    if env:
        return env
    for n in (name,) + default_names:
        p = shutil.which(n)
        if p:
            return p
    return None
