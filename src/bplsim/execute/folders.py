"""Data-root layout (plan §2.3)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


class DataRoot:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def case_dir(self, h: str) -> Path:
        return self.root / "cases" / h[:2] / h

    def run_dir(self, h: str) -> Path:
        return self.root / "runs" / h[:2] / h

    def failed_dir(self, h: str) -> Path:
        return self.root / "failed" / h

    def study_dir(self, study_id: str) -> Path:
        return self.root / "studies" / study_id

    @property
    def db_path(self) -> Path:
        return self.root / "trade.db"

    def done(self, d: Path) -> bool:
        return (d / "DONE").exists()


def write_json(path: Path, obj) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_default))
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(Path(path).read_text())


def _default(o):
    import numpy as np
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "canonical"):
        return o.canonical()
    return str(o)


def publish(tmp: Path, final: Path) -> bool:
    """Atomically move a finished temporary folder into place. False if another worker won the race."""
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        if (final / "DONE").exists():
            shutil.rmtree(tmp, ignore_errors=True)
            return False
        shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    return True
