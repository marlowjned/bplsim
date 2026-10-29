"""Move case and run folders between sites (plan §11.4) with ssh + tar (available on Linux, macOS and
Windows 10+). Only finished folders that the destination lacks are copied; raw solver output is left
behind unless --with-raw. Afterwards `bplsim collect` indexes them; nothing needs merging.

Site profile:
    remote: {host: savio.brc.berkeley.edu, user: me, data_root: /global/scratch/users/me/bplsim_data}
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import ConfigError


def _ssh(remote: dict) -> list[str]:
    host = remote["host"]
    user = remote.get("user")
    return ["ssh", f"{user}@{host}" if user else host]


def _remote_done(remote: dict, root: str) -> set[str]:
    cmd = _ssh(remote) + [f"cd '{root}' 2>/dev/null && find cases runs -mindepth 3 -maxdepth 3 -name DONE"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise ConfigError(f"ssh failed: {r.stderr.strip()}")
    return {str(Path(line.strip()).parent.as_posix()) for line in r.stdout.splitlines() if line.strip()}


def _local_done(root: Path) -> set[str]:
    return {p.parent.relative_to(root).as_posix() for p in root.glob("cases/*/*/DONE")} | \
        {p.parent.relative_to(root).as_posix() for p in root.glob("runs/*/*/DONE")}


def pull(site, project_name: str, local_root: Path, with_raw: bool = False, study: str | None = None) -> int:
    remote = site.remote if hasattr(site, "remote") else None
    if not remote:
        raise ConfigError(f"site {site.name} has no 'remote' (host, user, data_root)")
    rroot = f"{remote['data_root'].rstrip('/')}/{project_name}"
    local_root.mkdir(parents=True, exist_ok=True)
    todo = sorted(_remote_done(remote, rroot) - _local_done(local_root))
    if study:
        todo += [f"studies/{study}"]
    if not todo:
        return 0
    excl = [] if with_raw else ["--exclude=*/raw"]
    listing = "\n".join(todo)
    tar_remote = _ssh(remote) + [f"cd '{rroot}' && tar -cf - {' '.join(excl)} -T -"]
    p1 = subprocess.Popen(tar_remote, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["tar", "-xf", "-", "-C", str(local_root)], stdin=p1.stdout)
    p1.stdin.write(listing.encode())
    p1.stdin.close()
    p2.wait()
    p1.wait()
    if p1.returncode or p2.returncode:
        raise ConfigError("sync failed (ssh or tar returned an error)")
    return len(todo)


def push(site, project_name: str, local_root: Path, paths: list[str]) -> int:
    remote = site.remote if hasattr(site, "remote") else None
    if not remote:
        raise ConfigError(f"site {site.name} has no 'remote'")
    rroot = f"{remote['data_root'].rstrip('/')}/{project_name}"
    p1 = subprocess.Popen(["tar", "-cf", "-", "-C", str(local_root), *paths], stdout=subprocess.PIPE)
    p2 = subprocess.Popen(_ssh(remote) + [f"mkdir -p '{rroot}' && tar -xf - -C '{rroot}'"], stdin=p1.stdout)
    p2.wait()
    p1.wait()
    return len(paths)
