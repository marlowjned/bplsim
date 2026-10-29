"""Folder locks: O_EXCL lock files with a heartbeat (plan §11.2). A lock whose heartbeat is older than
STALE seconds is taken over (its owner is assumed dead)."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

STALE = 600.0
BEAT = 60.0


def pid_alive(pid: int) -> bool:
    """Whether a process exists on this machine (never signals it; os.kill would terminate on Windows)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259             # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Lock:
    def __init__(self, path: Path, stale: float = STALE, beat: float = BEAT):
        self.path = Path(path)
        self.stale, self.beat = stale, beat
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.held = False

    def _write(self, fd=None):
        info = json.dumps({"host": socket.gethostname(), "pid": os.getpid(), "time": time.time()})
        if fd is not None:
            os.write(fd, info.encode())
            os.close(fd)
        else:
            tmp = self.path.with_suffix(".beat")
            tmp.write_text(info)
            os.replace(tmp, self.path)

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._is_stale():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return False
            self._write(fd)
            self.held = True
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()
            return True
        return False

    def _is_stale(self) -> bool:
        try:
            info = json.loads(self.path.read_text() or "{}")
            if info.get("host") == socket.gethostname() and not pid_alive(int(info.get("pid", 0))):
                return True                                  # owner on this machine is gone
            return time.time() - float(info.get("time", 0)) > self.stale
        except (OSError, ValueError):
            try:
                return time.time() - self.path.stat().st_mtime > self.stale
            except FileNotFoundError:
                return True

    def _heartbeat(self):
        while not self._stop.wait(self.beat):
            try:
                self._write()
            except OSError:
                pass

    def release(self):
        self._stop.set()
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
