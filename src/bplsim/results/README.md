# results: reading results back

| File | Role |
|---|---|
| `analysis.py` | the analysis API for notebooks and scripts: a study's table, single runs, and their probe data combined at the run's (normalized) currents |
| `report.py` | reports (plan §14): a Markdown/Jinja template whose numbers and figures come from the database (`bplsim report build reports/x.md.j2`), so the text cannot drift from the data |

Figures themselves are library entries (`figures/` folder, `@figure` from `bplsim.figures`); the generic ones are
in `std/figures/`.
