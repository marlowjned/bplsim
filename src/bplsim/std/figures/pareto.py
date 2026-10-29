"""Two-objective scatter with the Pareto front highlighted."""
import matplotlib.pyplot as plt

from bplsim.figures import figure
from bplsim.store.query import pareto_mask


@figure(version="1.0.0")
def pareto(ctx, study: str, x: str, y: str, x_maximize: bool = False, y_maximize: bool = False,
           x_scale: float = 1.0, y_scale: float = 1.0, x_label: str | None = None, y_label: str | None = None):
    df = ctx.table(study)
    df = df[df["status"] == "done"]
    m = pareto_mask(df, [("-" if x_maximize else "") + x, ("-" if y_maximize else "") + y])
    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    ax.scatter(df[x].astype(float) * x_scale, df[y].astype(float) * y_scale, s=12, color="0.7", label="all")
    f = df[m].sort_values(x)
    ax.plot(f[x].astype(float) * x_scale, f[y].astype(float) * y_scale, "o-", color="C3", ms=4, label="Pareto front")
    ax.set_xlabel(x_label or x)
    ax.set_ylabel(y_label or y)
    ax.legend()
    return fig
