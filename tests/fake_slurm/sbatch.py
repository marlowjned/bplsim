"""Stand-in for sbatch in tests: runs every array task of the script now, records states for sacct."""
import json, os, re, subprocess, sys
from pathlib import Path
script = Path(sys.argv[-1])
text = script.read_text()
n = int(re.search(r"--array=0-(\d+)", text).group(1)) + 1
job = str(abs(hash(str(script))) % 100000)
states = {}
for i in range(n):
    env = dict(os.environ, SLURM_ARRAY_TASK_ID=str(i), SLURM_ARRAY_JOB_ID=job)
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    (script.parent / f"slurm-{job}_{i}.out").write_text(r.stdout + r.stderr)
    states[i] = "COMPLETED" if r.returncode == 0 else "FAILED"
(Path(os.environ.get("FAKE_SLURM_DIR", script.parent)) / f"{job}.json").write_text(json.dumps(states))
print(job)
