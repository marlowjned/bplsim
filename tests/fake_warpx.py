"""Stand-in for the WarpX executable (tests): reads the rendered deck, checks the external field file,
writes an openPMD field diagnostic (the applied B, scaled) and a reduced diagnostic."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bplsim.measure.openpmd import read_field, write_field  # noqa: E402

deck = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    line = line.split("#", 1)[0].strip()
    if "=" in line:
        k, v = line.split("=", 1)
        deck[k.strip()] = v.strip()
axes, comps = read_field(deck["warpx.read_fields_from_path"], "B")
steps = int(deck["max_step"])
out = Path("diags/diag1")
out.mkdir(parents=True, exist_ok=True)
b = np.stack([comps["r"], comps["t"], comps["z"]], axis=-1)
write_field(out / f"openpmd_{steps:06d}.h5", axes, {"B": b}, iteration=steps)
red = Path("diags/reducedfiles")
red.mkdir(parents=True, exist_ok=True)
peak = float(np.max(np.abs(comps["r"])))
(red / "energy.txt").write_text("#[0]step() [1]time(s) [2]total(J) [3]peakBr(T)\n"
                                f"{steps} 1e-6 {1e-3 * steps} {peak}\n")
print("fake warpx done")
