"""Overlay one line probe (e.g. a profile) from several runs of a study."""
import matplotlib.pyplot as plt
import numpy as np

from bplsim.figures import figure


@figure(version="1.0.0")
def line_probe(ctx, study: str, probe: str, field: str = "B_r", coord: str = "z", label_by: str | None = None,
               max_runs: int = 12, field_scale: float = 1e4, coord_scale: float = 1e3,
               field_label: str = "B_r (G)", coord_label: str = "z (mm)"):
    df = ctx.table(study)
    df = df[df["status"] == "done"].head(max_runs)
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    for _, r in df.iterrows():
        d = ctx.run(r["run_id"]).probe(probe)
        x = np.ravel(d[coord]) * coord_scale
        y = np.ravel(d[field]) * field_scale
        o = np.argsort(x)
        lab = f"{label_by} = {r[label_by]:.4g}" if label_by and isinstance(r.get(label_by), float) else \
            (f"{label_by} = {r[label_by]}" if label_by else r["run_id"][:8])
        ax.plot(x[o], y[o], lw=1.3, label=lab)
    ax.set_xlabel(coord_label)
    ax.set_ylabel(field_label)
    ax.legend(fontsize=7)
    return fig
