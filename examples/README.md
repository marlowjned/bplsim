# Examples

Two small projects to copy from. Run every command from inside the project folder (bplsim finds `project.yaml`
there); results go to `~/bplsim_data/<project name>/` unless you pass `--data <dir>` or set `BPLSIM_DATA`.

| Project | Needs | What it shows |
|---|---|---|
| [`functions/`](functions/README.md) | nothing beyond bplsim | the commands on a test function with a known minimum: a sweep and an optimizer, and a report. Seconds |
| [`magnet/`](magnet/README.md) | GetDP | a real device: a Hall-thruster magnetic circuit built from part types, parts and assemblies; a sweep of one geometry parameter with 2-D FEM, currents normalized to a target field; a report. About 12 s |

Start with `functions/` to learn the commands, then read `magnet/` to see how a device is described. The
configuration language is documented in [`docs/user_guide.md`](../docs/user_guide.md).
