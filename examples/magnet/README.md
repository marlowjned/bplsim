# Example: a Hall-thruster magnetic circuit

A parameter sweep on a real device: the magnetic circuit of a Hall-effect thruster (inner core and coil, four
outer posts with coils, front and back plates, a pole cap, an inner magnetic screen, and the boron-nitride
channel), solved as 2-D axisymmetric magnetostatics with iron in GetDP. The question: where should the inner
screen sit so that the radial field along the channel best matches a half-Gaussian target with a 165 G peak?

It is the runnable version of the example in [`docs/user_guide.md`](../../docs/user_guide.md), which explains every
file kind in detail.

**Needs GetDP** (3.5): put it on `PATH`, set `BPLSIM_TOOL_GETDP=/path/to/getdp`, or add
`tools: {getdp: /path/to/getdp}` to the site profile `~/.config/bplsim/sites/local.yaml`.

## Files

| File | Role |
|---|---|
| `project.yaml` | name and namespace (`magnet`), libraries, and the display units: bare numbers in YAML are mm, deg, A, degC, G, W |
| `library/vocabulary.yaml` | canonical material-property names and their aliases |
| `library/materials/` | A36 steel (with a B-H curve, `a36_bh.csv`), 1018 steel, copper, boron nitride, and the winding wire (copper plus its wire properties) |
| `library/part_types/*.py` | the Python part types: their parameters with units, checks, r-z geometry and equivalences (how a non-axisymmetric part is represented in 2-D). `_winding.py` is a shared helper (underscore: not an entry) |
| `library/parts/*.yaml` | concrete parts: a part type with values (e.g. `cap_flat_r17p6` is a flat pole cap of radius 17.6 mm) |
| `library/assemblies/bpl1000_bn.yaml` | the baseline thruster: which part fills each slot, placements, the operating point (coil currents, temperature) |
| `library/assemblies/bn_screened.yaml` | `extends` the baseline and adds the inner screen, positioned by the parameter `inner_screen_gap` |
| `library/probes/*.py` | where fields are sampled: the channel profile (B averaged over the channel's radial span at each z), a ring at the mid-radius, the channel's inner wall |
| `library/metrics/*.py` | numbers from probe data: field shape (peak, sigma, exit and anode fractions), field angle at the wall, coil power (I^2 R from turns, wire and temperature) |
| `library/references/half_gaussian_exit.py` | the target profile the misfit is measured against |
| `library/measurements/channel_field_2d.yaml` | the measurement set: probes plus metrics, including `std:metrics/saturation` over the iron parts |
| `library/pipelines/magnetostatics_2d.yaml` | one stage: backend `getdp_axisym`, mesh sizes, and the 2-D equivalences chosen for posts, coils and plates |
| `studies/gap_sweep.yaml` | the sweep: six inner-screen gaps; `normalize:` scales both coil currents so the peak B_r is 165 G; `misfit` is added to the measurement set for this study |
| `reports/gap_sweep.md.j2` | a report: the best gap, a table, two figures, all from the database |

## Run it

```
cd examples/magnet
bplsim check
bplsim show magnet:assemblies/bn_screened     # every resolved value and the file:line it came from
bplsim study run studies/gap_sweep.yaml       # 6 rows, about 12 s
bplsim report build reports/gap_sweep.md.j2   # writes reports/gap_sweep.md and reports/gap_sweep_figures/
```

## What you should get

The best fit is at a 14 mm gap: misfit 4.7 % of peak, coil power 1.12 W at 165 G. The misfit rises to 9.4 % at
30 mm. Running the study again is instant: every case is found in the cache.

To try another sweep, copy `gap_sweep.yaml` and change the variable, e.g.
`is_t: {param: parts.inner_screen.thickness, values: [0.5, 1, 2, 3]}`.
