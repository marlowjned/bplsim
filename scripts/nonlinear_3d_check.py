"""O1 check: nonlinear 3-D Newton solve of the test design (coarse mesh, finer ramp). About 30 min.
Run from the repo root: .venv/Scripts/python.exe scripts/nonlinear_3d_check.py (needs BPLSIM_TOOL_GETDP)."""
import time, shutil
from pathlib import Path
from bplsim.project import Project
from bplsim.resolve import Resolver, RowSpec
from bplsim.pipeline import load_pipeline
pr = Project.load("tests/fixtures/het_example")
pl = load_pipeline(pr, "het:pipelines/magnetostatics_3d_nl_coarse")
rs = RowSpec(overrides={"op.circuits.inner.current": (2.0, "t"), "op.circuits.outer.current": (1.6, "t")})
d = Resolver(pr, "het:assemblies/bn_screened", rs, fidelity=pl.fidelity_spec()).resolve()
st = pl.stages["mag"]; cfg = st.config(d)
inputs = st.backend.solve_inputs(d, cfg); bases = st.backend.bases(d, cfg, inputs)
w = Path("scratch/g3dnl"); shutil.rmtree(w, ignore_errors=True); w.mkdir(parents=True)
st.backend.prepare(inputs, w)
t = time.time(); r = st.backend.execute(inputs, w, bases[0], {}); print(r.status, r.reason[-300:], round(time.time() - t, 1))
log = (w / "solve_all.log").read_text()
print("\n".join(l for l in log.splitlines() if "ramp step" in l or "Error" in l or "Iterative" in l or "Residual" in l)[-3000:])
