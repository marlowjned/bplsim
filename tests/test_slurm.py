"""The Slurm executor end to end, with stand-in sbatch/squeue/sacct that run the array locally."""
import os
import shutil
import sys
from pathlib import Path

import pytest

from conftest import HET, run_study

FAKE = Path(__file__).parent / "fake_slurm"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash to run the generated batch script")
def test_slurm_executor_runs_study(tmp_path, monkeypatch):
    from bplsim.execute.slurm import SlurmExecutor
    from bplsim.sites import Site
    monkeypatch.setenv("FAKE_SLURM_DIR", str(tmp_path))
    scripts = Path(sys.executable).parent
    monkeypatch.setenv("PATH", str(scripts) + os.pathsep + os.environ["PATH"])
    py = Path(sys.executable).as_posix()
    site = Site(name="fake", executor="slurm",
                slurm={"partition": "debug", "cpus_per_node": 4, "memory_per_node": "8 GB", "poll_s": 0.1,
                       "max_walltime": "01:00:00",
                       "commands": {"sbatch": f"{py} {(FAKE / 'sbatch.py').as_posix()}",
                                    "squeue": f"{py} {(FAKE / 'squeue.py').as_posix()}",
                                    "sacct": f"{py} {(FAKE / 'sacct.py').as_posix()}"}})
    d, s = run_study(HET, "cap_screen_loops.yaml", tmp_path / "data", executor=SlurmExecutor(site))
    assert s["done"] == 12
    sub = next((tmp_path / "data").glob("studies/*/rounds/0/*attempt0/submit.sh")).read_text()
    assert "#SBATCH --array=0-" in sub and "--workers" in sub and "#SBATCH --partition=debug" in sub


def test_packing_rule():
    from bplsim.execute.local import pack, slots
    n = slots(32, 96 * 1024 ** 3, 4, 6 * 1024 ** 3)
    assert n == 8
    sizes = pack(80, n, runtime=360.0, min_task=600.0)
    assert sizes and max(sizes) <= 16 and sum(sizes) == 80           # example §14: 16 rows per task
