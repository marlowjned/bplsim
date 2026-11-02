"""Canonical JSON and content hashes (plan §10)."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np


def quantize(x: float, sig: int = 12) -> float:
    """Round to `sig` significant figures; the rounded value is both used and hashed."""
    if x == 0 or not math.isfinite(x):
        return float(x)
    return float(f"{x:.{sig - 1}e}")


def _canon(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        if not math.isfinite(x):
            raise ValueError(f"cannot hash non-finite value {x}")
        return quantize(x)
    if isinstance(obj, dict):
        return {str(k): _canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_canon(v) for v in obj.tolist()]
    if hasattr(obj, "canonical"):
        return _canon(obj.canonical())
    raise TypeError(f"cannot canonicalise {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"))


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def short(h: str) -> str:
    return h[:12]


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def major_minor(version: str) -> str:
    parts = str(version).split(".")
    return ".".join(parts[:2])
