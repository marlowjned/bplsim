"""Figures (plan §14): registered functions in a library's `figures/` folder.

A figure function receives a FigureContext and its parameters, and returns a matplotlib Figure. It reads
results only through the context (study tables, runs, probe data), never from study scripts, so any figure
can be regenerated from the data root alone.

    @figure(version="1.0.0")
    def channel_profiles(ctx, study: str, color_by: str = "params.inner_screen_gap"): ...
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STYLE = {
    "figure.dpi": 110, "savefig.dpi": 160, "font.size": 9, "axes.grid": True, "grid.alpha": 0.3,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
}


def figure(version: str):
    def deco(fn):
        fn._bplsim = {"kind": "figure", "version": str(version)}
        return fn
    return deco


class FigureContext:
    def __init__(self, project, results):
        self.project = project
        self.results = results
        self.units = project.units

    def table(self, study: str):
        return self.results.study_table(study)

    def run(self, run_id: str):
        return self.results.run(run_id)

    def show(self, value_si: float, dim_name: str) -> float:
        from .units import DIMS
        return self.units.from_si(value_si, DIMS[dim_name])

    def label(self, dim_name: str) -> str:
        from .units import DIMS
        return self.units.display.get(dim_name, DIMS[dim_name].display)


def render(project, results, figure_id: str, params: dict, out) -> str:
    fn = project.python_entry(figure_id, "figures")
    with plt.rc_context(STYLE):
        fig = fn(FigureContext(project, results), **params)
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
    return str(out)
