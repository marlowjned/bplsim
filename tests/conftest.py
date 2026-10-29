from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
HET = FIX / "het_example"
FUNCS = FIX / "funcs"


@pytest.fixture
def het():
    from bplsim.project import Project
    return Project.load(HET)


@pytest.fixture
def data_root(tmp_path):
    return tmp_path / "data"


def run_study(project_dir, study, data_root, executor=None, **kw):
    from bplsim.execute.local import InlineExecutor
    from bplsim.study.driver import Driver
    d = Driver(project_dir, Path(project_dir) / "studies" / study, data_root, executor=executor or InlineExecutor(),
               log=lambda *a: None, **kw)
    return d, d.run()
