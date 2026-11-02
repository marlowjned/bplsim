# model: from library entries to a resolved design

| File | Role |
|---|---|
| `project.py` | projects and libraries (rules R1-R3, plan §3): reads `project.yaml`, loads every entry of each library (ids from file paths, `ns:folder/name`), imports Python entries as packages, validates them; the built-in `std` library is loaded the same way |
| `materials.py` | materials: open-ended sets of named properties with units (example §4); B-H curves; the vocabulary of property names and aliases |
| `assembly.py` | assembly documents: loading and `extends` merging, recording where each value came from (rule R7), for `bplsim show` |
| `resolve.py` | resolution (plan §5): assembly + study row -> one `ResolvedDesign` (parts with their parameters, materials, operating point, derived values), evaluating expressions with units |
| `checks.py` | the pre-screen (plan §5 step 4, rule R11): part checks, the automatic overlap check (exact in r-z, K6), assembly checks; rows that fail are recorded and never solved |
| `pipeline.py` | pipelines: named stages, each with a backend, fidelity, equivalence choices, exports, inputs and resources |
