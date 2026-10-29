"""Assembly documents: loading, `extends` merging with value origins (rule R7)."""
from __future__ import annotations

import copy
from typing import Any

from .errors import ConfigError
from .yamlio import YamlDoc

ASSEMBLY_KEYS = {"description", "extends", "params", "parts", "checks", "op"}
SLOT_KEYS = {"use", "type", "params", "at", "optional"}
PLACEMENT_KEYS = {"at", "optional"}
CONTENT_KEYS = {"use", "type", "params"}


class Tree:
    """A merged YAML tree plus the origin (file:line or a description) of every leaf."""

    def __init__(self):
        self.data: dict = {}
        self.origins: dict[tuple, str] = {}
        self.emptied: set[tuple] = set()   # paths explicitly set to null

    def get(self, *path, default=None):
        node = self.data
        for k in path:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def origin(self, *path) -> str:
        p = tuple(path)
        while p:
            if p in self.origins:
                return self.origins[p]
            p = p[:-1]
        return "?"

    def _set_origins(self, value: Any, path: tuple, origin_of):
        for k in [k for k in self.origins if k[:len(path)] == path]:
            del self.origins[k]
        self.origins[path] = origin_of(path)
        if isinstance(value, dict):
            for k, v in value.items():
                self._set_origins(v, path + (k,), origin_of)

    def set(self, path: tuple, value: Any, origin: str | None = None, origin_of=None):
        node = self.data
        for k in path[:-1]:
            node = node.setdefault(k, {})
            if not isinstance(node, dict):
                raise ConfigError(f"cannot set {'.'.join(map(str, path))}: {k} is not a mapping")
        if value is None:
            node.pop(path[-1], None)
            for k in [k for k in self.origins if k[:len(path)] == path]:
                del self.origins[k]
            self.emptied.add(path)
            return
        node[path[-1]] = copy.deepcopy(value)
        self._set_origins(value, path, origin_of or (lambda p: origin))

    def merge(self, src: dict, doc: YamlDoc, prefix: tuple = ()):
        origin_of = lambda p: str(doc.loc(*p))  # noqa: E731
        for k, v in src.items():
            path = prefix + (k,)
            existing = self.get(*path)
            if v is None:
                self.set(path, None)
                continue
            if prefix == ("parts",) and isinstance(v, dict) and isinstance(existing, dict) \
                    and (CONTENT_KEYS - {"params"}) & set(v):
                kept = {pk: existing[pk] for pk in PLACEMENT_KEYS if pk in existing}
                kept_orig = {pk: self.origin(*path, pk) for pk in kept}
                self.set(path, kept, origin="")
                for pk, o in kept_orig.items():
                    self.origins[path + (pk,)] = o
                self.merge(v, doc, path)
                continue
            if isinstance(v, dict) and isinstance(existing, dict):
                self.merge(v, doc, path)
            else:
                self.set(path, v, origin_of=origin_of)


def load_assembly(project, assembly_id: str) -> tuple[Tree, list[YamlDoc]]:
    chain: list[tuple[str, YamlDoc]] = []
    seen, cur = set(), assembly_id
    while cur:
        if cur in seen:
            raise ConfigError(f"assembly inheritance cycle at {cur}")
        seen.add(cur)
        doc = project.doc(cur, "assemblies")
        data = doc.data or {}
        for k in data:
            if k not in ASSEMBLY_KEYS:
                raise doc.error(f"unknown key {k!r} in an assembly (allowed: {', '.join(sorted(ASSEMBLY_KEYS))})", k)
        for slot, spec in (data.get("parts") or {}).items():
            if spec is None:
                continue
            if not isinstance(spec, dict):
                raise doc.error("a slot must be a mapping (use/type, at, params, optional)", "parts", slot)
            for k in spec:
                if k not in SLOT_KEYS:
                    raise doc.error(f"unknown slot key {k!r} (allowed: {', '.join(sorted(SLOT_KEYS))})",
                                    "parts", slot, k)
            if "use" in spec and "type" in spec:
                raise doc.error("a slot has either 'use' (a part) or 'type' (a part type), not both",
                                "parts", slot)
        chain.append((cur, doc))
        cur = data.get("extends")
    tree = Tree()
    for _, doc in reversed(chain):
        data = {k: v for k, v in (doc.data or {}).items() if k not in ("extends", "description")}
        # a slot set to null must be optional in the parent
        for slot, spec in (data.get("parts") or {}).items():
            if spec is None and tree.get("parts", slot) is not None and not tree.get("parts", slot, "optional"):
                raise doc.error(f"slot {slot!r} is not optional, so it cannot be emptied", "parts", slot)
        tree.merge(data, doc)
    return tree, [d for _, d in chain]
