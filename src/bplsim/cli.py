"""The bplsim command line (plan §13)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__

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
    from .project import Project
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
    from .bplcheck import check_project
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
    from .checks import prescreen
    from .project import Project
    from .resolve import Resolver
    from .errors import BplsimError
    try:
        pr = Project.load(find_project(project))
        fid = None
        if pipeline:
            from .pipeline import load_pipeline
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
    from .sites import load_site
    from .study.driver import Driver
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
    from .errors import BplsimError
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
    from .errors import BplsimError
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
    from .store.query import study_table
    d = _driver(study, project, data, site, None)
    df = study_table(d.db, d.study_id)
    typer.echo(json.dumps(d.summary(), indent=1))
    if len(df):
        typer.echo(df.head(20).to_string())


@app.command("run-task")
def run_task_cmd(task: Path, jobs: Optional[str] = typer.Option(None, "--jobs")):
    """Worker entry point: run the jobs of a task file (used by executors)."""
    from .execute.runtask import run_task
    out = run_task(task, jobs)
    typer.echo(json.dumps(out))


@app.command()
def collect(project: Optional[Path] = typer.Option(None, "--project", "-p"),
            data: Optional[Path] = typer.Option(None, "--data"), site: Optional[str] = typer.Option(None, "--site"),
            rebuild: bool = typer.Option(False, "--rebuild")):
    """Index case and run folders into the trade database."""
    from .execute.folders import DataRoot
    from .sites import load_site
    from .store.collect import collect as do_collect, rebuild as do_rebuild
    from .store.db import DB
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
    from .execute.folders import DataRoot
    from .project import Project
    from .sites import load_site
    from .store.db import DB
    from .store.query import query as do_query
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
def init(directory: Path, name: Optional[str] = typer.Option(None)):
    """Create a new project skeleton."""
    from .bplcheck import init_project
    init_project(directory, name or directory.name)
    typer.echo(f"created project in {directory}")


@lib_app.command("fork")
def lib_fork(entry: str, into: str = typer.Option(..., "--into"),
             project: Optional[Path] = typer.Option(None, "--project", "-p")):
    """Copy an entry from an included library into this project's library."""
    from .bplcheck import fork_entry
    path = fork_entry(find_project(project), entry, into)
    typer.echo(f"forked {entry} -> {path}")


def main():
    app()


if __name__ == "__main__":
    main()
