"""YAML loading that keeps file and line numbers for every value, so errors can point at them."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from bplsim.core.errors import ConfigError

_yaml = YAML(typ="rt")


@dataclass(frozen=True)
class Loc:
    file: str
    line: int | None = None

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file


def _plain(node: Any, file: str, prefix: tuple, locs: dict) -> Any:
    if isinstance(node, CommentedMap):
        out = {}
        for k, v in node.items():
            key = str(k)
            try:
                line = node.lc.key(k)[0] + 1
            except Exception:  # noqa: BLE001 - ruamel may not track every key
                line = None
            locs[prefix + (key,)] = Loc(file, line)
            out[key] = _plain(v, file, prefix + (key,), locs)
        return out
    if isinstance(node, CommentedSeq):
        out = []
        for i, v in enumerate(node):
            try:
                line = node.lc.item(i)[0] + 1
            except Exception:  # noqa: BLE001
                line = None
            locs[prefix + (i,)] = Loc(file, line)
            out.append(_plain(v, file, prefix + (i,), locs))
        return out
    if hasattr(node, "value") and type(node).__module__.startswith("ruamel"):
        return node.value if not isinstance(node, str) else str(node)
    if isinstance(node, str):
        return str(node)
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    return node


@dataclass
class YamlDoc:
    data: Any
    locs: dict
    file: str

    def loc(self, *path) -> Loc:
        """Location of the deepest known prefix of path."""
        p = tuple(path)
        while p:
            if p in self.locs:
                return self.locs[p]
            p = p[:-1]
        return Loc(self.file, 1)

    def error(self, message: str, *path) -> ConfigError:
        loc = self.loc(*path)
        return ConfigError(message, loc.file, loc.line, ".".join(str(x) for x in path) or None)


def load_yaml(path: str | Path) -> YamlDoc:
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = _yaml.load(fh)
    except FileNotFoundError:
        raise ConfigError("file not found", str(path)) from None
    except Exception as e:  # noqa: BLE001 - ruamel raises several types
        mark = getattr(e, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        raise ConfigError(f"invalid YAML: {getattr(e, 'problem', e)}", str(path), line) from None
    locs: dict = {}
    data = _plain(raw if raw is not None else {}, str(path), (), locs)
    return YamlDoc(data, locs, str(path))


def dump_yaml(data: Any, path: str | Path) -> None:
    y = YAML()
    y.default_flow_style = False
    with open(path, "w", encoding="utf-8") as fh:
        y.dump(data, fh)
