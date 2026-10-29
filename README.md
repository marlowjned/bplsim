# bplsim

The Berkeley Propulsion Laboratory simulation trade framework: define designs from reusable library
entries, run trade studies (DOEs and optimizers) with any simulation tool behind one interface, and store
and query the results. Runs locally, on cloud VMs and on Slurm clusters.

Specification: `HET/docs/TRADE_FRAMEWORK_PLAN.md` (internals) and `HET/docs/TRADE_FRAMEWORK_EXAMPLE.md`
(configuration and use, rules R1-R11). Build status and open decisions: `PROGRESS.md`.

## Install

```
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"     # Linux/macOS: .venv/bin/python
```

GetDP (for `getdp_axisym`) is found through the site profile (`tools: {getdp: <path>}`), the environment
variable `BPLSIM_TOOL_GETDP`, or `PATH`.

## A project

```
my_project/
  project.yaml            name, namespace, display units, included libraries
  library/                materials, part_types, parts, assemblies, probes, metrics, references,
                          measurements, pipelines, figures   (ids come from paths: ns:folder/name)
  studies/                one YAML per trade question
  reports/                report templates (*.md.j2)
```

`bplsim init my_project` creates the skeleton. The HET project lives in `HET/sim/`.

## Commands

| | |
|---|---|
| `bplsim check` | validate every entry and assembly; all errors at once, with file:line |
| `bplsim show <assembly>` | resolved values, where each came from, and the design checks |
| `bplsim study plan <study.yaml>` | dry run: which rows are valid, cache hits, cost |
| `bplsim study run <study.yaml> [--site S] [--one-round]` | run or resume a study |
| `bplsim study status <study.yaml>` | progress and results so far |
| `bplsim query "<where>" --metrics a.b,c.d` | results across studies (units allowed: `radius <= 17.6 mm`) |
| `bplsim plot <figure id> -o out.png --param k=v` | a registered figure from stored results |
| `bplsim report build reports/x.md.j2` | a report whose numbers and figures come from the database |
| `bplsim collect [--rebuild]` | index result folders into the database |
| `bplsim sync pull --site S` | fetch finished results from a remote site |
| `bplsim run-task <task.json>` | the worker entry point used by executors |

## Sites

`~/.config/bplsim/sites/<name>.yaml` (or `BPLSIM_SITES`):

```yaml
name: savio
data_root: /global/scratch/users/<user>/bplsim_data
executor: slurm                 # local | inline | slurm
slurm: {partition: savio3, account: fc_<pi>, cpus_per_node: 32, memory_per_node: 96 GB,
        max_walltime: "72:00:00", max_concurrent_tasks: 20}
container: /global/scratch/users/<user>/images/bplsim.sif
tools: {getdp: /usr/local/bin/getdp}
remote: {host: hpc.brc.berkeley.edu, user: <user>, data_root: /global/scratch/users/<user>/bplsim_data}
```

## Tests

`python -m pytest -m "not slow"` (fast suite, analytic backends); `-m slow` adds subprocess crash tests.
The HET parity tests (GetDP) are in `HET/sim/tests`.
