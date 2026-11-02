"""Backend registry."""
from __future__ import annotations

from bplsim.core.errors import ConfigError
from bplsim.backends.base import Backend, Basis, Capabilities, ExecResult, FieldAccess, StageConfig  # noqa: F401

_REGISTRY: dict[str, type[Backend]] = {}


def register(cls: type[Backend]) -> type[Backend]:
    _REGISTRY[cls.name] = cls
    return cls


def _builtin():
    if _REGISTRY:
        return
    from bplsim.backends.analytic import AnalyticFlaky, AnalyticFunctions, AnalyticLoops
    for c in (AnalyticLoops, AnalyticFunctions, AnalyticFlaky):
        register(c)
    try:
        from bplsim.backends.getdp_axisym import GetDPAxisym
        register(GetDPAxisym)
    except ImportError:
        pass
    try:
        from bplsim.backends.getdp_3d import GetDP3D
        register(GetDP3D)
    except ImportError:
        pass
    try:
        from bplsim.backends.warpx import WarpX
        register(WarpX)
    except ImportError:
        pass


def _compatible(have: str, want: str) -> bool:
    """`want` like '^1.0' (same major, >= minor) or '1.2' (exact major.minor) or '' (any)."""
    if not want:
        return True
    h = [int(x) for x in have.split(".")[:2]]
    w = [int(x) for x in want.lstrip("^").split(".")[:2]] + [0]
    if want.startswith("^"):
        return h[0] == w[0] and h[1] >= w[1]
    return h[:2] == w[:2]


def get_backend(spec: str) -> Backend:
    """`spec` is 'name' or 'name ^1.0'."""
    _builtin()
    name, _, want = spec.strip().partition(" ")
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ConfigError(f"unknown backend {name!r} (known: {', '.join(sorted(_REGISTRY))})")
    if not _compatible(cls.version, want.strip()):
        raise ConfigError(f"backend {name} is version {cls.version}, the pipeline needs {want}")
    return cls()


def backends() -> dict[str, type[Backend]]:
    _builtin()
    return dict(_REGISTRY)
