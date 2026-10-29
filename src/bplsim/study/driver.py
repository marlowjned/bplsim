"""The study driver (plan §9.5): ask -> resolve + pre-screen + hash -> runsheet -> jobs -> execute ->
collect -> tell, round after round, resumable at any point."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from ..checks import prescreen
from ..errors import BplsimError, ConfigError, ErrorList, ExpressionError, ResolveError
from ..execute.folders import DataRoot, read_json, write_json
from ..execute.local import LocalExecutor, TaskSpec, pack, write_task
from ..hashing import content_hash, major_minor
from ..measure.engine import (MeasurementSet, call_design_metric, define_measurements, evaluate_metric,
                              load_measurement_set, reads_paths)
from ..pipeline import load_pipeline
from ..project import Project
from ..resolve import Resolver
from ..store.collect import collect
from ..store.db import DB, split_value
from ..units import DIMS, dim_of
from .samplers import RowResult, make_sampler
from .spec import StudySpec, load_study, row_spec


@dataclass
class Row:
    row_id: int
    round: int
    origin: str
    values: dict
    status: str = "pending"            # pending | invalid | done | failed
    reason: str = ""
    case_hash: str = ""
    run_hash: str = ""
    pinned: bool = False
    params: dict = field(default_factory=dict)
    prescreen: Any = None
    job_case: dict | None = None
    job_run: dict | None = None
    design_metrics: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)          # stage -> {case_hash, run_hash, job_case, job_run}


def _git_commit(path: Path) -> tuple[str, bool]:
    import subprocess
    try:
        c = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, timeout=10)
        d = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True, timeout=10)
        return c.stdout.strip(), bool(d.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return "", False


def _tree_hash(dirs: list[Path]) -> str:
    h = hashlib.sha256()
    for d in dirs:
        for f in sorted(p for p in Path(d).rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            h.update(str(f.relative_to(d)).replace("\\", "/").encode())
            h.update(f.read_bytes())
    return h.hexdigest()


class Driver:
    def __init__(self, project_dir: str | Path, study_file: str | Path, data_root: str | Path,
                 executor=None, refresh_snapshot: bool = False, log=print):
        self.project_dir = Path(project_dir).resolve()
        self.study_file = Path(study_file).resolve()
        self.root = DataRoot(data_root)
        self.executor = executor or LocalExecutor()
        self.log = log
        self.refresh = refresh_snapshot
        self.live = Project.load(self.project_dir)
        self.study_id, self.study_dir, self.snapshot = self._study_folder()
        self.project = Project.load(self.snapshot)
        self.spec: StudySpec = load_study(self.project, self.study_dir / "spec.yaml")
        self.spec.name = self.study_file.stem
        self.pipeline = load_pipeline(self.project, self.spec.pipeline)
        self.order = self.pipeline.order()
        self.stage_name = self.order[-1]
        self.stage = self.pipeline.stages[self.order[0]]
        self.ms = load_measurement_set(self.project, self.spec.measure_use, self.spec.measure_add)
        self.db = DB(self.root.db_path)
        self.state_path = self.study_dir / "sampler_state.json"

    # ---- study folder and library snapshot -------------------------------------------------------
    def _library_dirs(self) -> dict[str, Path]:
        from ..project import STD_ROOT
        return {ns: lib.root for ns, lib in self.live.libraries.items() if lib.root != STD_ROOT}

    def _study_folder(self) -> tuple[str, Path, Path]:
        libs = self._library_dirs()
        snap_hash = _tree_hash(list(libs.values()) + [self.project_dir / "project.yaml"])
        spec_text = self.study_file.read_text()
        spec_hash = hashlib.sha256(spec_text.encode()).hexdigest()
        base = self.root.root / "studies"
        base.mkdir(parents=True, exist_ok=True)
        for d in sorted(base.glob(f"*_{self.study_file.stem}*")):
            info = d / "study.json"
            if info.exists():
                meta = read_json(info)
                if meta["spec_hash"] == spec_hash and meta["snapshot_hash"] == snap_hash and not self.refresh:
                    return d.name, d, d / "snapshot"
                if meta["spec_hash"] == spec_hash and meta["snapshot_hash"] != snap_hash and not self.refresh:
                    self.log(f"note: the library changed since study {d.name} started; it keeps using its "
                             "snapshot. Use --refresh-snapshot to start a new study with the current library.")
                    return d.name, d, d / "snapshot"
        stamp = _dt.date.today().isoformat()
        sid, n = f"{stamp}_{self.study_file.stem}", 1
        while (base / sid).exists():
            n += 1
            sid = f"{stamp}_{self.study_file.stem}_{n}"
        d = base / sid
        snap = d / "snapshot"
        (snap / "libs").mkdir(parents=True)
        cfg = (self.project_dir / "project.yaml").read_text()
        own = self.live.namespace
        for ns, src in libs.items():
            dst = snap / "library" if ns == own else snap / "libs" / ns
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # included libraries now live under snapshot/libs
        from ruamel.yaml import YAML
        y = YAML()
        data = y.load(cfg)
        for ns, spec in (data.get("libraries") or {}).items():
            if ns in libs and ns != own and not (spec or {}).get("builtin"):
                data["libraries"][ns] = {"path": f"libs/{ns}"}
        with open(snap / "project.yaml", "w") as fh:
            y.dump(data, fh)
        shutil.copy(self.study_file, d / "spec.yaml")
        commit, dirty = _git_commit(self.project_dir)
        write_json(d / "study.json", {"study_id": sid, "spec_hash": spec_hash, "snapshot_hash": snap_hash,
                                      "created": time.time(), "bplsim": __version__, "project_commit": commit,
                                      "dirty": dirty, "study_file": str(self.study_file)})
        return sid, d, snap

    # ---- provenance --------------------------------------------------------------------------------
    def provenance(self) -> dict:
        meta = read_json(self.study_dir / "study.json")
        return {"study": self.study_id, "bplsim": __version__, "project_commit": meta.get("project_commit"),
                "dirty": meta.get("dirty"), "snapshot": meta.get("snapshot_hash")}

    # ---- rows ---------------------------------------------------------------------------------------
    def _output_dim(self, value: str, mdefs) -> Any:
        alias, _, out = value.partition(".")
        md = mdefs.get(alias)
        if md is None:
            raise ConfigError(f"no metric alias {alias!r} (have: {', '.join(mdefs)})")
        unit = (md.outputs or {}).get(out, "") if isinstance(md.outputs, dict) else ""
        if unit in ("", "1", "%", "text"):
            return None
        return dim_of(self.project.units.parse(f"1 {unit}"))

    def _limit_si(self, raw, d):
        if raw is None:
            return None
        return self.project.units.to_si(raw, d) if d is not None else float(raw)

    def build_row(self, row: Row) -> Row:
        spec = self.spec
        rs = row_spec(spec, row.values)
        try:
            res = Resolver(self.project, spec.design, rs, self.pipeline.fidelity_spec())
            design = res.resolve()
        except (ResolveError, ExpressionError, ErrorList) as e:
            row.status, row.reason = "invalid", f"resolve: {e}"
            return row
        ps = prescreen(design, design.checks_spec)
        row.prescreen = ps
        pdefs, mdefs = define_measurements(self.project, design, self.ms)
        last = self.order[-1]
        for d_ in list(pdefs.values()) + list(mdefs.values()):
            if d_.stage is None:
                d_.stage = last
            elif d_.stage not in self.pipeline.stages:
                raise ConfigError(f"measurement {d_.alias}: no stage {d_.stage!r} in {self.pipeline.id}")
        norm_paths = set(spec.normalize["scale"]) if spec.normalize else set()
        for alias, md in mdefs.items():
            if md.design_only:
                reads = reads_paths(self.project, design, md)
                if not (norm_paths & set(reads)):
                    row.design_metrics[alias] = evaluate_metric(self.project, design, md, {})
        reasons = [f"{i.name} ({i.detail})" if i.detail else i.name for i in ps.failures]
        for cname, c in spec.constraints.items():
            alias, _, out = c.value.partition(".")
            if alias in row.design_metrics:
                v = row.design_metrics[alias][out]
                d = self._output_dim(c.value, mdefs)
                if self._slack(v, c, d) < -1e-12:
                    reasons.append(f"constraint {cname}: {c.value} = {self._show(v, d)}")
        if reasons:
            row.status, row.reason = "invalid", "; ".join(reasons)
            return row
        for expr in spec.pin:
            try:
                if design.evaluate(expr)[0]:
                    row.pinned = True
            except BplsimError as e:
                raise ConfigError(f"pin expression {expr!r}: {e}") from None
        normalize = None
        norm_stage = None
        if spec.normalize:
            d = self._output_dim(spec.normalize["value"], mdefs)
            normalize = {"scale": spec.normalize["scale"], "value": spec.normalize["value"],
                         "target_si": self._limit_si(spec.normalize["equals"], d)}
            norm_stage = mdefs[spec.normalize["value"].split(".")[0]].stage
        canon = design.canonical()
        row.params = dict(canon["values"])
        prov = self.provenance()
        for sname in self.order:
            st = self.pipeline.stages[sname]
            cfg = st.config(design)
            issues = st.backend.check(design, cfg)
            if issues:
                row.status, row.reason = "invalid", f"backend ({sname}): " + "; ".join(issues)
                return row
            try:
                inputs = st.backend.solve_inputs(design, cfg)
            except BplsimError as e:
                row.status, row.reason = "invalid", f"backend ({sname}): {e}"
                return row
            # hand-offs from earlier stages: hashed by the upstream run, located at execution time
            if st.inputs:
                inputs["upstream"], inputs["_upstream_files"] = {}, {}
                for key, ref in st.inputs.items():
                    up, kind, name = (ref.split(".") + ["", ""])[:3]
                    if kind != "exports" or up not in row.stages:
                        raise ConfigError(f"stage {sname}: input {key} = {ref!r} must be <earlier stage>.exports.<name>")
                    inputs["upstream"][key] = {"stage": up, "run": row.stages[up]["run_hash"], "export": name}
                    inputs["_upstream_files"][key] = str(self.root.run_dir(row.stages[up]["run_hash"]) / "exports"
                                                         / f"{name}.h5")
            exp_defs = {}
            if st.exports:
                exp_ms = MeasurementSet(probes={n: {"probe": e["probe"], "with": dict(e.get("with") or {}),
                                                    "stage": sname} for n, e in st.exports.items()})
                exp_defs, _ = define_measurements(self.project, design, exp_ms)
            stage_pdefs = [p for p in pdefs.values() if p.stage == sname] + list(exp_defs.values())
            stage_mdefs = [m for m in mdefs.values() if m.stage == sname]
            bases = [b.canonical() for b in st.backend.bases(design, cfg, inputs)]
            hashed = {k: v for k, v in inputs.items() if not k.startswith("_")}
            case_hash = content_hash({"backend": st.backend.name, "version": major_minor(st.backend.version),
                                      "inputs": hashed, "bases": bases})
            st_norm = normalize if norm_stage == sname else None
            run_hash = content_hash({"case": case_hash, "design": canon, "normalize": st_norm, "stage": sname,
                                     "metrics": sorted(m.def_hash for m in stage_mdefs),
                                     "exports": sorted(p.def_hash for p in exp_defs.values())})
            job_case = {"type": "case", "case_hash": case_hash, "stage": sname, "backend": st.backend_spec,
                        "inputs": inputs, "bases": bases, "design": canon,
                        "probes": [p.canonical() for p in stage_pdefs],
                        "resources": dict(st.resources), "retention": dict(spec.retention), "pinned": row.pinned,
                        "needs_raw": getattr(st.backend, "measure_needs_raw", True), "provenance": prov}
            job_run = {"type": "run", "run_hash": run_hash, "case_hash": case_hash, "stage": sname,
                       "design": canon, "bases": bases, "metrics": [m.canonical() for m in stage_mdefs],
                       "exports": [{"name": n, "hash": d.def_hash} for n, d in exp_defs.items()],
                       "normalize": st_norm, "superposed": st.backend.superposed(cfg), "provenance": prov}
            row.stages[sname] = {"case_hash": case_hash, "run_hash": run_hash, "job_case": job_case,
                                 "job_run": job_run}
        row.case_hash = row.stages[last]["case_hash"]
        row.run_hash = row.stages[last]["run_hash"]
        row.status = "pending"
        return row

    def _slack(self, v, c, d) -> float:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return -math.inf
        lo, hi = self._limit_si(c.lo, d), self._limit_si(c.hi, d)
        s = math.inf
        if lo is not None:
            s = min(s, float(v) - lo)
        if hi is not None:
            s = min(s, hi - float(v))
        return s

    def _show(self, v, d):
        return self.project.units.show(float(v), d) if d is not None and isinstance(v, (int, float)) else str(v)

    # ---- execution ------------------------------------------------------------------------------------
    def execute(self, rows: list[Row], round_no: int) -> None:
        for i, sname in enumerate(self.order):
            active = []
            for r in rows:
                if r.status != "pending":
                    continue
                if i > 0:
                    up = self.order[i - 1]
                    if not self.root.done(self.root.run_dir(r.stages[up]["run_hash"])):
                        r.status = "failed"
                        r.reason = f"upstream stage {up} did not finish"
                        continue
                active.append(r)
            self._execute_stage(active, round_no, sname)

    def _execute_stage(self, rows: list[Row], round_no: int, sname: str) -> None:
        st = self.pipeline.stages[sname]
        cases: dict[str, dict] = {}
        runs: dict[str, dict] = {}
        for r in rows:
            info = r.stages[sname]
            cj = cases.get(info["case_hash"])
            if cj is None:
                cases[info["case_hash"]] = json.loads(json.dumps(info["job_case"]))
            else:
                have = {p["hash"] for p in cj["probes"]}
                cj["probes"] += [p for p in info["job_case"]["probes"] if p["hash"] not in have]
                cj["pinned"] = cj["pinned"] or r.pinned
            if not self.root.done(self.root.run_dir(info["run_hash"])):
                runs[info["run_hash"]] = info["job_run"]
        need_case = []
        from ..execute.runtask import _measured
        for h, cj in cases.items():
            d = self.root.case_dir(h)
            if self.root.done(d) and all(p["hash"] in _measured(d) for p in cj["probes"]):
                continue
            need_case.append(cj)
        n_cached = len(cases) - len(need_case)
        tag = f" [{sname}]" if len(self.order) > 1 else ""
        self.log(f"round {round_no}{tag}: {len(rows)} rows, {len(cases)} cases ({n_cached} cached), "
                 f"{len(runs)} runs to compute")
        if not need_case and not runs:
            return
        res = st.resources
        for attempt in range(2):
            jobs_by_case: dict[str, list] = {cj["case_hash"]: [cj] for cj in need_case}
            orphan_runs = []
            for rj in runs.values():
                if rj["case_hash"] in jobs_by_case:
                    jobs_by_case[rj["case_hash"]].append(rj)
                elif not self.root.done(self.root.run_dir(rj["run_hash"])):
                    orphan_runs.append(rj)
            groups = list(jobs_by_case.values())
            n_slots = self.executor.capacity(int(res.get("cores", 1)), float(res.get("memory", 0)))
            runtime = self._runtime_estimate(st)
            sizes = self.executor.partition(len(groups), n_slots, runtime, res)
            tasks, i = [], 0
            tdir = self.study_dir / "rounds" / str(round_no) / f"{sname}_attempt{attempt}"
            timeout = res.get("timeout")
            for k, size in enumerate(sizes):
                jobs = [j for g in groups[i:i + size] for j in g]
                i += size
                p = write_task(tdir / f"task{k:04d}.json", self.snapshot, self.root.root, jobs)
                tasks.append(TaskSpec(p, len(jobs), timeout=(timeout * (2 ** attempt) * size) if timeout else None))
            if orphan_runs:
                p = write_task(tdir / "task_runs.json", self.snapshot, self.root.root, orphan_runs)
                tasks.append(TaskSpec(p, len(orphan_runs)))
            outcomes = self.executor.run(tasks, parallel=n_slots)
            retry = [cj for cj in need_case if not self.root.done(self.root.case_dir(cj["case_hash"]))
                     and not (self.root.failed_dir(cj["case_hash"]) / "status.json").exists()]
            bad = [o for o in outcomes if o.timed_out or (o.returncode not in (0, None))]
            if attempt == 0 and retry:
                self.log(f"  {len(retry)} case(s) left no result ({len(bad)} task(s) timed out or crashed); retrying once")
                need_case = retry
                runs = {h: rj for h, rj in runs.items() if not self.root.done(self.root.run_dir(h))}
                continue
            for cj in retry:
                kind = "timeout" if any(o.timed_out for o in outcomes) else "crashed"
                fd = self.root.failed_dir(cj["case_hash"])
                fd.mkdir(parents=True, exist_ok=True)
                write_json(fd / "status.json", {"status": kind, "reason": f"no result after retry ({kind})"})
            leftover = [rj for rj in runs.values() if not self.root.done(self.root.run_dir(rj["run_hash"]))
                        and not (self.root.failed_dir(rj["run_hash"]) / "status.json").exists()]
            if leftover:
                from ..execute.runtask import run_run
                for rj in leftover:
                    run_run(self.project, self.root, rj)
            break

    def _runtime_estimate(self, st=None) -> float:
        st = st or self.pipeline.stages[self.order[0]]
        rows = self.db.query("SELECT AVG(wall_s) AS w FROM cases WHERE backend = ? AND status='done'",
                             [st.backend.name])
        w = rows[0]["w"] if rows else None
        return float(w) if w else float(st.resources.get("runtime_hint", 10.0))

    # ---- results --------------------------------------------------------------------------------------
    def result(self, row: Row) -> RowResult:
        if row.status == "invalid":
            return RowResult(row.row_id, row.values, "invalid")
        run_hashes = [v["run_hash"] for v in row.stages.values()] if row.stages else [row.run_hash]
        m = {}
        for h in run_hashes:
            d = self.root.run_dir(h)
            if not self.root.done(d):
                f = self.root.failed_dir(h) / "status.json"
                row.status = "failed"
                row.reason = row.reason or (read_json(f).get("reason", "") if f.exists() else "no result")
                return RowResult(row.row_id, row.values, "failed")
            m.update(read_json(d / "metrics.json"))
        vals = {k: v["value"] for k, v in m.items()}
        objectives = {name: vals.get(o.value) for name, o in self.spec.objectives.items()}
        constraints = {}
        for name, c in self.spec.constraints.items():
            unit = m.get(c.value, {}).get("unit", "")
            d_ = None if unit in ("", "1", "%", "text") else dim_of(self.project.units.parse(f"1 {unit}"))
            constraints[name] = self._slack(vals.get(c.value), c, d_)
        row.status = "done"
        return RowResult(row.row_id, row.values, "done", objectives, constraints)

    # ---- bookkeeping ----------------------------------------------------------------------------------
    def _record(self, rows: list[Row]):
        db = self.db
        for r in rows:
            db.upsert("rows", {"study_id": self.study_id, "row_id": r.row_id, "round": r.round, "origin": r.origin,
                               "status": r.status, "invalid_reason": r.reason or None})
            for k, v in r.values.items():
                num, text = split_value(v)
                var = self.spec.variables[k]
                db.upsert("row_values", {"study_id": self.study_id, "row_id": r.row_id, "name": k, "value_num": num,
                                         "value_text": text, "unit": var.unit})
            for sname, info in (r.stages or {}).items():
                db.upsert("row_runs", {"study_id": self.study_id, "row_id": r.row_id, "stage": sname,
                                       "run_id": info["run_hash"], "case_id": info["case_hash"],
                                       "stage_index": self.order.index(sname)})
        db.commit()
        self._write_runsheet()

    def _write_runsheet(self):
        import pandas as pd
        rows = self.db.query("SELECT * FROM rows WHERE study_id=? ORDER BY row_id", [self.study_id])
        vals = self.db.query("SELECT * FROM row_values WHERE study_id=?", [self.study_id])
        rr = {r["row_id"]: (r["case_id"], r["run_id"]) for r in
              self.db.query("SELECT * FROM row_runs WHERE study_id=?", [self.study_id])}
        table = {r["row_id"]: {"row_id": r["row_id"], "round": r["round"], "origin": r["origin"],
                               "status": r["status"], "reason": r["invalid_reason"]} for r in rows}
        for v in vals:
            table[v["row_id"]][v["name"]] = v["value_num"] if v["value_num"] is not None else v["value_text"]
        for rid, (c, r) in rr.items():
            table[rid]["case"], table[rid]["run"] = c, r
        df = pd.DataFrame(list(table.values()))
        df.to_parquet(self.study_dir / "runsheet.parquet", index=False)

    def _history(self) -> list[RowResult]:
        out = []
        for r in self.db.query("SELECT * FROM rows WHERE study_id=? ORDER BY row_id", [self.study_id]):
            row = self._row_from_db(r)
            out.append(self.result(row) if row.status != "invalid" else RowResult(row.row_id, row.values, "invalid"))
        return out

    def _row_from_db(self, r) -> Row:
        vals = {v["name"]: (v["value_num"] if v["value_num"] is not None else v["value_text"]) for v in
                self.db.query("SELECT * FROM row_values WHERE study_id=? AND row_id=?", [self.study_id, r["row_id"]])}
        for k, var in self.spec.variables.items():
            if k in vals and var.kind == "continuous" and var.integer:
                vals[k] = int(vals[k])
            elif k in vals and var.kind == "discrete" and var.values and isinstance(var.values[0], int):
                vals[k] = int(vals[k])
        runs = self.db.query("SELECT * FROM row_runs WHERE study_id=? AND row_id=?", [self.study_id, r["row_id"]])
        row = Row(r["row_id"], r["round"], r["origin"], vals, r["status"], r["invalid_reason"] or "")
        for x in runs:
            row.stages[x["stage"]] = {"case_hash": x["case_id"], "run_hash": x["run_id"]}
            if x["stage"] == self.stage_name:
                row.case_hash, row.run_hash = x["case_id"], x["run_id"]
        return row

    def _register(self):
        meta = read_json(self.study_dir / "study.json")
        self.db.upsert("studies", {"study_id": self.study_id, "spec_path": str(self.study_file),
                                   "spec_hash": meta["spec_hash"], "spec_yaml": (self.study_dir / "spec.yaml").read_text(),
                                   "snapshot_hash": meta["snapshot_hash"], "created": meta["created"],
                                   "bplsim_version": meta["bplsim"], "project_commit": meta.get("project_commit"),
                                   "production": int(self.spec.production)})
        self.db.commit()
        if self.spec.production and meta.get("dirty"):
            raise ConfigError("this is a production study, but the project's git tree was dirty when it started; "
                              "commit first (or remove production: true)")

    # ---- main loop ------------------------------------------------------------------------------------
    def run(self, one_round: bool = False) -> dict:
        self._register()
        spec = self.spec
        sampler_cfg = dict(spec.sampler)
        sampler_cfg["_base"] = str(self.study_file.parent)
        sampler = make_sampler(spec.variables, sampler_cfg, spec.objectives)
        state = read_json(self.state_path) if self.state_path.exists() else {}
        history = self._history() if state else []
        if state:
            sampler.restore(state.get("sampler", {}), [h for h in history if h.row_id in set(state.get("told", []))])
        told = set(state.get("told", []))
        # finish an interrupted round first
        pending = [self._row_from_db(r) for r in self.db.query(
            "SELECT * FROM rows WHERE study_id=? ORDER BY row_id", [self.study_id]) if r["row_id"] not in told]
        round_no = max([r["round"] for r in self.db.query("SELECT round FROM rows WHERE study_id=?",
                                                          [self.study_id])] or [-1])
        next_id = max([r["row_id"] for r in self.db.query("SELECT row_id FROM rows WHERE study_id=?",
                                                          [self.study_id])] or [-1]) + 1
        budget = spec.budget
        rounds_done = 0
        while True:
            if pending:
                rows = [self.build_row(Row(r.row_id, r.round, r.origin, r.values)) for r in pending]
                pending = []
            else:
                if sampler.finished():
                    break
                n_solved = len(self.db.query("SELECT 1 FROM rows WHERE study_id=? AND status IN ('done','failed')",
                                             [self.study_id]))
                n_invalid = len(self.db.query("SELECT 1 FROM rows WHERE study_id=? AND status='invalid'",
                                              [self.study_id]))
                if budget.get("runs") and n_solved >= budget["runs"]:
                    break
                if budget.get("max_invalid") and n_invalid >= budget["max_invalid"]:
                    self.log("stopping: max_invalid reached")
                    break
                if budget.get("max_rounds") and round_no + 1 >= budget["max_rounds"]:
                    break
                n = None
                if budget.get("runs") and not sampler.one_shot:
                    n = min(int(sampler_cfg.get("round_size", 8)), budget["runs"] - n_solved)
                asked = sampler.ask(n)
                if not asked:
                    break
                round_no += 1
                rows = []
                for v in asked:
                    rows.append(self.build_row(Row(next_id, round_no, sampler_cfg["kind"], v)))
                    next_id += 1
            self._record(rows)
            self.execute(rows, round_no)
            collect(self.root, self.db)
            results = [self.result(r) for r in rows]
            self._record(rows)
            sampler.tell(results)
            told |= {r.row_id for r in rows}
            write_json(self.state_path, {"sampler": sampler.state(), "told": sorted(told)})
            rounds_done += 1
            if one_round:
                break
        return self.summary()

    def summary(self) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM rows WHERE study_id=? GROUP BY status", [self.study_id])
        return {"study": self.study_id, "data_root": str(self.root.root), **{r["status"]: r["n"] for r in rows}}

    def plan(self, max_rows: int = 10000) -> dict:
        """Dry run: resolve and pre-screen the first round; report validity, cache hits and work."""
        spec = self.spec
        cfg = dict(spec.sampler)
        cfg["_base"] = str(self.study_file.parent)
        sampler = make_sampler(spec.variables, cfg, spec.objectives)
        asked = sampler.ask(None)[:max_rows]
        rows = [self.build_row(Row(i, 0, cfg["kind"], v)) for i, v in enumerate(asked)]
        valid = [r for r in rows if r.status == "pending"]
        cases = {r.stages[self.order[0]]["case_hash"] for r in valid}
        cached = {h for h in cases if self.root.done(self.root.case_dir(h))}
        fails: dict[str, int] = {}
        for r in rows:
            if r.status == "invalid":
                key = r.reason.split(" (")[0].split(":")[0] if r.reason else "?"
                fails[key] = fails.get(key, 0) + 1
        res = self.stage.resources
        n_slots = self.executor.capacity(int(res.get("cores", 1)), float(res.get("memory", 0)))
        runtime = self._runtime_estimate(self.stage)
        todo = len(cases) - len(cached)
        sizes = self.executor.partition(todo, n_slots, runtime, res)
        return {"study": self.study_id, "rows": len(rows), "valid": len(valid), "invalid": len(rows) - len(valid),
                "invalid_by_check": fails, "cases": len(cases), "cached_cases": len(cached),
                "runtime_estimate_s": runtime, "slots": n_slots, "tasks": len(sizes),
                "estimated_wall_s": (max(sizes) / n_slots * runtime if sizes else 0.0) if sizes else 0.0,
                "rows_detail": rows}
