# measure: from solved fields to numbers

A measurement set (library `measurements/` entry) lists probes (where to sample fields) and metrics (numbers
computed from probe data). Probes run per solved basis; a run combines them at its own currents.

| File | Role |
|---|---|
| `__init__.py` | public names for library authors: `Slot`, `reference` (the `@reference` decorator for target profiles) |
| `data.py` | `ProbeData`: named coordinate and field arrays, stored in HDF5 (K3: plain arrays + h5py, no xarray); weighted sums for superposition |
| `engine.py` | the measurement engine: measurement sets, probe and metric definitions, evaluation in the worker, combine (superposition of bases at a run's currents), normalization (scale currents so a metric hits a target; secant iteration for nonlinear cases, K21), per-stage measurement (K20) |
| `openpmd.py` | minimal openPMD 1.1 (HDF5) field files written with h5py, the format WarpX reads for external fields (pipeline exports, K19) |
