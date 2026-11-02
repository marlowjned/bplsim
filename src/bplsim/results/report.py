"""Reports (plan §14): a markdown template whose numbers and figures come from the data, so the text cannot
drift from the results. `bplsim report build reports/<name>.md.j2` renders <name>.md next to it, with its
figures in <name>_figures/.

Template functions:
    {{ value("study", "metric", "unit", ".2f", row="best"|"first"|<row_id>) }}  a number from a study
    {{ figure("ns:figures/id", name="file", **params) }}                       renders and links a figure
    {{ table("study", ["col", ...], sort="metric", n=10) }}                     a markdown table
    {{ study("name") }}                                                        the full study id

`value(row="best")` and `table` use only the rows that meet the study's constraints (`feasible=False` for all
done rows); a study with constraints but no feasible row is an error rather than a quoted infeasible design.
"""
from __future__ import annotations

import math
from pathlib import Path

import jinja2

from bplsim.figures import render


def build(project, results, template_path: str | Path) -> Path:
    template_path = Path(template_path)
    stem = template_path.name.replace(".md.j2", "").replace(".j2", "")
    out_md = template_path.with_name(stem + ".md")
    fig_dir = template_path.with_name(stem + "_figures")
    fig_dir.mkdir(exist_ok=True)
    used: list[str] = []

    def _row(df, row, metric):
        if row == "best":
            return df.loc[df[metric].astype(float).idxmin()]
        if row == "first":
            return df.iloc[0]
        return df[df["row_id"] == int(row)].iloc[0]

    def _done(study, feasible):
        df = results.study_table(study)
        df = df[df["status"] == "done"]
        return feasible_rows(results, study, df) if feasible else df

    def value(study, metric, unit="", fmt=".4g", row="best", by=None, feasible=True):
        df = _done(study, feasible and row == "best")
        r = _row(df, row, by or metric)
        v = float(r[metric])
        if unit and unit not in ("%", "1"):
            from bplsim.units import Q_
            from bplsim.store.db import DB  # noqa: F401
            base = _unit_of(results, metric)
            v = Q_(v, base).to(unit).magnitude if base else v
        return format(v, fmt) + (f" {unit}" if unit and unit != "1" else "")

    def figure(fid, name=None, **params):
        name = name or fid.split("/")[-1]
        path = fig_dir / f"{name}.png"
        render(project, results, fid, params, path)
        used.append(name)
        return f"![{name}]({fig_dir.name}/{name}.png)"

    def table(study, cols, sort=None, n=10, fmt=".4g", feasible=True):
        df = _done(study, feasible)
        if sort:
            df = df.sort_values(sort, key=lambda s: s.astype(float))
        df = df.head(n)
        head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
        rows = []
        for _, r in df.iterrows():
            cells = []
            for c in cols:
                v = r.get(c)
                cells.append(format(float(v), fmt) if isinstance(v, (int, float)) and not
                             (isinstance(v, float) and math.isnan(v)) else str(v))
            rows.append("| " + " | ".join(cells) + " |")
        return head + "\n".join(rows)

    def study(name):
        return results.study_id(name)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(template_path.parent)),
                             undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    text = env.get_template(template_path.name).render(value=value, figure=figure, table=table, study=study)
    out_md.write_text(text, encoding="utf-8")
    return out_md


def feasible_rows(results, study: str, df):
    """The rows of `df` (a study table) that meet the study's constraints. Limits are read as the driver reads
    them: bare numbers in the project's display unit for the metric's dimension, compared in SI."""
    from ruamel.yaml import YAML

    from bplsim.units import dim_of
    rows = results.db.query("SELECT spec_yaml FROM studies WHERE study_id=?", [results.study_id(study)])
    spec = YAML(typ="safe").load(rows[0]["spec_yaml"]) if rows and rows[0]["spec_yaml"] else {}
    cons = (spec or {}).get("constraints") or {}
    if not cons:
        return df
    keep = df.index == df.index
    for name, c in cons.items():
        col = c.get("value")
        if col not in df:
            raise KeyError(f"study {study}: constraint {name} reads {col!r}, not in the study table")
        v = df[col].astype(float).to_numpy()
        base = _unit_of(results, col)
        d = dim_of(results.units.parse(f"1 {base}")) if base not in ("", "1", "%", "text") else None
        for key in ("min", "max"):
            if c.get(key) is not None:
                lim = results.units.to_si(c[key], d) if d is not None else float(c[key])
                keep &= (v >= lim) if key == "min" else (v <= lim)
    if not keep.any():
        raise ValueError(f"study {study}: no done row meets the constraints {', '.join(cons)}")
    return df[keep]


def _unit_of(results, metric: str) -> str:
    rows = results.db.query("SELECT unit FROM metrics WHERE name=? LIMIT 1", [metric])
    if rows:
        return rows[0]["unit"] or ""
    rows = results.db.query("SELECT unit FROM params WHERE path=? LIMIT 1", [metric])
    from bplsim.units import DIMS
    if rows and rows[0]["unit"] in DIMS:
        return DIMS[rows[0]["unit"]].si
    return ""
