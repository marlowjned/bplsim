# bplsim design: architecture

**What this is.** The architecture plan bplsim was built from (v0.2, 2026-10-29). Docstrings in the code cite it
as "plan §n". Read it to understand how resolution, measurement, hashing, the driver, execution and the store fit
together.

**Status.** Written before the code. The code follows it; where it departs or fills in details, the decision is
logged in [`development.md`](development.md) (K1-K24), and the package layout is the one in
`src/bplsim/README.md` (module paths here are updated to it). "The example" means [`user_guide.md`](user_guide.md)
("example §n" in docstrings).

---

## 0. Scope and principles

**In scope:** defining designs from reusable library entries; running trade studies (DOEs and optimizers)
with any simulation tool behind a common interface; storing and querying results; running locally,
on cloud VMs and on Slurm clusters.

**Not in scope for v1:**
- a GUI;
- a shared multi-user database server;
- CAD authoring (Fusion stays the design tool; §20);
- automatic mesh-convergence tooling. Fidelity values are parameters (R6), so a convergence study is just
  a study.

**Principles:**
1. **The framework knows nothing about any device.** Device knowledge lives in project libraries.
2. **One definition per thing, referenced by id.** Every dependency is explicit (R1, R3).
3. **Case and run folders are the record.** The database is an index that can be rebuilt from them.
4. **Cache identity = what the solver sees** (R9).
5. **Every unit of work is self-contained, idempotent and atomic.**
6. **SI inside, units only at the edges** (R5).
7. **No configuration through global state:** no environment variables that change model behaviour, no
   import side effects, no module globals patched by other modules.
8. **Every concept must earn its place.** Fewer kinds of thing are better, and nothing is built before
   something needs it.

---

## 1. Glossary

Terms are used with exactly these meanings in the code, configs and docs.

| Term | Meaning |
|---|---|
| **project** | A folder with `project.yaml`, a library and studies. HET is project `het`. |
| **library** | A folder of entries under one **namespace** (`het:`, `std:`). |
| **entry** | One file in a library: material, part type, part, assembly, probe, metric, reference, measurement set, pipeline (R3). |
| **std** | The library shipped with bplsim; device-agnostic entries only. |
| **part type** | Python class: parameters, checks, derived values, geometry, named surfaces, equivalence rules. |
| **part** | YAML: a part type plus parameter values (a real or reused part). |
| **slot** | A named place in an assembly holding one part (or nothing, if optional). |
| **assembly** | YAML: slots, assembly parameters (independent or derived), checks, nominal operating point. |
| **check** | A design-only test with a signed margin; failure makes a row invalid. |
| **operating point** | `op.*`: circuit currents, temperature, and later plasma inputs. |
| **circuit** | A named current source (`op.circuits.inner`); windings attach to circuits. |
| **fidelity** | `fidelity.<stage>.*`: backend accuracy settings, validated by the backend's schema. |
| **pipeline** | YAML: named stages, each with backend, fidelity, equivalence choices, exports, resources. |
| **stage** | One simulation step in a pipeline. |
| **backend** | Adapter for one tool and formulation (`getdp_axisym`, `getdp_3d`, `warpx`, `analytic_loops`). |
| **equivalence rule** | A part type's named 2-D stand-in for non-axisymmetric geometry, with declared validity. |
| **field access** | The interface through which probes read a solution (§7.1). |
| **probe** | Python: where and what to sample; produces probe data. |
| **metric** | Python: numbers from probe data and/or the design. |
| **reference** | Target or measured data a metric compares against (Python if design-dependent). |
| **measurement set** | YAML: probe and metric aliases and how they connect. |
| **alias** | The local name of a probe or metric inside a measurement set or study. |
| **export** | A stage output another stage consumes (e.g. a field map). |
| **study** | YAML: one trade question (design, pipeline, measurements, variables, objectives, sampler). |
| **study variable** | A knob the sampler controls; maps to one or more parameters. |
| **row** | One point in study-variable space. **Round:** rows created together. **Runsheet:** all rows of a study. |
| **pre-screen** | Checks and design-only constraints evaluated before solving; failures are **invalid** rows. |
| **normalization** | Scaling listed values by one factor so a named output hits a target (§8.3). |
| **case** | What a backend solves: identified by the solver-input hash. |
| **basis** | One solve of a case: one per circuit when superposable, otherwise a single one. |
| **run** | A case at one fully resolved input set (weights, normalization, design-only values). |
| **task** | A unit of executor work: a chunk of case and run jobs. |
| **executor** | Where tasks run: `local` or `slurm`. |
| **site** | A machine profile: data root, executor, resources, container. |
| **data root** | Where case folders, run folders and the trade DB live, per site and project. |

---

## 2. Repositories and layout

### 2.1 The bplsim repository

As planned. The build differs (uv instead of pixi, hand-written validation with file:line errors instead of
pydantic, coarser modules): the actual layout is in `src/bplsim/README.md`.

```
bplsim/
├── pyproject.toml, pixi.toml, pixi.lock
├── src/bplsim/
│   ├── __init__.py, __main__.py      version banner (bplsim + loaded library versions)
│   ├── cli/                          typer commands (§13)
│   ├── config/                       project.py, library.py (namespaces, include, fork), loader.py (ruamel.yaml),
│   │                                 schemas/ (pydantic models per YAML kind, study, site, project), vocabulary.py
│   ├── expr/                         evaluator.py (AST whitelist), units.py (pint registry, display units)
│   ├── model/                        parts.py (PartType, Param, Slot, equivalence), materials.py, assembly.py,
│   │                                 resolve.py (row → resolved inputs), trace.py (value origins for `show`)
│   ├── geom/                         rz.py (regions, named edges), cad.py (facade over gmsh OCC), clearance.py
│   ├── backends/                     base.py (Backend, FieldAccess, Capabilities), registry.py,
│   │                                 analytic/, getdp_axisym/, getdp_3d/ (phase 6), warpx/ (phase 7)
│   ├── measure/                      probes.py, metrics.py, references.py, sets.py, combine.py (superposition,
│   │                                 normalization), io.py (HDF5)
│   ├── study/                        spec.py, variables.py, runsheet.py, driver.py, scheduler.py (job graph),
│   │                                 samplers/ (grid, listed, qmc, product, compass, optuna_tpe, optuna_nsga2)
│   ├── execute/                      runtask.py, tasks.py, locks.py, packing.py, sites.py, sync.py,
│   │                                 executors/ (local.py, slurm.py)
│   ├── store/                        schema.sql, db.py, collect.py, query.py, gc.py
│   ├── hashing.py, provenance.py, errors.py
│   └── std/                          the std library, in the same format as any project library
├── tests/
├── containers/                       Dockerfile (built from pixi.lock)
└── docs/
```

`std` is a library folder like any other. bplsim reads it with the same loader it uses for projects, so
the library format gets exercised on every run.

### 2.2 The HET project

The project lives in the HET repository as a folder `sim/` (project name `het`), laid out as in example
§2. Legacy `gmsh_getdp/` stays untouched until phase 4 retires it.

### 2.3 The data root

The data root is `<site data_root>/<project name>/`:

```
trade.db
studies/<study_id>/
    spec.yaml                 frozen copy of the study file
    library_snapshot/         frozen copy of every library the study uses (§11.1)
    runsheet.parquet          append-only
    sampler_state.json
    rounds/<n>/tasks/*.json   frozen task inputs
    logs/
cases/<h[:2]>/<case_hash>/
    case.json                 solve inputs, bases, provenance
    raw/                      backend-native output (purgeable)
    measurements.h5           probe data per probe definition, per basis
    exports/                  stage exports (e.g. field maps)
    status.json, DONE
runs/<h[:2]>/<run_hash>/
    run.json                  resolved inputs, weights, normalization result, provenance
    metrics.json
    status.json, DONE
failed/<hash>/                inputs, logs and raw output of failed jobs
```

**Study ids** take the form `<date>_<study file name>`. Running a study file again *resumes* the existing
study if the spec and library snapshot are unchanged. If either changed, it creates a new study id. Runs are
still reused through the cache.

**No cross-project sharing.** Each project has its own data root. This is deliberate: it keeps one
database per project and avoids coupling between projects.

---

## 3. Library loading and validation

- **Discovery:** `project.yaml` → libraries (std, the project library, includes) → every file in each
  kind's folder becomes an entry (R1–R3). A Python file must define exactly one entry; zero or two is an
  error.
- **YAML:** parsed with **ruamel.yaml**, which keeps line and column numbers. Every error is reported as
  `file:line:col: path: message`.
- **Python entries:** imported under namespace packages (`het.part_types.pole_cap_flat`) by a custom import
  finder rooted at each library. Decorators and base classes register the entry.
- **Schemas:** one pydantic v2 model per YAML kind, plus study, site and project.
  - `bplsim schema export` writes JSON Schemas.
  - `bplsim init` adds the VS Code YAML-extension mapping, so configs get autocompletion and inline errors
    while being written.
- **Vocabulary:** merged across included libraries. Two libraries defining the same alias differently is
  an error.
- **Includes:** a path, or a git URL with a pinned ref, cloned to `~/.cache/bplsim/libs/<name>@<ref>`.
  `bplsim lib fork` copies an entry into the project library (example §16).
- **`bplsim check`** loads everything and reports *all* errors in one pass, not just the first. It covers:
  - schemas;
  - every id reference;
  - every expression, resolving each assembly with its defaults;
  - part checks;
  - the code-entry fingerprints (R8).

---

## 4. Expressions and units

- **Units:** one pint `UnitRegistry` with the project's display units. Strings like `"18 mm"`,
  `"1.7e-7 ohm*m"` and `"20 degC"` are parsed only at load time. Temperatures are stored in K.
- **Evaluator:** the expression body is parsed with Python's `ast` and only whitelisted node types are
  allowed (numbers and strings, names and attribute chains, arithmetic, comparisons, boolean operators,
  conditional expressions, calls to the whitelisted functions). Anything else is a load-time error.
  Python's `eval` is never used.
- **Name resolution:** each name or path is looked up through the resolver, which records a dependency
  edge. That's how the resolution graph (§5) is built.
- **Assignment:** results are quantities with units. On assignment the dimension is checked against the
  target, the value is converted to SI and rounded to 12 significant figures. The rounded value is the
  one used and the one hashed.

---

## 5. Model and resolution

**Objects:**
- **`PartType`**: parameters declared with `Param()` (unit dimension, default, bounds, `needs=` for
  materials).
- **`Slot`**: a typed reference to another slot.
- **`Material`**: resolved properties, with `.at(T)` and similar accessors.
- **`ResolvedInputs`**: immutable and JSON-serialisable in canonical form, plus a **trace** recording the
  origin of every value: `file:line`, `derived: <expr>`, `study variable q`, `override`, or
  `part-type default`.

**Resolving one row** (the algorithm behind example §12):
1. **Structure.** Load the assembly's `extends` chain, merging per R7 with an origin on every node. Then
   apply study `overrides`, then slot choices.
2. **Graph.** Every leaf value is a node. That covers assembly parameters, part parameters, `op`,
   `fidelity`, variable assignments, `sets:` expressions and probe/reference parameters. Each part's
   derived values form one node that depends on all of that part's parameters. Expressions add edges.
3. **Evaluate** in topological order. A cycle is an error that lists the cycle. Bounds (R10) and
   dimensions (R4) are checked on assignment.
4. **Pre-screen:**
   - overlaps and clearances (§6);
   - part checks;
   - assembly checks;
   - constraints on design-only metrics.

   A design-only metric runs once with a recording proxy on `design` and `op`. If it reads a path listed
   in the study's `normalize.scale`, it's deferred until after normalization (§8.3) instead of being
   pre-screened. This is how bplsim knows to defer `power` in example A without being told.
5. **Output:** `ResolvedInputs` + trace + pre-screen result with margins.

`bplsim show <entry>` and `bplsim show <study> --row N` print the result and its trace (example §7).

---

## 6. Geometry

**r–z regions.** `rz.Region` holds:
- a simple polygon in the part's local frame (normalised to counter-clockwise, r ≥ 0);
- a material;
- named surfaces as edge indices;
- an optional excitation (`circuit`, `turns`).

A part's `profile_rz` or chosen equivalence rule returns one or more regions. Placement translates them
by `at` (axial only in v1).

**Overlap and clearance** (R11):
- **Both parts axisymmetric** (each has an exact `profile_rz`): computed on their r–z polygons with
  shapely. This is exact. For two bodies of revolution on the same axis, the closest points always lie in
  a common half-plane, because rotating one point to the other's angle can only shorten the distance.
- **Otherwise:** computed on 3-D solids through gmsh's OpenCASCADE API (`occ.getDistance` for gaps,
  boolean `intersect` + `occ.getMass` for overlap volume). Both are available in gmsh 4.15.2, the version
  installed here.

  A pair involving a non-axisymmetric part that has no `solid_3d` is an error asking for one, or for a
  custom check.

**3-D facade (`bplsim.geom.cad`).** A thin layer over gmsh OCC:
- `cylinder`, `box`, `revolve(rz region)`, `polar_array`, `translate`, `rotate`, `fuse`, `cut`;
- named faces carried as physical groups.

Why gmsh OCC:
- the legacy 3-D model already uses it;
- meshing is gmsh anyway, so there's no STEP round trip.

Part types only use the facade. Swapping in another kernel later (e.g. build123d) touches only
`cad.py`.

---

## 7. Backends

### 7.1 Interface

```python
class Backend(ABC):
    name: ClassVar[str]                        # "getdp_axisym"
    version: ClassVar[str]                     # "1.0.0"; MAJOR.MINOR goes into case hashes
    capabilities: ClassVar[Capabilities]
    Fidelity: ClassVar[type[BaseModel]]        # fidelity schema (units, bounds, defaults)

    def check(self, design, fidelity) -> list[Issue]: ...          # can it represent this design?
    def solve_inputs(self, design, fidelity) -> dict: ...          # canonical; hashed as the case (R9)
    def bases(self, design) -> list[Basis]: ...                    # one per circuit if superposable, else one
    def prepare(self, inputs: dict, workdir: Path) -> None: ...    # mesh, input deck
    def execute(self, workdir: Path, basis: Basis, res: Resources) -> ExecResult: ...
    def field_access(self, workdir: Path, basis: Basis) -> FieldAccess: ...


class FieldAccess(ABC):
    symmetry: str                                                  # "axisymmetric" | "none"
    fields: set[str]                                               # {"B", "H"}; later plasma fields

    def sample(self, where, fields) -> Dataset: ...                # points or parametric grid, global (r, theta, z)
    def region(self, part: str, fields) -> Dataset: ...            # element centroids, volume weights, values
    def boundary(self, surface: str, fields) -> Dataset: ...       # facet centroids, normals, areas, values
    def export_grid(self, grid, fields, fmt) -> Path: ...
```

```python
@dataclass(frozen=True)
class Capabilities:
    dims: int                                  # 2 or 3
    symmetry: str                              # "axisymmetric" | "none"
    superposable_in: tuple[str, ...]           # op paths it is linear in when fidelity is linear
    consumes: tuple[str, ...]                  # export kinds it needs from upstream stages
    restartable: bool
```

- `ExecResult` is `ok`, `failed(reason)` or `incomplete(restart_token)`.
- A backend never writes anything except into the `workdir` it was given.
- `prepare` is where part types' geometry is turned into a mesh, so it runs in the worker using the
  library snapshot (§11.1).

### 7.2 Superposition

When the fidelity is linear and the backend declares `superposable_in` for the circuit currents:
- each **basis** is one circuit at 1 A, with the windings' turns included in the solve;
- the case solves every basis once;
- a run's weights are its circuit currents (after normalization), and its probe data is the weighted sum
  of the basis data.

Otherwise there's one basis, and its weight is 1.

### 7.3 GetDP axisymmetric (phase 3, port of `gmsh_getdp/axisym`)

- **prepare:**
  - regions from `profile_rz` and the chosen equivalence rules;
  - a gmsh 2-D mesh with one physical group per (part, material) and per named surface;
  - a generated `regions.pro` (μ per region, current density per winding region from turns ÷ area);
  - the formulation, ported from `axisym.pro`.
- **execute:** `getdp -solve` once per basis. The solution file is kept for field access.
- **field access:** evaluated by **GetDP itself** on the stored solution, so values are computed exactly as
  in the legacy code:
  - parametric grids (lines, rings, r–z grids) → `OnGrid` with parametric expressions, which is how the
    legacy channel grid works;
  - small point sets → generated `OnPoint` blocks;
  - regions → `OnElementsOf <part group> Depth 0`, plus element areas from the mesh (weight 2πr·A, as the
    legacy `_elem_weights`);
  - boundaries → `OnElementsOf <surface group> Depth 0`, plus facet normals and lengths from the mesh.

  v1 makes one GetDP post-processing call per request. That's a few seconds per 2-D case, against about
  15 s for today's full geometry. Batching requests is an optimisation to make only if profiling shows a
  need.

### 7.4 GetDP 3-D (phase 6, port of `gmsh_getdp/assembly`)

The same structure:
- geometry through the `cad` facade;
- the legacy 3-D formulation;
- Newton for nonlinear iron;
- iterative normalization (§8.3).

### 7.5 Analytic backends (built in; phase 2)

These let the framework be tested without GetDP:
- **`analytic_functions`:** standard optimizer test functions (Rosenbrock, Branin, a constrained
  Rosenbrock, ZDT1). Each study variable maps to a function argument, and a trivial probe returns the
  value.
- **`analytic_loops`:** winding regions become coaxial current loops, with B in closed form using
  `scipy.special.ellipk`/`ellipe`. Magnetic materials are ignored (air core).
  - It implements the full field-access interface: regions and boundaries are evaluated on a
    triangulation of the parts' r–z profiles.
  - It is superposable.
  - It runs in microseconds. It exercises every layer, and it's the synthetic solution `bplsim check`
    uses for fingerprints (R8).
- **`analytic_flaky`:** wraps another backend and injects failures, timeouts and crashes on purpose, to
  test execution.

### 7.6 Later backends

- **WarpX** (phase 7): consumes `fieldmap` exports (openPMD), restartable.
- **"Template" backend** (render input files, run a command, parse outputs): deliberately not scheduled.
  It gets built when a second simple tool actually needs it (principle 8).

---

## 8. Measurement, normalization and storage

### 8.1 Measure step (in the worker, after execute)

The probes to run are those in the study's measurement set, plus the pipeline's exports, plus exports for
pinned rows. For each one:
- **probe definition hash** = H(probe id, `MAJOR.MINOR`, resolved parameters);
- if `measurements.h5` already holds that hash for the case, it's skipped;
- otherwise the probe is evaluated per basis through field access and written.

Probe data is an xarray Dataset in SI units, with attributes recording the symmetry and the probe id and
version.

### 8.2 Combine

At run level, combined data = Σ (weight × basis data) for the field variables; coordinates are shared.
Combining is cheap and is done on read. That's why run folders hold no probe data, only inputs, weights
and metrics.

### 8.3 Normalization

`normalize` (example §12) finds the factor k so that `so_that.value(k) = equals`:
- **superposed cases:** the combined data is linear in k, so k is found by Brent's method on combine.
  There are no extra solves, and any monotone output works, not just ones proportional to k;
- **nonlinear cases** (phase 6): a secant iteration on k. Each iteration is a new case, with a default
  tolerance of 0.1 % and at most 6 iterations. The run records k and the iteration cases.

The normalized values are stored as `normalized.<path>`. Metrics that read them run after normalization
(§5 step 4).

### 8.4 Metrics

Metrics are evaluated at run level after combine and normalization: the design-only ones and those fed by
probes. `metrics.json` maps `alias.output` → {value, unit, metric id, version, definition hash}.

### 8.5 File formats

| File | Format |
|---|---|
| `measurements.h5` | HDF5 via h5netcdf/xarray: group per probe definition hash, subgroup per basis; attributes: probe id, version, parameters (JSON), alias at first use |
| exports | their own files (openPMD HDF5 for field maps), listed in `case.json` |
| `case.json`, `run.json`, `metrics.json`, `status.json` | JSON |
| `runsheet.parquet` | Parquet (typed columns); `bplsim runsheet export` writes CSV |

### 8.6 Remeasure and staleness

- **`bplsim remeasure <selector>`** fills in missing probe definitions. It uses raw data if it's
  retained; otherwise it needs a re-solve, which only happens with `--resolve`.
- **Probe or metric version change:** a `MAJOR.MINOR` bump marks stored values `stale` in the database.
  - `bplsim metrics recompute` recomputes metrics from stored probe data.
  - Probe changes need `remeasure`.

---

## 9. Studies, samplers and the driver

### 9.1 Spec

The study spec has these fields (examples §12–13):
- `description`, `production`, `design`, `pipeline`;
- `measure {use, add}`, `overrides`, `variables`, `normalize`;
- `objectives`, `constraints`, `sampler`, `budget`, `retention`, `pin`.

**Where it runs isn't part of the study**: that comes from the site and the command line.

### 9.2 Variables

| Form | Values | Sampler encoding |
|---|---|---|
| `param` + `range` | continuous or int (from the parameter's type) | [0, 1]; log-transformed if `scale: log` |
| `param` + `values` | discrete list | ordinal |
| `slot`/`param` + `choices` | parts, materials, or `none` | categorical |
| `range` + `sets` | a knob that writes parameters through expressions | as `range` |

### 9.3 Sampler interface

```python
class Sampler(ABC):
    def ask(self, n: int | None) -> list[dict]: ...           # study-variable values; None = sampler decides
    def tell(self, results: list[RowResult]) -> None: ...      # objectives, constraint margins, status
    def finished(self) -> bool: ...
    def state(self) -> dict: ...                               # JSON; with DB history it restores the sampler
    @classmethod
    def restore(cls, spec, state, history) -> "Sampler": ...
```

- **v1 samplers:** `grid`, `list` (inline or CSV), `sobol`, `lhs`, `product` (composition), `compass` (port
  of the legacy `pattern_search` with its step schedule), `optuna_tpe`, `optuna_nsga2`. CMA-ES and BoTorch
  get added when a study needs them.
- **Invalid and failed rows** are told to the sampler as infeasible, with margins where available.
- **Optuna** keeps no storage of its own. History is replayed into an in-memory study on restore, so the
  bplsim database is the only record.

### 9.4 Budget

`runs` (solved rows), `max_invalid`, `max_rounds`, `wall_time`. Whichever is hit first ends the study.

### 9.5 Driver and job graph

`bplsim study run <study> [--site S] [--one-round]` creates or resumes a study, then repeats:

```
ask → resolve + pre-screen + hash → append to runsheet → build job graph → submit ready jobs
    → wait → collect → tell → save state
```

until the sampler is finished or the budget is spent.

- **Job graph:**
  - **case jobs:** prepare, execute and measure;
  - **run jobs:** combine, normalize and metrics. Each depends on its case job;
  - **downstream-stage case jobs** depend on their upstream run jobs.

  Run jobs that are known when a task is built go into the same task as their case. Run jobs added
  later, against an existing case, are cheap and run in the driver.
- **Modes:**
  - `sync`: rounds. Reproducible. The default, and required by `compass`.
  - `async`: keeps K jobs in flight and asks for a new point whenever one finishes. Optuna treats
    running trials as pending. Point *choice* then depends on timing, but each result never does.
- **`--one-round`:** does one iteration and exits, so the driver never has to run for long on a login node.

### 9.6 Results

Objectives and constraints give each run `feasible` (bool) and objective values. The Pareto front for
multiple objectives is computed by `bplsim query --pareto` and by figures.

### 9.7 Dry run

`bplsim study plan <study>` resolves the first round (or the whole DOE) and pre-screens it, and reports:
- counts of valid and invalid rows, and which checks failed;
- cache hits;
- estimated cost (runtime hints or database timings) and the task packing.

It solves nothing. Every study should be planned before it runs.

---

## 10. Hashing and provenance

- **Canonical JSON:** sorted keys, SI floats in shortest round-trip form after quantisation, no NaN or
  Inf. Hashed with SHA-256; 12 hex characters for display.
- **Case hash** = backend name + `MAJOR.MINOR` + `solve_inputs` + basis list + upstream run hashes.
- **Run hash** = case hash + canonical resolved inputs + normalization spec + stage.
- **Probe and metric definition hashes:** as in §8.1 and §8.4.
- **Provenance** in `run.json` and `case.json`:
  - bplsim version;
  - project git commit, dirty flag and diff hash;
  - library snapshot hash and the versions of the entries used;
  - tool versions (`getdp --version`, gmsh);
  - container image digest, host, user, timestamps, wall and CPU time.

---

## 11. Execution

### 11.1 Library snapshot

Workers need the project's code (part types, probes, metrics) as well as its data.
- When a study is created, every library it uses is copied into `studies/<id>/library_snapshot/`. That's
  small: code, YAML and tables.
- Workers import from the snapshot, never from a working copy. A cluster therefore doesn't need the repo
  checked out at the right commit.
- If the working library later differs from the snapshot, `study run` says so. `--refresh-snapshot`
  starts a new study id, and the cache still reuses unchanged solves.

### 11.2 `bplsim run-task <task.json> [--jobs 0-15] [--data ROOT]`

The task file lists fully resolved jobs. Workers never re-resolve studies. For each job:
1. If `DONE` exists, skip it.
2. Take the lock: `<hash>.lock`, created with `O_EXCL` and holding host, pid and a heartbeat that a
   thread refreshes every 60 s. A lock with no heartbeat for 10 minutes is stale and gets taken over.
3. Work in `<hash>.tmp-<host>-<pid>/`, write `status.json` and `DONE`, rename the folder into place
   (atomic on one filesystem), release the lock.
4. On error, write a classified `status.json` and copy inputs, logs and raw output to `failed/<hash>/`.

| Class | Meaning | Retry |
|---|---|---|
| `invalid` | failed pre-screen | never submitted |
| `failed` | the tool reported an error or didn't converge | no (deterministic) |
| `timeout` | exceeded the per-job timeout | once, with twice the timeout |
| `crashed` | stale lock / no status (node lost, spot VM reclaimed) | once |
| `incomplete` | walltime reached, restartable | resubmit up to 10 times |

### 11.3 Executors

- **`local`:** a process pool started with `spawn`. Slots come from the packing rule using the machine's
  cores and memory. `OMP_NUM_THREADS` and similar are set to the job's cores. Used on the laptop (WSL2)
  and on cloud VMs.
- **`slurm`:** renders an `sbatch` script from the site profile:
  - `--array=0-(T-1)%max_concurrent`, cores, memory, time, partition and account;
  - `apptainer exec <image> bplsim run-task …`;
  - downstream stages chained with `--dependency=afterok`.

  `wait()` polls `squeue`/`sacct` and the `DONE` markers.
- **Packing:** the rule and worked numbers are in example §14.

### 11.4 Sites, sync and environment

- **Site profiles:** example §14.
- **Sync:** `bplsim sync pull|push --site S [--study X] [--with-raw]` copies case and run folders with
  rsync (without `raw/` by default), then `bplsim collect` indexes them. Nothing needs merging, because
  folders are the record.
- **Environment:** pixi with a lockfile; the same environment in WSL2, CI and the container.
  - Python 3.12.
  - gmsh 4.15.x, the same series as the legacy install, from conda-forge.
  - numpy, scipy, pint, pydantic, ruamel.yaml, shapely, xarray, h5netcdf, pandas, pyarrow, optuna,
    typer, rich.
  - **GetDP 3.5.0 for Linux** (the same version as the legacy Windows build), fetched by a pixi task.
- **Container:** a Dockerfile built from the lockfile and pushed to GHCR; pulled with `apptainer pull` on
  clusters. The image digest is recorded in provenance.

---

## 12. Store (SQLite, WAL mode; written only by `collect` and the driver)

```sql
studies(study_id PK, spec_path, spec_hash, spec_yaml, snapshot_hash, created, bplsim_version,
        project_commit, production)
rows(study_id, row_id, round, origin, status, invalid_reason, PRIMARY KEY (study_id, row_id))
row_values(study_id, row_id, name, value_num, value_text, unit)              -- study-variable space
row_runs(study_id, row_id, stage, run_id)
cases(case_id PK, backend, backend_version, status, path, host, started, finished,
      wall_s, cpu_s, raw_retained, provenance_json)
runs(run_id PK, case_id, stage, status, error, path, normalized_json, feasible, provenance_json)
params(run_id, path, value_num, value_text, unit, origin, PRIMARY KEY (run_id, path))   -- parameter space
metrics(run_id, alias, output, definition_hash, metric_id, metric_version, value_num, value_text,
        unit, stale, PRIMARY KEY (run_id, alias, output, definition_hash))
pins(run_id PK), tags(run_id, tag)
```

- **Units** are stored as SI unit strings.
- **Long tables** mean new parameters, metrics and backends never need a schema migration. A wide view
  is generated per study.
- **`bplsim collect [--rebuild]`** is idempotent; `--rebuild` recreates the database from the folders.
- **Query** returns a wide DataFrame. The `where` string uses the expression language (R4), and units in
  it are parsed:

```python
bplsim.query(where="parts.pole_cap.radius <= 17.6 mm and parts.inner_screen", metrics=["misfit.rms_pct"])
```

---

## 13. Command line (v1)

| Command | Purpose | Phase |
|---|---|---|
| `bplsim --version` | bplsim and loaded library versions | 0 |
| `bplsim init <dir>` | new project skeleton + editor schema mapping | 1 |
| `bplsim check` | validate everything; code-entry fingerprints | 1 |
| `bplsim show <entry>` / `show <study> --row N` | resolved values with origins; check margins | 1 |
| `bplsim schema export` | JSON Schemas for editors | 1 |
| `bplsim lib fork <id> --into <ns>` | fork an entry | 1 |
| `bplsim study plan <study>` | dry run: pre-screen, cache hits, cost, packing | 2 |
| `bplsim study run <study> [--site] [--one-round] [--refresh-snapshot]` | run or resume | 2 |
| `bplsim study status <study>` | progress, failures, best so far | 2 |
| `bplsim run-task <task>` | worker entry point (used by executors) | 2 |
| `bplsim collect [--rebuild]` | index folders into the database | 2 |
| `bplsim query "<where>" [--metrics …] [--pareto] [--out file]` | results as a table | 2 |
| `bplsim remeasure <selector> [--resolve]`, `bplsim metrics recompute` | fill or refresh results | 2 |
| `bplsim pin`, `bplsim gc` | retention | 2 |
| `bplsim sync pull/push --site` | move folders between sites | 5 |
| `bplsim plot <figure>`, `bplsim report build <spec>` | figures and reports | 4 |

---

## 14. Reporting (phase 4)

- **Figures** are registered functions (`@figure`) whose inputs are a query result plus probe data. They
  never read from a study script.
- **Reports** are markdown templates whose numbers come from tags (`{{ value("study", "misfit.rms_pct",
  "%", ".2f") }}`), so the text can't drift from the data. `bplsim report build` regenerates figures and
  text.
- Figures share one style module.

Today's report figures (channel profiles, field maps, dimensioned sections, sweeps) are the first figures
ported.

---

## 15. Testing

| Layer | Tests |
|---|---|
| Config | every schema; every error message includes `file:line`; inheritance, merge and slot-replacement rules; vocabulary conflicts |
| Expressions and units | whitelist enforcement; units of literals; the zero rule; null guards; cycles; dimension mismatches |
| Resolution | example §7 `show` values reproduced exactly; example §12 runsheet pre-screen outcomes reproduced |
| Geometry | r–z clearance against hand-computed cases; the axisymmetric/3-D paths agree on coaxial parts |
| Hashing | golden hashes; key-order independence; quantisation; a temperature-only change keeps the case hash |
| Samplers | each finds known optima on `analytic_functions` within tolerance and budget (fixed seeds); constrained optimum on the boundary; NSGA-II hypervolume on ZDT1; compass solves an `analytic_loops` inverse problem |
| Driver | kill and resume gives no duplicate solves and the same answer as an uninterrupted run; two studies sharing points solve once; async mode completes |
| Execution | `analytic_flaky`: every failure class and retry rule; stale-lock takeover; atomic rename |
| Store | collect is idempotent; rebuild matches; queries handle units |
| Fingerprints | `bplsim check` in CI |
| **Parity with legacy** (phase 3) | the regression targets in §17 phase 3 |

CI runs GitHub Actions on Linux with the pixi environment. GetDP parity tests are marked `slow` and run
on demand and before any GetDP backend version bump.

---

## 16. Dependencies

| Need | Choice | Why |
|---|---|---|
| Schemas | pydantic v2 | validation, discriminated unions, JSON Schema export |
| YAML | ruamel.yaml | line and column numbers in errors |
| Units | pint | only at load, display and assignment; never in solver or metric loops |
| 2-D geometry | shapely | exact r–z distances and overlaps |
| 3-D geometry, meshing | gmsh (OCC) | already used; has distance and boolean operations |
| Arrays, data | numpy, scipy, xarray, h5netcdf | probe data; elliptic integrals for `analytic_loops` |
| Tables | pandas, pyarrow | queries; runsheet Parquet |
| Optimizers | optuna, scipy.stats.qmc, own compass | TPE, NSGA-II; Sobol, LHS |
| CLI, output | typer, rich | |
| Templates | jinja2 | reports (phase 4) |
| Field maps | openpmd-api | WarpX input (phase 7) |
| Environment | pixi | locked, conda-forge |

**Rejected:**
- **Hydra/OmegaConf:** its working-directory and override model conflicts with frozen inputs.
- **signac:** one-level state points don't fit cases, runs and stages.
- **MLflow:** too heavy.

---

## 17. Phases

| Phase | Content | Done when |
|---|---|---|
| **0. Groundwork** | repository (§21 Q1), pixi env, CI, Dockerfile, GetDP and gmsh in WSL2 | `bplsim --version` and `getdp --version` work in WSL2 and CI |
| **1. Config and model** | loader, schemas, expressions and units, materials, part types, parts, assemblies, resolution and trace, r–z geometry, clearances, `check`, `show`, `init`, `schema export` | the example's library (written as test fixtures) loads; `show` reproduces example §7 exactly; seeded errors give `file:line` messages |
| **2. Measurement and execution core** | field access, probes, metrics, references, measurement sets, superposition, normalization, hashing, folders, run-task, local executor, store, collect, query, samplers, driver (sync and async), `study plan/run/status`, analytic backends | all §15 tests except parity pass |
| **3. GetDP 2-D and the HET library** | `getdp_axisym` backend; `het` part types, probes and metrics matching the legacy definitions; real Design A and Design B and the old-channel target design as assemblies | parity targets met (below) |
| **4. Studies, figures, reports** | port each legacy study as a spec; figure registry and reports; move `gmsh_getdp/axisym` scripts to `legacy/`; remove `AXISYM_CONFIG` | each legacy report's headline numbers reproduced by a spec + report build |
| **5. Remote execution** | Slurm executor, sites, sync, container on GHCR; tested on a single-node Slurm container, then a cloud VM or Savio | a study runs end to end through Slurm and syncs back |
| **6. 3-D** | `cad` facade; `getdp_3d` backend (port of `gmsh_getdp/assembly`); nonlinear normalization | Design A cross-checked 2-D vs 3-D on the angle-averaged profile; 3-D parity with the legacy 3-D results |
| **7. WarpX** | `warpx` backend consuming field-map exports; restartable jobs | a magnetostatics → PIC chain runs |

**Phase 3 parity targets** (to confirm, §21 Q2):
- **Design A** (screened, stock tubes; `results/bn/search_stock_stock.json`): misfit 1.17 %, B_r at the
  anode 1.7 %, 1.57 W at 165 G, 0.91 / 0.72 A.
- **Design B** (shieldless, coils forward; `results/bn_noshield/best.json` without `ring_gap`): misfit
  1.60 %.
- **Old-channel target design** (`TARGET_REPORT.md`, flat cap + gap 21): misfit 3.0 %, σ 12.4 mm.

**Tolerance:** the new backend meshes the same geometry differently, so exact equality isn't expected.
Phase 3 starts by measuring the **legacy code's own mesh sensitivity** (re-solving with ±20 % mesh size).
The tolerance is then set to that spread, with defaults of 1 % relative and 0.1 percentage points for
%-quantities if the spread is smaller. That way the tolerance comes from data, not a guess.

**This week:** phases 0–2, starting phase 3.

---

## 18. Decision log

| # | Decision |
|---|---|
| D1 | bplsim is device-agnostic; device knowledge lives in project libraries; `std` holds only device-agnostic entries |
| D2 | Ids from paths; entry kinds by folder; one entry per file (R1–R3) |
| D3 | One expression syntax `"${ … }"`, whitelisted AST, evaluated with units (R4) |
| D4 | Display units per dimension, driven by schemas; SI inside (R5) |
| D5 | Four reserved parameter roots (R6); only independent values can be swept (R10) |
| D6 | Inheritance merge rules; named dictionaries for anything extended item by item (R7) |
| D7 | Version strings on code entries, with fingerprint enforcement; no versions on data entries (R8) |
| D8 | Case hash = solver inputs; run hash = case + full inputs + normalization (R9) |
| D9 | Automatic overlap checks; explicit minimum gaps per pair (R11); exact r–z clearance for axisymmetric pairs, OCC for the rest |
| D10 | Field access is the only backend surface probes see; GetDP evaluates its own solution |
| D11 | Superposition per circuit basis; normalization by root-finding on combine (linear) or iterative solves (nonlinear) |
| D12 | Probe data stored per case and basis; runs hold weights and metrics; combine on read |
| D13 | Studies compose library entries; execution settings come from sites, not studies |
| D14 | Batch ask/tell samplers; sync (default) and async modes; the database is the only optimizer record |
| D15 | Library snapshot per study; workers never read the working copy |
| D16 | Run-task on frozen jobs; `O_EXCL` locks with heartbeat; atomic rename; classified failures |
| D17 | Case and run folders are the record; SQLite is a rebuildable index; long tables |
| D18 | Executors: local and Slurm; VMs use local; packing rule by cores and memory |
| D19 | pixi + WSL2 + Docker/Apptainer; GetDP 3.5.0 and gmsh 4.15.x pinned to match legacy |
| D20 | 3-D geometry through a facade over gmsh OCC; kernel swappable later |
| D21 | Nothing is built before something needs it (template backend, CMA-ES and BoTorch wait for a user) |

---

## 19. Risks

| Risk | Mitigation |
|---|---|
| GetDP post-processing per request is slow in 3-D | measure in phase 6; batch requests into one PostOperation if needed |
| Parity misses because of mesh differences | tolerance from measured legacy mesh sensitivity (§17) |
| Slow file access across the WSL2 boundary | data root and repos on the WSL ext4 filesystem |
| Async optimizer results not reproducible | sync is the default; async is opt-in and documented |
| Python entries in libraries can do anything | expected: libraries are trusted project code; YAML expressions stay whitelisted |
| `occ.getDistance` behaviour on complex solids | v1 non-axisymmetric parts are simple (cylinders, revolves); tested against analytic distances |

---

## 20. Geometry sub-project (after phase 6)

Scope:
- general placement (full transforms);
- a Fusion workflow: STEP export → measure named features → compare against resolved values, with a
  per-value verdict;
- whether build123d should replace gmsh OCC behind the facade.

Until then, part types build geometry in code and Fusion remains the detailed-design tool.

---

## 21. Open questions

1. **Where does the bplsim code live?** A separate repository (recommended), or inside the HET repository
   for now?
2. **Parity targets:** are the three designs and the tolerance method in §17 right?
3. **Other users:** will other BPL members use bplsim in the next few months, and on what machines?
4. **Scope of the first push:** phases 0–4 (2-D complete, legacy retired) before 3-D?

---

## Appendix A: changes from v0.1

- **Framework/project split:** components, probes and metrics moved out of the framework into project
  libraries (D1). `std` was added.
- **Design model:** "components" replaced by part types / parts / assemblies. Materials are free-form and
  wire is a material. Constraints became checks with per-pair minimums.
- **Paths:** `design.*` became `params.*`, `parts.*`, `op.*`, `fidelity.*`.
- **Hashing:** "hash the resolved design + integer adapter versions" became "hash what the solver sees +
  semver strings with fingerprint checks".
- **Products:** "products defined per backend" became field access + probe scripts. Probe data is stored
  per case and basis and combined on read.
- **Normalization:** new (§8.3); matches how legacy trades compare designs.
- **Studies:** compose library entries; goals removed; execution settings moved to sites; dry-run
  `study plan` added.
- **Execution:** the library snapshot (§11.1) closes a gap in v0.1, where workers needed the project's
  code but nothing provided it. The packing rule replaces the contradictory chunking text.
- **Repository:** the template backend is unscheduled; Optuna's own storage isn't used; reports moved to
  phase 4.
- **Phases:** reordered; each has a measurable "done when"; parity targets named.
