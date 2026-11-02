# study: studies, samplers and the driver

| File | Role |
|---|---|
| `spec.py` | study specs and variables (example §12-13, plan §9.1-9.2): `design`, `pipeline`, `measure`, `variables` (`param`, `slot`, `values`/`range`, `sets`), `normalize`, `objectives`, `constraints`, `sampler`, `budget`, `retention`; unknown keys are errors |
| `samplers.py` | batch ask/tell samplers (plan §9.3): `grid`, `list` (rows given explicitly), `sobol` and `lhs` (quasi-random), `product` (combine samplers over variable groups), `compass` (pattern search), `optuna_tpe`, `optuna_nsga2` (multi-objective), with constraints |
| `driver.py` | the study driver (plan §9.5): per round, ask -> resolve + pre-screen + hash -> runsheet -> jobs -> execute -> collect -> tell; reuses cached cases and runs, resumes after interruption, retries a crashed task once |
