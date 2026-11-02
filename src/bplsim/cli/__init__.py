"""The bplsim command line (plan §13)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from bplsim import __version__

app = typer.Typer(add_completion=False, no_args_is_help=True, help="bplsim: simulation trade studies.")
study_app = typer.Typer(no_args_is_help=True, help="Plan, run and inspect studies.")
lib_app = typer.Typer(no_args_is_help=True, help="Library tools.")
app.add_typer(study_app, name="study")
app.add_typer(lib_app, name="lib")


def _version_cb(value: bool):
    if value:
        typer.echo(f"bplsim {__version__}")
        raise typer.Exit()


@app.callback()
def _main(version: bool = typer.Option(False, "--version", callback=_version_cb, is_eager=True,
                                       help="Show the version and exit.")):
    pass


def find_project(start: Optional[Path]) -> Path:
    p = (start or Path.cwd()).resolve()
    if p.is_file():
        return p.parent
    for d in [p, *p.parents]:
        if (d / "project.yaml").exists():
            return d
    raise typer.BadParameter(f"no project.yaml in {p} or its parents (use --project)")


def data_root_for(project_dir: Path, data: Optional[Path], site) -> Path:
    from bplsim.model.project import Project
    if data:
        return data
    if os.environ.get("BPLSIM_DATA"):
        return Path(os.environ["BPLSIM_DATA"])
    name = Project.load(project_dir).name
    return Path(site.data_root).expanduser() / name


def _fail(e: Exception):
    typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command()
def check(project: Optional[Path] = typer.Option(None, "--project", "-p")):
    """Load and validate every library entry and assembly; report all errors at once."""
    from bplsim.cli.check import check_project
    errors = check_project(find_project(project))
    if errors:
        for e in errors:
            typer.secho(str(e), fg=typer.colors.RED)
        typer.echo(f"{len(errors)} error(s)")
        raise typer.Exit(1)
    typer.secho("ok", fg=typer.colors.GREEN)


@app.command()
def show(entry: str, project: Optional[Path] = typer.Option(None, "--project", "-p"),
         pipeline: Optional[str] = typer.Option(None, help="Pipeline id, to include fidelity values.")):
    """Resolved values of an assembly with the origin of every value, and its checks."""
    from bplsim.model.checks import prescreen
    from bplsim.model.project import Project
    from bplsim.model.resolve import Resolver
    from bplsim.core.errors import BplsimError
    try:
        pr = Project.load(find_project(project))
        fid = None
        if pipeline:
            from bplsim.model.pipeline import load_pipeline
            fid = load_pipeline(pr, pipeline).fidelity_spec()
        d = Resolver(pr, entry, fidelity=fid).resolve()
        w = max(len(p) for p, _, _ in d.show())
        for p, v, o in d.show():
            typer.echo(f"{p:<{w}}  {v:<22} <- {o}")
        ps = prescreen(d, d.checks_spec)
        typer.echo("checks")
        for i in ps.items:
            mark = "ok" if i.ok else "FAIL"
            typer.echo(f"  {i.name:<40} {i.detail:<70} {mark}")
    except BplsimError as e:
        _fail(e)


def _driver(study: Path, project, data, site, workers, refresh=False):
    from bplsim.execute.sites import load_site
    from bplsim.study.driver import Driver
    s = load_site(site)
    pdir = find_project(project or study.parent)
    root = data_root_for(pdir, data, s)
    return Driver(pdir, study, root, executor=s.make_executor(workers), refresh_snapshot=refresh,
                  log=typer.echo)


@study_app.command("plan")
def study_plan(study: Path, project: Optional[Path] = typer.Option(None, "--project", "-p"),
               data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site"),
               rows: bool = typer.Option(False, "--rows", help="List every row.")):
    """Dry run: resolve and pre-screen the first round; report validity, cache hits and cost."""
    from bplsim.core.errors import BplsimError
    try:
        d = _driver(study, project, data, site, None)
        rep = d.plan()
    except BplsimError as e:
        _fail(e)
    detail = rep.pop("rows_detail")
    for k, v in rep.items():
        typer.echo(f"{k:>20}: {v}")
    if rows:
        for r in detail:
            typer.echo(f"  row {r.row_id:>4} {r.status:<8} {json.dumps(r.values)} {r.reason}")


@study_app.command("run")
def study_run(study: Path, project: Optional[Path] = typer.Option(None, "--project", "-p"),
              data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site"),
              workers: Optional[int] = typer.Option(None, "--workers"),
              one_round: bool = typer.Option(False, "--one-round"),
              refresh_snapshot: bool = typer.Option(False, "--refresh-snapshot")):
    """Run (or resume) a study."""
    from bplsim.core.errors import BplsimError
    try:
        d = _driver(study, project, data, site, workers, refresh_snapshot)
        typer.echo(f"study {d.study_id}  (data: {d.root.root})")
        summary = d.run(one_round=one_round)
    except BplsimError as e:
        _fail(e)
    typer.echo(json.dumps(summary, indent=1))


@study_app.command("status")
def study_status(study: Path, project: Optional[Path] = typer.Option(None, "--project", "-p"),
                 data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Progress, failures and the best rows so far."""
    from bplsim.store.query import study_table
    d = _driver(study, project, data, site, None)
    df = study_table(d.db, d.study_id)
    typer.echo(json.dumps(d.summary(), indent=1))
    if len(df):
        typer.echo(df.head(20).to_string())


@app.command("run-task")
def run_task_cmd(task: Path, jobs: Optional[str] = typer.Option(None, "--jobs"),
                 workers: int = typer.Option(1, "--workers", help="Parallel job groups (one node)")):
    """Worker entry point: run the jobs of a task file (used by executors)."""
    from bplsim.execute.runtask import run_task
    out = run_task(task, jobs, workers)
    typer.echo(json.dumps(out))


@app.command()
def collect(project: Optional[Path] = typer.Option(None, "--project", "-p"),
            data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site"),
            rebuild: bool = typer.Option(False, "--rebuild")):
    """Index case and run folders into the trade database."""
    from bplsim.execute.folders import DataRoot
    from bplsim.execute.sites import load_site
    from bplsim.store.collect import collect as do_collect, rebuild as do_rebuild
    from bplsim.store.db import DB
    root = DataRoot(data_root_for(find_project(project), data, load_site(site)))
    if rebuild:
        typer.echo(json.dumps(do_rebuild(root)))
    else:
        db = DB(root.db_path)
        typer.echo(json.dumps(do_collect(root, db)))
        db.close()


@app.command()
def query(where: str = typer.Argument("", help="Expression over parameter paths, e.g. 'parts.pole_cap.radius <= 17.6 mm'"),
          metrics: Optional[str] = typer.Option(None, "--metrics", help="Comma-separated metric names."),
          study: Optional[str] = typer.Option(None, "--study"),
          pareto: Optional[str] = typer.Option(None, "--pareto", help="Comma-separated objectives, prefix '-' to maximize."),
          out: Optional[Path] = typer.Option(None, "--out"),
          project: Optional[Path] = typer.Option(None, "--project", "-p"),
          data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Results as a table (CSV or Parquet with --out)."""
    from bplsim.execute.folders import DataRoot
    from bplsim.model.project import Project
    from bplsim.execute.sites import load_site
    from bplsim.store.db import DB
    from bplsim.store.query import query as do_query
    pdir = find_project(project)
    root = DataRoot(data_root_for(pdir, data, load_site(site)))
    db = DB(root.db_path)
    df = do_query(db, Project.load(pdir).units, where=where or None,
                  metrics=metrics.split(",") if metrics else None, study=study,
                  pareto=pareto.split(",") if pareto else None)
    if out:
        df.to_parquet(out) if str(out).endswith(".parquet") else df.to_csv(out, index=False)
        typer.echo(f"{len(df)} rows -> {out}")
    else:
        typer.echo(df.to_string() if len(df) else "no rows")


@app.command()
def gc(older_than_days: float = typer.Option(14.0, "--raw-older-than-days"),
       dry_run: bool = typer.Option(False, "--dry-run"),
       project: Optional[Path] = typer.Option(None, "--project", "-p"),
       data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Delete raw solver output of unpinned cases older than the limit (probes and metrics are kept)."""
    from bplsim.execute.folders import DataRoot
    from bplsim.execute.sites import load_site
    from bplsim.store.retention import gc as do_gc
    root = DataRoot(data_root_for(find_project(project), data, load_site(site)))
    typer.echo(json.dumps(do_gc(root, older_than_days, dry_run)))


@app.command()
def pin(run_or_case: str, off: bool = typer.Option(False, "--off"),
        project: Optional[Path] = typer.Option(None, "--project", "-p"),
        data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Keep a case's raw output (by run or case hash); --off to release it."""
    from bplsim.execute.folders import DataRoot
    from bplsim.execute.sites import load_site
    from bplsim.store.retention import pin as do_pin
    root = DataRoot(data_root_for(find_project(project), data, load_site(site)))
    typer.echo(f"{'unpinned' if off else 'pinned'} {do_pin(root, run_or_case, not off)}")


@study_app.command("show-row")
def study_show_row(study: Path, row: int, project: Optional[Path] = typer.Option(None, "--project", "-p"),
                   data: Optional[Path] = typer.Option(None, "--data"),
                   site: Optional[str] = typer.Option(None, "--site")):
    """Resolved values of one row of a study (from its library snapshot), with origins and checks."""
    from bplsim.model.resolve import Resolver
    from bplsim.study.spec import row_spec
    d = _driver(study, project, data, site, None)
    rows = d.db.query("SELECT * FROM rows WHERE study_id=? AND row_id=?", [d.study_id, row])
    if not rows:
        raise typer.BadParameter(f"no row {row} in {d.study_id}")
    r = d._row_from_db(rows[0])
    res = Resolver(d.project, d.spec.design, row_spec(d.spec, r.values), d.pipeline.fidelity_spec())
    des = res.resolve()
    typer.echo(f"row {row} of {d.study_id}: {json.dumps(r.values)}  status {r.status} {r.reason}")
    w = max(len(p) for p, _, _ in des.show())
    for p, v, o in des.show():
        typer.echo(f"{p:<{w}}  {v:<22} <- {o}")


@app.command()
def plot(figure_id: str, out: Path = typer.Option(..., "--out", "-o"),
         param: list[str] = typer.Option([], "--param", help="key=value (YAML value), repeatable"),
         project: Optional[Path] = typer.Option(None, "--project", "-p"),
         data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Render a registered figure from stored results."""
    from ruamel.yaml import YAML
    from bplsim.results.analysis import Results
    from bplsim.figures import render
    from bplsim.model.project import Project
    from bplsim.execute.sites import load_site
    pdir = find_project(project)
    pr = Project.load(pdir)
    params = {}
    for kv in param:
        k, _, v = kv.partition("=")
        params[k] = YAML(typ="safe").load(v)
    res = Results(data_root_for(pdir, data, load_site(site)), pr.units)
    typer.echo(render(pr, res, figure_id, params, out))


sync_app = typer.Typer(no_args_is_help=True, help="Move results between sites (ssh + tar).")
app.add_typer(sync_app, name="sync")


@sync_app.command("pull")
def sync_pull(site: str = typer.Option(..., "--site"), study: Optional[str] = typer.Option(None, "--study"),
              with_raw: bool = typer.Option(False, "--with-raw"),
              project: Optional[Path] = typer.Option(None, "--project", "-p"),
              data: Optional[Path] = typer.Option(None, "--data")):
    """Copy finished case/run folders (and optionally a study folder) from a remote site, then collect."""
    from bplsim.execute.folders import DataRoot
    from bplsim.execute.sync import pull
    from bplsim.model.project import Project
    from bplsim.execute.sites import load_site
    from bplsim.store.collect import collect as do_collect
    from bplsim.store.db import DB
    pdir = find_project(project)
    name = Project.load(pdir).name
    local = data_root_for(pdir, data, load_site(None))
    n = pull(load_site(site), name, local, with_raw, study)
    root = DataRoot(local)
    db = DB(root.db_path)
    typer.echo(f"pulled {n} folder(s); collected {do_collect(root, db)}")
    db.close()


report_app = typer.Typer(no_args_is_help=True, help="Reports regenerated from stored results.")
app.add_typer(report_app, name="report")


@report_app.command("build")
def report_build(template: Path, project: Optional[Path] = typer.Option(None, "--project", "-p"),
                 data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site")):
    """Render a report template (<name>.md.j2) into <name>.md with its figures."""
    from bplsim.results.analysis import Results
    from bplsim.model.project import Project
    from bplsim.results.report import build
    from bplsim.execute.sites import load_site
    from bplsim.core.errors import BplsimError
    pdir = find_project(project or template.parent)
    pr = Project.load(pdir)
    res = Results(data_root_for(pdir, data, load_site(site)), pr.units)
    try:
        typer.echo(f"wrote {build(pr, res, template)}")
    except (BplsimError, KeyError, ValueError) as e:     # e.g. a study the template reads has not been run
        msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        _fail(Exception(f"{template}: {msg} (run the studies the template reads first)"))


@app.command()
def init(directory: Path, name: Optional[str] = typer.Option(None)):
    """Create a new project skeleton."""
    from bplsim.cli.check import init_project
    init_project(directory, name or directory.name)
    typer.echo(f"created project in {directory}")


@lib_app.command("fork")
def lib_fork(entry: str, into: str = typer.Option(..., "--into"),
             project: Optional[Path] = typer.Option(None, "--project", "-p")):
    """Copy an entry from an included library into this project's library."""
    from bplsim.cli.check import fork_entry
    path = fork_entry(find_project(project), entry, into)
    typer.echo(f"forked {entry} -> {path}")


def main():
    app()


if __name__ == "__main__":
    main()
