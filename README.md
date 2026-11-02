# bplsim

The Berkeley Propulsion Laboratory simulation trade framework. Describe a device once, from reusable library
entries (materials, part types, parts, assemblies); ask trade questions as short study files (sweeps and
optimizers); bplsim resolves every design, checks it before solving, runs the simulation tool, measures the
results, caches everything by content hash, and stores it in a database you can query, plot and report from.
Runs on a laptop, on cloud VMs and on Slurm clusters. BPL internal.

Simulation tools behind one interface: 2-D axisymmetric and 3-D magnetostatics (gmsh + GetDP), analytic test
backends, and a WarpX particle-in-cell stage (adapter only, not yet run against real WarpX).

## Install

Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/marlowjned/bplsim.git
cd bplsim
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .        # Windows: .venv\Scripts\python.exe
source .venv/bin/activate                             # Windows: .venv\Scripts\activate
bplsim --help
```

(`python -m venv .venv` and `pip install -e .` work too.) On Linux, gmsh needs a few system libraries:
`sudo apt install libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1`.

The magnetostatics backends need [GetDP](https://getdp.info) 3.5: put it on `PATH`, set
`BPLSIM_TOOL_GETDP=/path/to/getdp`, or name it in your site profile (below).

## Five minutes

```
cd examples/functions
bplsim check                                  # validate the project
bplsim study run studies/branin_grid.yaml     # a sweep over a test function, about 2 s
bplsim study run studies/branin_compass.yaml  # an optimizer on the same function, about 17 s
bplsim study status studies/branin_compass.yaml
bplsim report build reports/summary.md.j2     # numbers and figures from the database
```

Then [`examples/`](examples/README.md): the same commands on a Hall-thruster magnetic circuit with GetDP.

## A project

```
my_project/
  project.yaml            name, namespace, display units, included libraries
  library/                materials, part_types, parts, assemblies, probes, metrics, references,
                          measurements, pipelines, figures   (ids come from paths: ns:folder/name)
  studies/                one YAML per trade question
  reports/                report templates (*.md.j2)
```

`bplsim init my_project` creates the skeleton. Results go to `~/bplsim_data/<project name>/` (or the site's data
root, `--data`, `BPLSIM_DATA`).

## Commands

| | |
|---|---|
| `bplsim check` | validate every entry and assembly; all errors at once, with file:line |
| `bplsim show <assembly>` | resolved values, where each came from, and the design checks |
| `bplsim study plan <study.yaml>` | dry run: which rows are valid, cache hits, cost |
| `bplsim study run <study.yaml> [--site S] [--one-round]` | run or resume a study |
| `bplsim study status <study.yaml>` | progress and results so far |
| `bplsim query "<where>" --metrics a.b,c.d` | results across studies (units allowed: `params.radius <= 17.6 mm`) |
| `bplsim plot <figure id> -o out.png --param k=v` | a registered figure from stored results |
| `bplsim report build reports/x.md.j2` | a report whose numbers and figures come from the database |
| `bplsim collect [--rebuild]` | index result folders into the database |
| `bplsim pin`, `bplsim gc` | keep, or delete, the raw solver output of cases |
| `bplsim sync pull --site S` | fetch finished results from a remote site |
| `bplsim init`, `bplsim lib fork` | new project; copy a library entry into your project to change it |

## Sites

Where things run: `~/.config/bplsim/sites/<name>.yaml` (or `BPLSIM_SITES`). Without `--site`, the `local` profile
is used if it exists. A laptop:

```yaml
name: local
data_root: ~/bplsim_data
executor: local
tools: {getdp: /path/to/getdp}
```

A Slurm cluster (the Slurm executor is tested only with stand-in commands so far):

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

## Documentation

| | |
|---|---|
| [`docs/user_guide.md`](docs/user_guide.md) | the configuration language: every file kind, the rules R1-R11, a complete example project |
| [`examples/`](examples/README.md) | runnable projects |
| [`src/bplsim/README.md`](src/bplsim/README.md) | how the code is organized, with a README per package |
| [`docs/design.md`](docs/design.md) | the architecture |
| [`docs/development.md`](docs/development.md) | developing bplsim: set-up, tests, decisions taken while building, open issues |
