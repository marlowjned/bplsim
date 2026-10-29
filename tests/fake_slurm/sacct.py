import json, os, sys
from pathlib import Path
job = sys.argv[sys.argv.index("-j") + 1]
for f in Path(os.environ["FAKE_SLURM_DIR"]).glob(f"{job}.json"):
    for i, st in json.loads(f.read_text()).items():
        print(f"{job}_{i}|{st}")
