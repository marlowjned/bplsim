"""Scatter (or line) of one study column against another, optionally coloured by a third."""
import matplotlib.pyplot as plt
import numpy as np

from bplsim.figures import figure


@figure(version="1.0.0")
def scatter(ctx, study: str, x: str, y: str, color: str | None = None, line: bool = False,
            x_scale: float = 1.0, y_scale: float = 1.0, x_label: str | None = None, y_label: str | None = None,
            title: str | None = None):
    """x, y, color: study-table columns (variables, parameter paths, alias.output metrics).
    x_scale / y_scale multiply the stored (SI) values, e.g. 1000 for mm."""
    df = ctx.table(study)
    df = df[df["status"] == "done"]
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    if color and color in df:
        for key, g in df.groupby(color):
            g = g.sort_values(x)
            xs, ys = g[x].astype(float) * x_scale, g[y].astype(float) * y_scale
            (ax.plot if line else ax.scatter)(xs, ys, label=f"{color} = {key}", **({"marker": "o"} if line else {}))
        ax.legend()
    else:
        g = df.sort_values(x)
        xs, ys = g[x].astype(float) * x_scale, g[y].astype(float) * y_scale
        (ax.plot if line else ax.scatter)(xs, ys, **({"marker": "o"} if line else {}))
    ax.set_xlabel(x_label or x)
    ax.set_ylabel(y_label or y)
    if title:
        ax.set_title(title)
    return fig
