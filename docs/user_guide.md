# bplsim user guide: configuring and using a project

**What this is.** The configuration specification bplsim was built from (v0.3, 2026-10-29), told through one
example project, a Hall-effect thruster (namespace `het`). It shows where each thing is defined: materials, part
types, parts, assemblies, probes, metrics, references, measurement sets, pipelines, studies and sites, and the
rules R1-R11 that apply everywhere.

**Status.** It was written before the code and the code implements it. Runnable versions of most files shown here
are in `examples/magnet/` (the same magnetic circuit) and `tests/fixtures/het_example/`; where this document and
those files or the code differ, the files and the code are right. Decisions taken while building are in
`development.md` (K1-K24). Numbers quoted for the HET design are illustrative. Mentions of `report_figs.py`,
`gmsh_getdp/` and `BN_REPORT.md` refer to the HET repository's legacy tools.

Companion: [`design.md`](design.md) (the framework's internals; "plan §n" in the code's docstrings).

---

## 1. Rules that apply everywhere

**R1. Ids come from file paths.** An entry's id is `<namespace>:<folder>/<file name without extension>`,
e.g. `library/materials/a36.yaml` → `het:materials/a36`. Files never repeat their own id.

**R2. One entry per file.** Python files whose names start with `_` are shared helpers, not entries.
A library can be imported as a Python package under its namespace (`import het.part_types._winding`).

**R3. Kinds of entry.** The folder decides the kind:

| Folder | Kind | Format | Holds |
|---|---|---|---|
| `materials/` | material | YAML | named properties with units, open-ended (wire is a material too, §4) |
| `part_types/` | part type | Python | parameter schema, local checks, derived values, geometry, named surfaces, equivalence rules |
| `parts/` | part | YAML | a part type plus parameter values: a real or reused part |
| `assemblies/` | assembly | YAML | slots filled with parts, placement, assembly parameters, checks, nominal operating point |
| `probes/` | probe | Python | where and what to measure, as a request on the solution |
| `metrics/` | metric | Python | numbers computed from probe data and/or the design |
| `references/` | reference | Python, or YAML + data file | target or measured data; Python when it depends on the design |
| `measurements/` | measurement set | YAML | which probes to run and which metrics they feed |
| `pipelines/` | pipeline | YAML | stages: backend, fidelity, 2-D equivalence choices, exports, resources |

Studies (`studies/`) and site profiles (outside the project) are not library entries.

**R4. One expression syntax.** A string value of the form `"${ <expression> }"` is an expression. It must
be the whole value and must be quoted, because unquoted `${…}` isn't valid inside YAML flow mappings.
- Names are parameter paths (R6) or study variable names.
- Operators: `+ - * / **`, comparisons, `and`/`or`/`not`, `a if cond else b`, and the functions
  `min max abs sqrt sin cos tan pi`. String literals are allowed for comparisons
  (`post_mat == 'het:materials/a36'`).
- Literal numbers are dimensionless, except that `0` takes whatever dimension it's combined with. Any
  constant with units must be a named parameter.
- Evaluation uses units. The result's dimension must match the target's. Evaluation follows
  dependencies, and a cycle is an error.
- A path to an empty optional slot evaluates to `null`. Using `null` in arithmetic is an error that names
  the expression, so a guard (`... if parts.pole_cap else 0`) is required.

**R5. Units.** `project.yaml` sets one display unit per dimension.
- A bare number is read in the display unit of the **target's dimension**, which comes from a schema:
  part-type parameters, probe/metric/reference parameters, backend fidelity, the operating point.
  Counts and ratios stay dimensionless.
- Where there is no schema (assembly parameters, and study variables that use `sets:`), the unit must be
  written out (`18 mm`, `unit: A`).
- Internally everything is SI.

**R6. Parameter paths.** A row's resolved inputs form one tree with four reserved roots:
- `params.*`: assembly parameters;
- `parts.<slot>.*`: part parameters and derived values;
- `op.*`: the operating point;
- `fidelity.<stage>.*`: backend settings per stage.

**R7. Inheritance (`extends`).** Dictionaries merge recursively; lists and scalars replace; `null` empties
a key.
- Emptying a part slot is only allowed if the slot is marked `optional`.
- When a child or a study choice changes a slot's `use:` or `type:`, the slot's **content** (`use`,
  `type`, `params`) is replaced whole and its **placement** (`at`, `optional`) is kept.
- Things a child needs to extend one item at a time (stages, checks, probes, metrics, objectives,
  constraints) are written as **named dictionaries, never lists**.

**R8. Versions.**
- **Code entries** (part types, probes, metrics, references written in Python, backends) carry
  `"MAJOR.MINOR.PATCH"`: MAJOR = interface change, MINOR = output change, PATCH = no output change.
  `bplsim check` runs every probe, metric and Python reference on a fixed synthetic solution and fails if
  the output changed while `MAJOR.MINOR` didn't.
- **Data entries** (YAML) carry no version. Their resolved values are hashed directly (R9), and git keeps
  the history.

**R9. Identity and caching.**
- **Case hash = what the solver sees:** canonical geometry regions (coordinates quantised to 1 nm), the
  material properties the backend uses, excitation regions and turns, fidelity, and the backend's
  `MAJOR.MINOR`. Coil currents are excluded when the solve is linear (superposition).
- Consequences: a row that differs only in coil temperature or a description reuses an existing solve. A
  part-type refactor that leaves the geometry unchanged invalidates nothing. A geometry change invalidates
  exactly the affected cases.
- **Run hash = case hash + the full resolved inputs + the normalization spec** (§12), so design-only
  metrics such as power are attached to the right run.

**R10. Variables and bounds.** A study range must lie within the parameter's schema bounds. Only
**independent** values can be swept: targeting a derived value is an error that names its inputs.

**R11. Overlaps and clearances.**
- Every pair of parts is checked for overlap automatically. Overlap is invalid; touching is allowed
  (tolerance 1 nm).
- **Minimum gaps** apply only to pairs listed in a check, each pair with its own minimum.

---

## 2. The project folder

```
sim/                              (project `het`: a folder in the HET repository)
├── project.yaml                  name, namespace, bplsim version, display units, included libraries
├── library/
│   ├── vocabulary.yaml           material property aliases
│   ├── materials/                a36, steel_1018, bn, copper, wire_awg20_mw16c (+ B-H tables)
│   ├── part_types/               plate, channel_insulator, core, pole_cap_flat, screen, post_array,
│   │                             solenoid, post_coils, _winding (helper)
│   ├── parts/                    plate_6in_a36, bn_channel_v2, cap_flat_r17p6, cap_flat_r15_t3,
│   │                             solenoid_230t_awg20, post_coils_184t_awg20
│   ├── assemblies/               bpl1000_bn, bn_screened
│   ├── probes/                   channel_profile, channel_ring, channel_wall
│   ├── metrics/                  field_shape, wall_angle, coil_power
│   ├── references/               half_gaussian_exit
│   ├── measurements/             channel_field_2d, channel_field_3d
│   └── pipelines/                magnetostatics_2d, magnetostatics_3d_nonlinear, magnetostatics_3d_to_pic
├── studies/                      cap_screen_trade_2d, post_count_trade_3d
└── reports/                      (not covered in this example)
```

Outside the project:
- **bplsim itself:** the backends (`getdp_axisym`, `getdp_3d`, later `warpx`) and the **standard library
  `std:`**. `std:` holds only entries that know nothing about any device: region data, field-map export,
  saturation, ring ripple, profile misfit, clearance, containment.
- **Site profiles:** `~/.config/bplsim/sites/`.
- **The data root:** `<site data_root>/<project name>/`, e.g. `~/bplsim_data/het/`.

| I want to… | Edit |
|---|---|
| change a material or wire property | `library/materials/<material>.yaml` |
| change how a kind of part is shaped (e.g. add a chamfer) | `library/part_types/<type>.py` |
| record a real part we own or ordered, or one used in several assemblies | `library/parts/<part>.yaml` |
| change the baseline thruster | `library/assemblies/<assembly>.yaml` |
| measure the field somewhere new | new `library/probes/<probe>.py` |
| compute a new number from measurements | new `library/metrics/<metric>.py` |
| change the target profile | `library/references/<reference>` |
| change mesh, solver, 2-D equivalence choices or stage hand-offs | `library/pipelines/<pipeline>.yaml` |
| ask a new trade question (variables, objectives, constraints, sampler) | new `studies/<study>.yaml` |
| run somewhere else | `--site` on the command line |

---

## 3. Project file

```yaml
# project.yaml
name: het
namespace: het
bplsim: ">=0.1,<0.2"
libraries:
  std: {builtin: true}
  # lab: {git: "https://github.com/<org>/lab-library", ref: v1.2.0}   # a shared library, included by version
units:                                   # display units: how bare numbers are read and values are shown
  length: mm
  angle: deg
  current: A
  temperature: degC
  magnetic_flux_density: G
  power: W
```

---

## 4. Materials (wire included)

A material is a set of named properties with units. The set is open-ended: only consumers that ask for a
property check for it.

```yaml
# library/vocabulary.yaml — canonical name: [aliases]. A file using two names for one property is an error.
mu_r_linear:     [mu_r, relative_permeability]
bh_curve:        [bh, b_h_curve]
saturation_knee: [b_knee, knee]
resistivity:     [rho_e, electrical_resistivity]
density:         [rho, mass_density]
```

```yaml
# library/materials/a36.yaml
description: "ASTM A36 structural steel, as rolled"
sources: ["supplier datasheet (illustrative)"]
properties:
  density: 7850 kg/m^3
  mu_r: 1500                             # alias of mu_r_linear; used by linear solves
  bh_curve: {table: a36_bh.csv, columns: {H: A/m, B: T}}      # used by nonlinear solves
  saturation_knee: 1.5 T
  thermal_conductivity: 51.9 W/(m*K)     # nothing uses this yet; kept for a future thermal backend
```

```yaml
# library/materials/steel_1018.yaml
extends: het:materials/a36
description: "AISI 1018, annealed"
properties:
  mu_r: 2200
  bh_curve: {table: steel_1018_bh.csv, columns: {H: A/m, B: T}}
  saturation_knee: 1.6 T
```

```yaml
# library/materials/copper.yaml
description: "Annealed copper"
properties:
  density: 8960 kg/m^3
  resistivity: {value: 1.724e-8 ohm*m, at: 20 degC, temp_coeff: 0.00393 1/K}
```

```yaml
# library/materials/wire_awg20_mw16c.yaml — a wire is copper plus its wire properties
extends: het:materials/copper
description: "AWG 20 magnet wire, heavy polyimide (MW 16-C), 240 °C"
properties:
  wire_diameter: 0.812 mm
  insulated_diameter: 0.89 mm
  max_temperature: 240 degC
```

Both coil types take a `wire:` parameter that must provide `resistivity`, `wire_diameter` and
`insulated_diameter`. They're checked when a row is resolved, with an error naming the material and the
part. `bn.yaml` (`mu_r: 1`, density) follows the same pattern.

**Value forms:** a scalar with units; a table file with column units; or `{value, at, temp_coeff}` for
linear temperature dependence. The consumer asks for the value at a temperature or field.

---

## 5. Part types (Python)

A part type defines parameters (with units and bounds), local checks, derived values, geometry in its
**own local frame**, and named surfaces. A part that isn't axisymmetric also provides named
**equivalence rules** for 2-D backends.

```python
# library/part_types/pole_cap_flat.py
from bplsim.parts import PartType, Param, Length, Material, margin
from bplsim.geom import rz, cad
from bplsim.units import mm


class PoleCapFlat(PartType):
    version = "1.1.0"
    doc = "Flat pole cap disc, optional chamfer between edge face and back face."
    frame = "front face at z = 0, body toward -z, axis on z"

    class Params:
        radius: Length = Param(17.6 * mm, min=5 * mm)
        thickness: Length = Param(9.525 * mm, min=0.5 * mm)
        edge_length: Length | None = Param(None)          # axial length of the edge face; None = thickness
        chamfer_width: Length = Param(0 * mm, min=0 * mm)  # radial width of the chamfer on the back face
        material: Material = Param("het:materials/steel_1018", needs=["mu_r_linear"])

    def checks(self, p):
        t = p.edge_length or p.thickness
        yield margin("edge_within_thickness", p.thickness - t, min=0 * mm)
        yield margin("chamfer_within_radius", p.radius - p.chamfer_width, min=1 * mm)
        if p.chamfer_width > 0:
            yield margin("chamfer_has_height", p.thickness - t, min=0.1 * mm)

    def profile_rz(self, p):                           # edge i joins pts[i] and pts[i + 1]
        t = p.edge_length or p.thickness
        if p.chamfer_width == 0:
            pts = [(0, 0), (p.radius, 0), (p.radius, -p.thickness), (0, -p.thickness)]
            surfaces = {"front_face": [0], "edge_face": [1], "back_face": [2]}
        else:
            pts = [(0, 0), (p.radius, 0), (p.radius, -t), (p.radius - p.chamfer_width, -p.thickness),
                   (0, -p.thickness)]
            surfaces = {"front_face": [0], "edge_face": [1], "chamfer": [2], "back_face": [3]}
        return rz.Region(pts, material=p.material, surfaces=surfaces)

    def solid_3d(self, p):
        return cad.revolve(self.profile_rz(p))           # surface names carry over to the 3-D faces
```

```python
# library/part_types/post_array.py
from math import pi, sin

from bplsim.parts import PartType, Param, Length, Angle, Material, margin, equivalence
from bplsim.geom import rz, cad
from bplsim.units import mm, deg


class PostArray(PartType):
    version = "1.0.0"
    doc = "N cylindrical posts on a circle."
    frame = "front ends at z = 0, posts toward -z, post #1 at theta = phase"

    class Params:
        count: int = Param(4, min=2, max=16)
        ring_radius: Length = Param(63.5 * mm)
        post_radius: Length = Param(9.525 * mm, min=1 * mm)
        length: Length = Param(41.275 * mm, min=1 * mm)
        phase: Angle = Param(0 * deg)
        material: Material = Param("het:materials/a36", needs=["mu_r_linear"])

    def derived(self, p):
        return {"pitch": 2 * pi / p.count}                 # angle between neighbouring posts

    def checks(self, p):
        chord = 2 * p.ring_radius * sin(pi / p.count)
        yield margin("posts_do_not_touch", chord - 2 * p.post_radius, min=0 * mm)

    def solid_3d(self, p):
        post = cad.cylinder(p.post_radius, p.length)
        return cad.polar_array(post, p.count, p.ring_radius, p.phase, names="post_{i}")

    @equivalence("smeared_ring", valid_for="linear")    # same rule as today's ring_geometry()
    def smeared_ring(self, p):
        fill = p.count * pi * p.post_radius**2 / (2 * pi * p.ring_radius * 2 * p.post_radius)
        ring = rz.rect(p.ring_radius - p.post_radius, p.ring_radius + p.post_radius, -p.length, 0)
        return rz.Region(ring, material=p.material.with_mu_r(1 + fill * (p.material.mu_r_linear - 1)))
```

`valid_for="linear"` matters. Scaling μ is only meaningful for a linear material, so a nonlinear 2-D
pipeline that selects `smeared_ring` is rejected before anything runs.

The two coil types share their winding logic through a helper, and each declares which part it's
wound on as a **typed slot reference**:

```python
# library/part_types/_winding.py — helper (underscore: not an entry)
from math import ceil, pi

from bplsim.parts import Param, Material, PartType


class Winding(PartType):
    """Base class for coils: wire, turns, layers, resistance. Both coil types inherit it."""

    class Params:
        wire: Material = Param(needs=["resistivity", "wire_diameter", "insulated_diameter"])
        turns: int = Param(min=1)                      # per coil
        per_layer: int = Param(min=1)
        circuit: str = Param()                         # name of an op circuit

    def winding(self, p):
        d = p.wire.insulated_diameter
        layers = ceil(p.turns / p.per_layer)
        return {"layers": layers, "length": p.per_layer * d, "build": layers * d}

    def coil_count(self, p):
        return 1                                       # post_coils: one coil per post

    def mean_turn_length(self, p):
        raise NotImplementedError                      # each coil type knows its own geometry

    def derived(self, p):
        return {**self.winding(p), "coil_count": self.coil_count(p)}

    def resistance(self, p, temperature):              # of one coil
        area = pi * p.wire.wire_diameter**2 / 4
        return p.wire.resistivity.at(temperature) * p.turns * self.mean_turn_length(p) / area
```

**Resolved parts:** in probes, metrics and expressions, a resolved part exposes its parameters and
derived values as attributes (`coil.turns`, `coil.coil_count`, `parts.outer_posts.pitch`). Part-type
methods that take extra arguments are called without `p` (`coil.resistance(temperature)`).

```python
# library/part_types/post_coils.py
from math import pi, sin

from bplsim.parts import Param, Slot, margin, equivalence
from bplsim.geom import rz, cad
from bplsim.units import mm

from het.part_types._winding import Winding


class PostCoils(Winding):
    version = "1.0.0"
    doc = "One identical coil on each post of a post_array, all on one circuit."
    frame = "front ends at z = 0, coils toward -z"

    class Params(Winding.Params):
        on: Slot = Param(type="het:part_types/post_array")     # the posts these coils are wound on

    def coil_count(self, p):
        return p.on.count

    def mean_turn_length(self, p):
        return 2 * pi * (p.on.post_radius + self.winding(p)["build"] / 2)

    def derived(self, p):
        d = super().derived(p)
        return {**d, "outer_radius": p.on.post_radius + d["build"]}

    def checks(self, p):
        chord = 2 * p.on.ring_radius * sin(pi / p.on.count)
        yield margin("coils_do_not_touch", chord - 2 * (p.on.post_radius + self.winding(p)["build"]), min=0 * mm)

    def solid_3d(self, p):
        ...                                          # one annular winding per post, excitation = circuit, turns

    @equivalence("winding_sheets", valid_for="any")  # same rule as today's inner/outer winding sheets
    def winding_sheets(self, p):
        ...                                          # two annular current sheets at ring_radius -/+ post_radius
```

The other part types follow the same pattern:
- `solenoid.py` has `on: Slot = Param(type="het:part_types/core")` and an exact r–z profile.
- `plate.py` has `shape: square|round` and the equivalence rule `equal_area_disc` for square plates.
- `channel_insulator.py`, `core.py` and `screen.py` are plain axisymmetric types.

Geometry regions carry their material and, for windings, an **excitation** (circuit name and turns).
That's everything a backend needs to set up currents. The `cad` helpers are a thin layer over gmsh's
OpenCASCADE kernel (plan §6).

---

## 6. Parts (YAML)

A part is a part type plus parameter values. It earns its own file when it's **a real physical object**
(it exists, was ordered, or has a drawing), or when **two or more assemblies use it**. Everything else stays
inline in the assembly.

```yaml
# library/parts/cap_flat_r17p6.yaml
type: het:part_types/pole_cap_flat
description: "Pole cap, flat, R17.6 (inside the BN bore with 0.12 mm clearance)"
params: {radius: 17.6, thickness: 9.525, material: het:materials/steel_1018}
```

```yaml
# library/parts/cap_flat_r15_t3.yaml
type: het:part_types/pole_cap_flat
description: "Thin flat pole cap, R15, 3 mm thick (candidate)"
params: {radius: 15.0, thickness: 3.0, material: het:materials/steel_1018}
```

```yaml
# library/parts/bn_channel_v2.yaml
type: het:part_types/channel_insulator
description: "Boron nitride channel part, drawing Boron_Nitride_Channel (2026-10-20)"
params:
  r_in: 22.12             # assumed; not dimensioned on the drawing (BN_REPORT.md)
  r_out: 31.45
  depth: 41.43            # exit plane to anode face (bottom 6.35 mm of the channel filled)
  bore_radius: 17.72      # centre bore; the pole cap and inner screen must fit inside it
  lip_radius: 38.1
  lip_length: 9.525
  body_radius: 44.45
  total_length: 47.78
  material: het:materials/bn
```

```yaml
# library/parts/plate_6in_a36.yaml
type: het:part_types/plate
description: "6 in square A36 plate, 3/8 in thick, 3 in bore"
params: {shape: square, side: 152.4, thickness: 9.525, bore_radius: 38.1, material: het:materials/a36}
```

```yaml
# library/parts/solenoid_230t_awg20.yaml
type: het:part_types/solenoid
description: "Inner coil: 230 turns AWG 20, 46 per layer"
params: {wire: het:materials/wire_awg20_mw16c, turns: 230, per_layer: 46, circuit: inner}
# 'on' (which core) is left for the assembly to set; a part may leave required params unset
```

```yaml
# library/parts/post_coils_184t_awg20.yaml
type: het:part_types/post_coils
description: "Outer coils: 184 turns AWG 20 per post, 46 per layer"
params: {wire: het:materials/wire_awg20_mw16c, turns: 184, per_layer: 46, circuit: outer}
```

---

## 7. Assemblies

An assembly holds:
- **parameters**: independent ones, plus derived ones written as expressions;
- **slots**, each holding a part or an inline part type, with an axial placement `at`;
- named **checks** that every study inherits;
- the **nominal operating point**.

```yaml
# library/assemblies/bpl1000_bn.yaml
description: "BPL-1000 with the BN channel (illustrative values)"

params:                                   # no schema here, so units are written out (R5)
  back_plate_inner_z: -50.8 mm
  front_plate_inner_z: "${ -parts.front_plate.thickness }"                       # derived
  cap_back_z: "${ -parts.pole_cap.thickness if parts.pole_cap else 0 }"          # derived; cap is optional

parts:                                    # 'at' places the part's local z = 0 (global +z downstream, 0 = exit plane)
  channel:     {use: het:parts/bn_channel_v2, at: 0}
  front_plate: {use: het:parts/plate_6in_a36, at: 0}
  back_plate:  {use: het:parts/plate_6in_a36, at: "${ params.back_plate_inner_z }",
                params: {bore_radius: 3.4}}           # same plate, smaller bore: override on top of the part
  pole_cap:    {use: het:parts/cap_flat_r17p6, at: 0, optional: true}
  inner_core:
    type: het:part_types/core
    at: "${ params.cap_back_z }"                       # starts behind the cap, so the two never overlap
    params:
      radius: 9.525
      length: "${ params.cap_back_z - params.back_plate_inner_z }"
      material: het:materials/steel_1018
  inner_coil:  {use: het:parts/solenoid_230t_awg20, at: "${ params.cap_back_z }", params: {on: inner_core}}
  outer_posts:
    type: het:part_types/post_array
    at: "${ params.front_plate_inner_z }"
    params:
      count: 4
      ring_radius: 63.5
      post_radius: 9.525
      length: "${ params.front_plate_inner_z - params.back_plate_inner_z }"
      material: het:materials/a36
  outer_coils: {use: het:parts/post_coils_184t_awg20, at: "${ params.front_plate_inner_z }",
                params: {on: outer_posts}}

checks:                                   # named, so children add to them (R7); overlap is always checked (R11)
  cap_in_bore:    {metric: std:metrics/clearance, with: {pairs: [[pole_cap, channel, 0.1]]}}
  posts_on_plate: {metric: std:metrics/within, with: {inner: outer_posts, outer: front_plate, min_edge: 1.0}}

op:
  temperature: 20
  circuits:
    inner: {current: 1.53}
    outer: {current: 1.21}
```

```yaml
# library/assemblies/bn_screened.yaml
extends: het:assemblies/bpl1000_bn
description: "Illustrative: flat cap R17.6 + inner screen from 1-3/8 x .095 DOM tube, tip gap 18 (no outer screen)"
params:
  inner_screen_gap: 18 mm                                                   # screen tip to front plate inner face
  screen_tip_z: "${ params.front_plate_inner_z - params.inner_screen_gap }"
parts:
  inner_screen:
    type: het:part_types/screen
    at: "${ params.screen_tip_z }"
    optional: true
    params:
      r_inner: 15.05
      thickness: 2.41
      length: "${ params.screen_tip_z - params.back_plate_inner_z }"
      material: het:materials/a36
checks:
  screen_clearance:
    metric: std:metrics/clearance
    with: {pairs: [[inner_screen, channel, 0.1], [inner_screen, inner_coil, 0.4]]}
```

Pairs that involve an empty optional slot are skipped, so removing the cap doesn't break `cap_in_bore`.

**Seeing every resolved value and where it came from:**

```
$ bplsim show het:assemblies/bn_screened
params.back_plate_inner_z      -50.8 mm    ← het:assemblies/bpl1000_bn
params.front_plate_inner_z      -9.525 mm  ← derived  -parts.front_plate.thickness
params.cap_back_z               -9.525 mm  ← derived  -parts.pole_cap.thickness
params.inner_screen_gap         18 mm      ← het:assemblies/bn_screened
params.screen_tip_z            -27.525 mm  ← derived
parts.pole_cap.radius           17.6 mm    ← het:parts/cap_flat_r17p6
parts.pole_cap.chamfer_width     0 mm      ← het:part_types/pole_cap_flat (default)
parts.back_plate.bore_radius     3.4 mm    ← het:assemblies/bpl1000_bn (overrides het:parts/plate_6in_a36)
parts.inner_core.length         41.275 mm  ← derived
parts.inner_coil.length         40.94 mm   ← derived  46 per layer × 0.89 mm
parts.inner_coil.build           4.45 mm   ← derived  5 layers × 0.89 mm  (outer radius 13.975 mm)
parts.inner_screen.length       23.275 mm  ← derived  (BN_REPORT: 23.28 mm at gap 18)
parts.outer_posts.count          4         ← het:assemblies/bpl1000_bn
op.circuits.outer.current        1.21 A    ← het:assemblies/bpl1000_bn
checks
  overlap              all pairs                       none                          ok
  cap_in_bore          pole_cap ↔ channel              gap 0.12 mm   (min 0.1)       ok
  screen_clearance     inner_screen ↔ channel          gap 0.26 mm   (min 0.1)       ok
                       inner_screen ↔ inner_coil       gap 1.075 mm  (min 0.4)       ok
  posts_on_plate       outer_posts in front_plate      edge 3.175 mm (min 1.0)       ok
  part checks          posts_do_not_touch +70.8 mm, coils_do_not_touch +63.6 mm     ok
```

---

## 8. Probes

A probe turns geometry into a request on the backend's **field access**, an interface every backend
implements (plan §7):

```python
class FieldAccess:                                     # implemented once per backend
    symmetry: str                                      # "axisymmetric" or "none"

    def sample(self, where, fields): ...               # where: points or a parametric grid in global (r, theta, z)
    def region(self, part, fields): ...                # elements: centroid, volume weight, values
    def boundary(self, surface, fields): ...           # facets: centroid, normal, area, values
    def export_grid(self, grid, fields, fmt): ...      # e.g. openPMD file for a later stage
```

When the solve is superposed, the framework runs each probe once per basis solve and combines the results
for each run. Probes never deal with this.

```python
# library/probes/channel_profile.py — the legacy "channel profile"
from bplsim.probes import probe, grid_rtz, radial_mean, Slot, Length, Angle
from bplsim.units import mm


@probe(version="1.0.0", kind="line")
def channel_profile(design, sol, channel: Slot = Slot("channel", type="het:part_types/channel_insulator"),
                    dz: Length = 0.25 * mm, dr: Length = 0.25 * mm, beyond_exit: Length = 15 * mm,
                    azimuth: Angle | str = "average", n_theta: int = 36):
    """B averaged over the channel's radial span (r-weighted) at each axial position, from the anode face
    to beyond_exit downstream. azimuth="average": also averaged over n_theta angles (identical in 2-D)."""
    ch = design.parts[channel]
    g = grid_rtz(r=(ch.r_in, ch.r_out, dr), z=(-ch.depth, beyond_exit, dz), azimuth=azimuth, n_theta=n_theta)
    return radial_mean(sol.sample(g, ["B"]), weight="r")      # → B_r(z), B_theta(z), B_z(z)
```

The channel slot is a parameter with a default, so an assembly that calls its slot `insulator` still
works with `with: {channel: insulator}`. The slot's part type is checked when the row is resolved.

```python
# library/probes/channel_ring.py
from bplsim.probes import probe, ring, Slot, Length


@probe(version="1.0.0", kind="ring")
def channel_ring(design, sol, z: Length, channel: Slot = Slot("channel", type="het:part_types/channel_insulator"),
                 n_theta: int = 360):
    """B on a full circle at the channel mid-radius, at axial position z."""
    ch = design.parts[channel]
    return sol.sample(ring(r=(ch.r_in + ch.r_out) / 2, z=z, n=n_theta), ["B"])
```

```python
# library/probes/channel_wall.py — a boundary (surface) probe
from bplsim.probes import probe, Slot


@probe(version="1.0.0", kind="surface")
def channel_wall(design, sol, wall: str = "inner_wall",
                 channel: Slot = Slot("channel", type="het:part_types/channel_insulator")):
    """B on a named surface of the channel part (surface names come from the part type)."""
    return sol.boundary(f"{channel}.{wall}", ["B"])
```

From `std:`: `std:probes/part_fields` (region data for each selected part) and
`std:probes/fieldmap_export` (grid export).

---

## 9. Metrics

A metric declares the **kind** of input it needs (`line[B]`, `ring[B]`, `regions[B]`, `surface[B]`), not a
specific probe. A measurement set connects probes to inputs. The function receives its declared inputs
and parameters by name, plus `design` and `op` if it asks for them.

```python
# library/metrics/field_shape.py
from bplsim.metrics import metric


@metric(version="2.0.0", inputs={"profile": "line[B]"},
        outputs={"peak_Br": "T", "peak_z": "m", "exit_Br_pct": "%", "anode_Br_pct": "%",
                 "anode_B_pct": "%", "half_depth": "m", "sigma": "m"})
def field_shape(profile, design):
    """The legacy shape metrics (metrics.shape_metrics): peak of B_r searched from 15 mm beyond the exit
    to the anode, exit and anode values as % of peak, half depth, pinned-amplitude half-Gaussian sigma."""
    ...
```

```python
# library/metrics/wall_angle.py
from bplsim.metrics import metric


@metric(version="1.0.0", inputs={"surface": "surface[B]"},
        outputs={"mean_deg": "deg", "max_deg": "deg"})
def wall_angle(surface):
    """Angle between B and the wall surface, area-weighted: how field lines meet the channel wall."""
    ...
```

```python
# library/metrics/coil_power.py — depends only on design + op
from bplsim.metrics import metric

from het.part_types._winding import Winding


@metric(version="1.0.0", inputs={}, outputs={"total": "W"})
def coil_power(design, op):
    total = 0.0
    for coil in design.parts_of(Winding):
        current = op.circuits[coil.circuit].current
        total += coil.coil_count * current**2 * coil.resistance(op.temperature)
    return {"total": total}
```

This is the **one** power formula: I²R per coil, with R from the actual turns, mean turn length, wire
area and temperature.

From `std:`:
- `saturation`: `regions[B]` → `max_fraction`, `worst_part`, using each material's `saturation_knee`;
- `ring_ripple`: `ring[B]` → `ripple_pct`, `mean_Br`;
- `profile_misfit`: `line[B]` + reference → `rms_pct`, `max_pct` (% of peak, wherever the reference is defined);
- `clearance` and `within`, which depend only on the design.

**Design-only metrics** (no inputs) are evaluated when a row is resolved. They're used in the pre-screen
**unless they depend on normalized values** (§12), in which case they run after normalization.

---

## 10. References and measurement sets

A reference that depends on the design is a Python function. This one does: the target width scales with
the channel length.

```python
# library/references/half_gaussian_exit.py
from math import exp

from bplsim.measure import reference, Slot
from bplsim.units import G


@reference(version="1.0.0", kind="line[B]")
def half_gaussian_exit(design, z, channel: Slot = Slot("channel", type="het:part_types/channel_insulator"),
                       sigma_per_length: float = 0.353, peak=165 * G):
    """Target supplied 2026-10-21 (TARGET_REPORT.md): B_r is a half-Gaussian peaked at the exit plane,
    sigma = 0.353 x channel length. Defined inside the channel only (anode face to exit plane)."""
    depth = design.parts[channel].depth
    sigma = sigma_per_length * depth
    return {"B_r": [peak * exp(-0.5 * (zi / sigma) ** 2) if -depth <= zi <= 0 else None for zi in z]}
```

On the old 33.02 mm channel this gives σ = 11.66 mm. On the BN channel (41.43 mm) it gives 14.6 mm,
matching `BN_REPORT.md`. A fixed data file would have been right for only one of the two channels. A
reference that is plain data (e.g. a measured profile) is a YAML file pointing at a CSV with column units.

A measurement set gives each probe and metric a local **alias**. Results are stored as `<alias>.<output>`,
together with a hash of the full definition (entry, version, parameters, which probe feeds it).

```yaml
# library/measurements/channel_field_2d.yaml
description: "Channel profile and shape, iron saturation, field angle at the inner wall, coil power"
probes:
  profile: {probe: het:probes/channel_profile}
  iron:    {probe: std:probes/part_fields, with: {select: magnetic}}
  wall:    {probe: het:probes/channel_wall, with: {wall: inner_wall}}
metrics:
  shape:      {metric: het:metrics/field_shape, inputs: {profile: profile}}
  sat:        {metric: std:metrics/saturation,  inputs: {parts: iron}}
  wall_angle: {metric: het:metrics/wall_angle,  inputs: {surface: wall}}
  power:      {metric: het:metrics/coil_power}
```

```yaml
# library/measurements/channel_field_3d.yaml — everything above, plus what only 3-D can show
extends: het:measurements/channel_field_2d
probes:
  profile_post:    {probe: het:probes/channel_profile, with: {azimuth: 0}}                 # through post #1
  profile_between: {probe: het:probes/channel_profile,
                    with: {azimuth: "${ parts.outer_posts.pitch / 2 }"}}                  # between two posts
  ring_mid:  {probe: het:probes/channel_ring, with: {z: -20}}
  ring_exit: {probe: het:probes/channel_ring, with: {z: 0}}
metrics:
  ripple_mid:  {metric: std:metrics/ring_ripple, inputs: {ring: ring_mid}}
  ripple_exit: {metric: std:metrics/ring_ripple, inputs: {ring: ring_exit}}
```

`profile` is averaged over angle by default, so its 2-D and 3-D results compare directly. The
through-post and between-post profiles are stored for figures (today's two-azimuth channel-profile plot)
and aren't used by any metric.

---

## 11. Pipelines

```yaml
# library/pipelines/magnetostatics_2d.yaml
description: "Linear axisymmetric magnetostatics (GetDP)"
stages:
  mag:
    backend: getdp_axisym ^1.0
    fidelity:                             # schema from the backend; bare lengths in mm
      nonlinear: false                    # linear: coil currents superposed (not in the case hash)
      mesh: {h_fine: 0.35, h_iron: 1.2, h_far: 25}
      air_radius: 400
    equivalence:                          # 2-D modelling choices for parts that are not axisymmetric
      outer_posts: smeared_ring
      outer_coils: winding_sheets
      front_plate: equal_area_disc
      back_plate:  equal_area_disc
    resources: {cores: 1, memory: 1 GB}
```

```yaml
# library/pipelines/magnetostatics_3d_nonlinear.yaml
description: "Nonlinear 3-D magnetostatics (GetDP), with a field-map export"
stages:
  mag:
    backend: getdp_3d ^1.0
    fidelity:
      nonlinear: true                     # needs bh_curve on every magnetic material; currents in the case hash
      newton: {tol: 1.0e-6, max_iter: 40}
      mesh: {h_fine: 0.8, h_iron: 2.5, h_far: 40}
      air_radius: 300
    exports:                              # products a later stage (or a figure) can use
      fieldmap: {probe: std:probes/fieldmap_export,
                 with: {grid: cartesian, x: [-80, 80], y: [-80, 80], z: [-60, 60], spacing: 1.0}}
    resources: {cores: 4, memory: 6 GB, runtime_hint: 6 min}
```

```yaml
# library/pipelines/magnetostatics_3d_to_pic.yaml — chaining, for when WarpX exists
extends: het:pipelines/magnetostatics_3d_nonlinear
description: "3-D magnetostatics, then PIC in that field"
stages:
  pic:
    backend: warpx ^0.1
    inputs: {B_external: mag.exports.fieldmap}     # this reference also orders the stages
    fidelity: {cells: [128, 128, 256], particles_per_cell: 16, steps: 200000}
    resources: {gpus: 1, memory: 40 GB, runtime_hint: 8 h, restartable: true}
```

Stage hand-offs are defined inside the pipeline (`exports` → `inputs`), so a pipeline doesn't depend on
whichever measurement set a study uses. `runtime_hint` is only used until the database has real timings.

---

## 12. Example A: 2-D study

**Question:** which pole cap (or none), what inner-screen gap and thickness, and what outer/inner
ampere-turn ratio best match the target profile, with currents scaled to a 165 G peak, within the
saturation and power limits? This is the shape of the legacy `target_sigma` and `bn_design` searches.

```yaml
# studies/cap_screen_trade_2d.yaml
description: "Pole cap choice × inner screen × ampere-turn ratio vs the half-Gaussian target, at 165 G"
design:   het:assemblies/bn_screened
pipeline: het:pipelines/magnetostatics_2d
measure:
  use: het:measurements/channel_field_2d
  add:                                            # metrics only this study needs
    misfit: {metric: std:metrics/profile_misfit, inputs: {profile: profile},
             with: {reference: het:references/half_gaussian_exit, component: B_r}}
overrides:                                        # fixed for the whole study
  op.temperature: 80                              # degC
variables:
  cap:    {slot: pole_cap, choices: [het:parts/cap_flat_r17p6, het:parts/cap_flat_r15_t3, none]}
  is_gap: {param: params.inner_screen_gap, range: [10, 30]}           # mm
  is_t:   {param: parts.inner_screen.thickness, range: [0.5, 3.0]}    # mm
  q:      {range: [0.4, 1.0],                                         # outer A-turns per coil / inner A-turns
           sets: {op.circuits.outer.current:
                  "${ op.circuits.inner.current * q * parts.inner_coil.turns / parts.outer_coils.turns }"}}
normalize:                                        # one factor k scales both currents, keeping q
  scale: [op.circuits.inner.current, op.circuits.outer.current]
  so_that: {value: shape.peak_Br, equals: 165}    # G
objectives:
  misfit: {minimize: misfit.rms_pct}
constraints:
  saturation: {value: sat.max_fraction, max: 0.8}
  power:      {value: power.total, max: 5}        # W, at the normalized currents
sampler: {kind: optuna_tpe, seed: 7, mode: sync, round_size: 24}
budget: {runs: 300, max_invalid: 600}             # 'runs' counts solved rows; invalid rows are capped separately
retention: {raw: purge_on_success}
```

**Normalization.** Legacy studies compare designs at a fixed peak (165 G), not at fixed currents.
`normalize` finds one factor k for the listed values so that the named output hits its target.
- On a superposed (linear) case, k is found by root-finding on the combined probe data, with no extra
  solves.
- With nonlinear iron, each trial k is a new solve. That is planned with the 3-D backend (plan §17,
  phase 6) and not used in this example.
- The normalized currents are stored with the run as `normalized.op.circuits.*.current`.
- Anything that depends on them (here `power`) is evaluated after normalization, so the power constraint
  is checked after the solve, not in the pre-screen.

**How a row is resolved** (the same for every study):
1. **Structure:** baseline + `overrides` + slot choices (`cap`). A slot choice replaces the slot's content
   and keeps its placement (R7).
2. **Values:** direct variables, `sets:` expressions and the assembly's expressions are evaluated as one
   dependency graph. Two writers to the same path is an error. A variable that targets a parameter the
   chosen part doesn't have is an error.
3. **Pre-screen:** overlaps, assembly checks, part checks, and constraints on design-only metrics that
   don't depend on normalized values. A failure makes the row `invalid`: it's recorded and told to the
   optimizer as infeasible together with its margins, but never solved.
4. **Hashes** (R9), then submit if not already done.

**The runsheet** (study-variable values on the left, the resulting parameter values on the right):

| row | round | cap | is_gap | is_t | q | parts.pole_cap | params.inner_screen_gap | parts.inner_screen.thickness | pre-screen | case | run |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | cap_flat_r17p6 | 18.0 | 2.41 | 0.63 | cap_flat_r17p6 | 18.0 mm | 2.41 mm | ok | 3fa1… | 91c0… |
| 1 | 0 | cap_flat_r17p6 | 18.0 | 2.41 | 0.55 | cap_flat_r17p6 | 18.0 mm | 2.41 mm | ok | **3fa1…** | 0d7e… |
| 2 | 0 | cap_flat_r15_t3 | 12.4 | 2.65 | 0.80 | cap_flat_r15_t3 | 12.4 mm | 2.65 mm | invalid: screen_clearance (inner_screen ↔ channel gap 0.02 mm, min 0.1) | — | — |
| 3 | 0 | none | 27.2 | 1.6 | 0.45 | — | 27.2 mm | 1.6 mm | ok | 7be2… | 55a9… |

- Rows 0 and 1 differ only in q, so they share case `3fa1…`: one pair of basis solves (one per circuit),
  two runs.
- Row 2: the screen's outer radius is 15.05 + 2.65 = 17.70 mm against a 17.72 mm bore. Any `is_t` above
  2.57 mm is invalid.
- Row 3 (no cap): `cap_back_z` = 0, so the core and inner coil start at the exit plane, and `cap_in_bore`
  is skipped.
- The 80 °C override changes coil resistance and therefore power, not the field. These cases are shared
  with any other study that solved the same geometry at 20 °C.

---

## 13. Example B: 3-D study

**Question:** how do the number of outer posts, their radius and material, and the total outer
ampere-turns trade exit-plane ripple against coil power, with nonlinear iron?

```yaml
# studies/post_count_trade_3d.yaml
description: "Outer post count, size and material vs exit-ring ripple and coil power (3-D, nonlinear)"
production: true                                   # refuses to run from a dirty git tree
design:   het:assemblies/bn_screened
pipeline: het:pipelines/magnetostatics_3d_nonlinear
measure:  {use: het:measurements/channel_field_3d}
variables:
  n_posts:  {param: parts.outer_posts.count, values: [4, 6, 8]}
  post_r:   {param: parts.outer_posts.post_radius, range: [6.35, 12.7]}               # mm
  post_mat: {param: parts.outer_posts.material, choices: [het:materials/a36, het:materials/steel_1018]}
  ni_out:   {range: [400, 4000], unit: A, scale: log,                                  # total outer ampere-turns
             sets: {op.circuits.outer.current: "${ ni_out / (n_posts * parts.outer_coils.turns) }"}}
objectives:                                        # two objectives: a Pareto trade
  ripple: {minimize: ripple_exit.ripple_pct}
  power:  {minimize: power.total}
constraints:
  peak:       {value: shape.peak_Br, min: 150}     # G
  saturation: {value: sat.max_fraction, max: 0.9}
sampler:
  kind: product                                    # full grid × space-filling points
  of:
    - {kind: grid,  vars: [n_posts, post_mat]}             # 3 × 2 = 6 combinations
    - {kind: sobol, vars: [post_r, ni_out], n: 16, seed: 3} # 16 points per combination → 96 rows
retention: {raw: 14 days, exports: pinned}
pin: ["${ n_posts == 4 and post_mat == 'het:materials/a36' }"]   # keep everything for these rows
```

```
$ bplsim study run studies/post_count_trade_3d.yaml --site savio
$ bplsim sync pull --site savio --study post_count_trade_3d        # later, from the laptop
```

**What this shows, beyond example A:**

| Feature | How it appears here |
|---|---|
| integer variable, with checks that depend on it | `n_posts` drives `posts_do_not_touch` and `coils_do_not_touch`. Over this range both always pass (worst case: 8 posts at r 12.7 still leaves 16.1 mm between coils), so they're recorded but never limiting |
| a check that does limit the range | `posts_on_plate` needs 1 mm of plate beyond each post: 76.2 − 63.5 − r ≥ 1 → r ≤ 11.7 mm. Rows with r > 11.7 (about one in six) are invalid and never solved |
| linked parts | `outer_coils.on: outer_posts`: coil count, positions and radius follow the posts |
| a categorical choice of material | `post_mat` |
| log scale | `ni_out` covers a factor of 10, so Sobol points are spread evenly per decade |
| expression using a variable and a parameter | current per coil = total ampere-turns / (posts × turns per coil) |
| combined samplers | grid × Sobol |
| objectives with a fixed DOE | the DOE doesn't use them to choose points; they rank the results and define the Pareto front, and constraints mark rows feasible or not |
| explicit currents instead of normalization | `ni_out` is swept directly; with nonlinear iron, every valid row is its own solve |
| measurement-set inheritance; one metric on two probes | `channel_field_3d` extends `channel_field_2d`; `ripple_mid` and `ripple_exit` |
| export kept only where needed | `exports: pinned`: the field map is written only for rows matching `pin` (known before solving) |
| production guard; remote site | `production: true`; `--site savio`, with no change to the study |

**Exports and pinning after the fact:**
- Pins are evaluated at resolve time, so the export is written while the solution is loaded.
- A row pinned *after* it ran (e.g. "the Pareto-best design") gets its export from `bplsim remeasure`
  while its raw data is retained (14 days here). After that it needs a re-solve.

**2-D vs 3-D cross-check:** run example A's best design through this pipeline with a one-row `list`
sampler. Both use `channel_profile` averaged over angle, so `shape.*` compares directly between the two
backends.

---

## 14. Sites and how work is packed

```yaml
# ~/.config/bplsim/sites/savio.yaml (illustrative)
name: savio
data_root: /global/scratch/users/<user>/bplsim_data
executor: slurm
slurm: {partition: savio3, account: fc_<pi>, cpus_per_node: 32, memory_per_node: 96 GB,
        max_walltime: "72:00:00", max_concurrent_tasks: 20}
container: /global/scratch/users/<user>/images/bplsim_<tag>.sif
```

```yaml
# ~/.config/bplsim/sites/laptop.yaml
name: laptop
data_root: ~/bplsim_data
executor: local
local: {workers: auto, memory_limit: 24 GB}
```

**Packing rule:**
- **slots per node** = min(cores ÷ cores per run, memory ÷ memory per run);
- **rows per task** = slots × k, where k is the smallest whole number that makes a task last at least
  10 minutes (so scheduler and container start-up are paid rarely);
- **tasks** = rows ÷ rows per task, rounded up, with at most `max_concurrent_tasks` running at once.

Example B: slots = min(32/4, 96/6) = 8. With 6-minute runs, k = 2, so 16 rows per task. About 80 valid rows
gives 5 tasks of about 12 minutes, all running at once. A 2-D study with runs of a few seconds packs into
one task, and locally it simply uses the worker pool.

---

## 15. One row from start to finish (example B, row 17)

```
row 17: n_posts = 6, post_r = 8.1 mm, post_mat = steel_1018, ni_out = 1210 A

resolve   bn_screened (extends bpl1000_bn) + row values
          parts.outer_posts.count = 6, .post_radius = 8.1 mm, .material = het:materials/steel_1018
          op.circuits.outer.current = 1210 / (6 × 184) = 1.096 A
checks    overlap none · posts_on_plate edge 76.2 − 63.5 − 8.1 = 4.6 mm (min 1.0) · cap_in_bore 0.12 mm
          screen_clearance 0.26 / 1.075 mm · posts_do_not_touch 63.5 − 16.2 = 47.3 mm
          coils_do_not_touch 63.5 − 2 × (8.1 + 3.56) = 40.18 mm                         → valid
design-only metrics   power.total (stored; it's an objective here, not a constraint)
hash      case = solve_inputs(getdp_3d 1.0: 3-D geometry, 1018 B-H table, excitation 6 × 184 turns
                 at 1.096 A, fidelity) → 8c2e…;  run = case + full inputs → 41d9…
task      Savio array task 2 → bplsim run-task
          prepare  part types → 3-D solids → gmsh mesh → GetDP input
          execute  getdp, Newton
          measure  probes profile, iron, wall, profile_post, profile_between, ring_mid, ring_exit
                   metrics shape, sat, wall_angle, power, ripple_mid, ripple_exit → DONE
                   (no field-map export: row 17 is not pinned)
collect   sync pull → collect → trade DB (parameters and metrics stored long, with provenance)
```

---

## 16. Reuse across projects

- **Include (the default).** List another library in `project.yaml` (a path, or git at a fixed ref) and refer
  to its entries by its namespace. Nothing is copied, so nothing drifts.
- **Fork (deliberate divergence).** `bplsim lib fork lab:materials/a36 --into het` copies the file into
  this library as `het:materials/a36`. Entries it refers to stay pointing at `lab:` unless they're forked
  too.
- **`std:`** ships with bplsim, so generic probes and metrics are never copied at all.

A new BPL project includes the libraries it needs, writes its own assemblies and device-specific probes,
and reuses materials, generic part types, pipelines and `std:`.

---

## 17. Not covered in this example

- **Reports** (plan §14).
- **Geometry beyond axial placement**, the CAD kernel, and the Fusion workflow (plan §6 and §20).
- **Execution internals:** run-task, locks, failure classes, collect, sync (plan §11).

---

## Appendix A: audit log

### A.1 Concepts removed because they weren't justified (v0.1 → v0.2)

| # | Before | Problem | Now |
|---|---|---|---|
| 1 | `catalog/` kind for wire | A wire is copper plus a few properties, and materials already allow any properties | wire is a material (`wire_awg20_mw16c` extends `copper`) |
| 2 | `goals/` kind | Goals referred to measurement-set aliases, so they weren't self-contained; also only 3–5 lines | objectives and constraints live in the study; study-specific metrics in `measure.add` |
| 3 | `datums` | A second kind of named value next to parameters | derived assembly parameters |
| 4 | `rules` block (min clearance, max OD) | Limits separated from the checks that use them | limits are check parameters, per pair |
| 5 | `id:` in files and decorators | Duplicated the path; could disagree with it | ids from paths (R1) |
| 6 | version numbers on data entries | Hand-maintained, could drift from content | data hashed by content; versions only on code (R8) |
| 7 | `flip:` placement | Not needed once each part type defines its local frame | removed |
| 8 | `connection: series` on a circuit | Nothing used it | removed |
| 9 | one `coil` type with `around:` that adapted to whatever it was around | Behaviour hidden inside one type | `solenoid` and `post_coils`, each with a typed `on:` slot reference |
| 10 | `keep: pinned_only` on a probe *and* `pin:` on the study | Two retention mechanisms | one `retention` block + `pin` |
| 11 | `after:` between pipeline stages | Duplicated what the inputs already imply | order inferred from `inputs` |
| 12 | `std:` library mentioned only at the end, unexplained | Unsupported | defined up front (§2) with what qualifies |

### A.2 Hidden dependencies made explicit (v0.1 → v0.2)

| # | Before | Problem | Now |
|---|---|---|---|
| 13 | probes hard-coded `parts.channel` | Broke for any assembly with a different slot name | slot is a typed probe parameter with a default |
| 14 | WarpX input referred to a measurement alias | The pipeline depended on a study's measurement set | stage `exports` → `inputs`, inside the pipeline |
| 15 | metric aliases used as database names | Same alias, different definitions would mix data across studies | stored with a definition hash |
| 16 | `lib copy` with namespaces unspecified | Unclear what happens to references | include (default) vs fork, with a stated reference rule |

### A.3 Errors in the v0.1 example (v0.1 → v0.2)

| # | Before | Problem | Now |
|---|---|---|---|
| 17 | clearance check `pairs: all` | Coils on cores and posts on plates touch by design, so every design would fail | automatic overlap check + explicit minimum-gap pairs (R11) |
| 18 | envelope "max OD 160" with a 152.4 mm square plate | Plate diagonal 215.5 mm: the baseline would fail | removed; `posts_on_plate` containment check |
| 19 | inner screen r 19.5–22.5 | Inside the BN body (bore r 17.72) | inside the bore, with bore and coil clearance checks |
| 20 | alternative cap R20 | Doesn't fit the 17.72 bore | `cap_flat_r15_t3` |
| 21 | inner coil placed at `-parts.pole_cap.thickness` while the study allowed `none` | Undefined with no cap | guarded expression; empty-slot rule (R4) |
| 22 | inner core and pole cap occupied the same volume | Legacy relied on drawing order | core starts at the cap's back face; overlap is invalid |
| 23 | "8 posts × large radius fails pre-screen" | False | corrected; `posts_on_plate` is the limiting check |
| 24 | `show` output "clearance +1.88 mm" | Wrong pair geometry | recomputed from the stated numbers |
| 25 | unquoted `${…}` in flow mappings; two interpolation styles | Invalid YAML; ambiguous | one quoted form; all blocks parse-checked |
| 26 | "bare numbers are mm" project-wide | Counts and ratios would become lengths | per-dimension display units, driven by schemas (R5) |
| 27 | `smeared_ring` scaled μ | Invalid for nonlinear materials | equivalence rules declare `valid_for` |
| 28 | `winding_sheets` selected but never defined | Unsupported reference | defined in `post_coils` |
| 29 | 2-D vs 3-D comparison with a θ = 0 line | In 3-D that line goes through a post | profile averaged over angle by default |
| 30 | chunking: 45-min target vs "12 tasks of 8" | Contradictory | one packing rule with worked numbers (§14) |
| 31 | `mid_channel_ring` at z = −5 | Not mid-channel | `channel_ring` with explicit z |
| 32 | `wall` probe that nothing used | Unsupported | `wall_angle` metric |
| 33 | `machinability_note: fine` | Pointless example | `thermal_conductivity`, with its purpose |

### A.4 Mechanisms that were unspecified (v0.1 → v0.2)

| # | Now specified in |
|---|---|
| 34 | merge rules for `extends` | R7 |
| 35 | resolution order and conflicts | §12 |
| 36 | expression language | R4 |
| 37 | case and run hashes | R9 |
| 38 | ranges within bounds; derived values can't be swept | R10 |
| 39 | budget and invalid rows | §12 |
| 40 | slot choice combined with variables on that slot | §12 step 2 |
| 41 | adding probes or pinning after a run | §13 |
| 42 | effect of a probe or metric version change | R8 |
| 43 | metric function arguments | §9 |
| 44 | helper files and imports between library scripts | R2 |

### A.5 Mismatches with the legacy code (v0.2 → v0.3)

Found by checking v0.2 against `metrics.py`, `target_sigma.py`, `report_figs.py` and `BN_REPORT.md`:

| # | v0.2 | Problem | v0.3 |
|---|---|---|---|
| 45 | example assembly called `design_b` | Collides with the real Design B (shieldless, `report_figs.py`), which is a different design | `bn_screened`; real Design A and B are defined in the port |
| 46 | reference = fixed CSV, σ 11.66 mm | The target is σ = 0.353 × channel length: 14.6 mm on the BN channel, so a fixed file was wrong there | design-dependent Python reference `half_gaussian_exit` |
| 47 | `channel_centerline`: B on the mid-radius line | The legacy profile is B averaged over the channel's radial span (r-weighted), so regressions couldn't match | `channel_profile` probe, same definition and grid spacing as legacy |
| 48 | no way to compare designs at a fixed peak | Every legacy trade scales currents to 165 G before scoring | `normalize` block (§12) |
| 49 | power constraint applied at pre-screen | Under normalization, power depends on the solved currents | design-only metrics that depend on normalized values run after normalization |
| 50 | ratio defined on currents | Legacy `q` is the outer-per-coil / inner **ampere-turn** ratio | `q` defined on ampere-turns |
| 51 | screen 14.4–17.6 (invented) | Real stock tube is R 15.05–17.46 (BN_REPORT) | tube values used; screen length at gap 18 matches BN_REPORT's 23.28 mm |
