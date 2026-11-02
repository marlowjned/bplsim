"""Samplers: batch ask/tell (plan §9.3).

Values are in study-variable space (display units, or choice strings). tell() receives RowResult
objects; invalid and failed rows are infeasible. state() + the history in the database restore a
sampler after an interruption.
"""
from __future__ import annotations

import csv
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from bplsim.core.errors import ConfigError
from bplsim.study.spec import Variable


@dataclass
class RowResult:
    row_id: int
    values: dict
    status: str                              # done | invalid | failed
    objectives: dict = field(default_factory=dict)       # name -> value (as stored; minimize/maximize applied by sampler)
    constraints: dict = field(default_factory=dict)      # name -> slack (>= 0 ok)

    @property
    def feasible(self) -> bool:
        return self.status == "done" and all(s >= -1e-12 for s in self.constraints.values())


def _from_unit(var: Variable, u: float):
    """Map u in [0, 1) to a value of the variable."""
    u = min(max(u, 0.0), 1 - 1e-12)
    if var.kind == "continuous":
        if var.log:
            v = math.exp(math.log(var.lo) + u * (math.log(var.hi) - math.log(var.lo)))
        else:
            v = var.lo + u * (var.hi - var.lo)
        return int(round(v)) if var.integer else float(v)
    return var.values[int(u * len(var.values))]


class Sampler:
    one_shot = True

    def __init__(self, variables: dict[str, Variable], cfg: dict, objectives: dict):
        self.vars = variables
        self.cfg = cfg
        self.objectives = objectives
        self.issued = 0
        self._done = False

    def ask(self, n: int | None = None) -> list[dict]:
        raise NotImplementedError

    def tell(self, results: list[RowResult]) -> None:
        pass

    def finished(self) -> bool:
        return self._done

    def state(self) -> dict:
        return {"issued": self.issued, "done": self._done}

    def restore(self, state: dict, history: list[RowResult]) -> None:
        self.issued = state.get("issued", 0)
        self._done = state.get("done", False)


class FixedSampler(Sampler):
    """A sampler whose rows are known up front (one round)."""

    def points(self) -> list[dict]:
        raise NotImplementedError

    def ask(self, n=None):
        if self._done:
            return []
        self._done = True
        pts = self.points()
        self.issued = len(pts)
        return pts


class Grid(FixedSampler):
    def points(self):
        names = self.cfg.get("vars") or list(self.vars)
        levels = self.cfg.get("levels", 5)
        axes = []
        for n in names:
            v = self.vars[n]
            if v.kind == "continuous":
                k = levels.get(n, 5) if isinstance(levels, dict) else int(levels)
                if v.log:
                    vals = list(np.exp(np.linspace(math.log(v.lo), math.log(v.hi), k)))
                else:
                    vals = list(np.linspace(v.lo, v.hi, k))
                vals = [int(round(x)) if v.integer else float(x) for x in vals]
                axes.append(list(dict.fromkeys(vals)))
            else:
                axes.append(list(v.values))
        return [dict(zip(names, combo)) for combo in itertools.product(*axes)]


class Listed(FixedSampler):
    def points(self):
        rows = self.cfg.get("rows")
        if rows is None and "csv" in self.cfg:
            with open(Path(self.cfg["_base"]) / self.cfg["csv"], newline="") as fh:
                rows = [dict(r) for r in csv.DictReader(fh)]
        if not rows:
            raise ConfigError("list sampler needs 'rows' or 'csv'")
        out = []
        for r in rows:
            row = {}
            for n, v in self.vars.items():
                if n not in r:
                    raise ConfigError(f"list sampler row lacks variable {n!r}")
                x = r[n]
                if v.kind == "continuous":
                    x = float(x)
                    x = int(round(x)) if v.integer else x
                elif v.kind == "discrete":
                    x = type(v.values[0])(x) if v.values else x
                row[n] = x
            out.append(row)
        return out


class QMC(FixedSampler):
    def points(self):
        from scipy.stats import qmc
        names = self.cfg.get("vars") or list(self.vars)
        n = int(self.cfg.get("n", 16))
        seed = self.cfg.get("seed")
        d = len(names)
        if self.cfg["kind"] == "sobol":
            eng = qmc.Sobol(d, scramble=True, seed=seed)
            u = eng.random(n)
        else:
            u = qmc.LatinHypercube(d, seed=seed).random(n)
        return [{nm: _from_unit(self.vars[nm], u[i, j]) for j, nm in enumerate(names)} for i in range(n)]


class Product(FixedSampler):
    def points(self):
        parts = [make_sampler({k: v for k, v in self.vars.items() if k in (c.get("vars") or list(self.vars))},
                              c, self.objectives).points() for c in self.cfg["of"]]
        out = []
        for combo in itertools.product(*parts):
            row = {}
            for p in combo:
                row.update(p)
            out.append(row)
        missing = set(self.vars) - set(out[0] if out else {})
        if missing:
            raise ConfigError(f"product sampler: variables {sorted(missing)} are not covered by any part")
        return out


def _score(r: RowResult, objectives: dict) -> float:
    (name, obj), = objectives.items()
    v = r.objectives.get(name)
    if v is None or not math.isfinite(v):
        return math.inf
    return v if obj.direction == "minimize" else -v


class Compass(Sampler):
    """Compass (pattern) search, the legacy pattern_search: poll +-step on each continuous variable,
    move to the best improving point, shrink the step when nothing improves. One round per poll."""
    one_shot = False

    def __init__(self, variables, cfg, objectives):
        super().__init__(variables, cfg, objectives)
        if len(objectives) != 1:
            raise ConfigError("compass search needs exactly one objective")
        self.names = [n for n, v in variables.items() if v.kind == "continuous"]
        if len(self.names) != len(variables):
            raise ConfigError("compass search supports continuous variables only")
        steps = cfg.get("steps", [0.1])
        self.steps = [s if isinstance(s, dict) else {n: float(s) for n in self.names} for s in steps]
        self.max_iter = int(cfg.get("max_iter", 60))
        self.level = 0
        self.iter = 0
        self.center: dict | None = None
        self.best = math.inf
        self.phase = "center"

    def _start(self):
        start = self.cfg.get("start")
        if isinstance(start, dict):
            return {n: float(start[n]) for n in self.names}
        return {n: (self.vars[n].lo + self.vars[n].hi) / 2 for n in self.names}

    def ask(self, n=None):
        if self._done:
            return []
        if self.center is None:
            self.center = self._start()
            self.phase = "center"
            self.issued += 1
            return [dict(self.center)]
        self.phase = "poll"
        step = self.steps[self.level]
        pts = []
        for nm in self.names:
            for sgn in (1, -1):
                p = dict(self.center)
                p[nm] = p[nm] + sgn * step[nm]
                if self.vars[nm].contains(p[nm]):
                    pts.append(p)
        self.issued += len(pts)
        if not pts:
            self._advance(False)
            return self.ask(n)
        return pts

    def tell(self, results):
        if self.phase == "center":
            self.best = min((_score(r, self.objectives) if r.feasible else math.inf for r in results),
                            default=math.inf)
            return
        best_r, best_s = None, self.best
        for r in results:
            s = _score(r, self.objectives) if r.feasible else math.inf
            if s < best_s - 1e-15:
                best_r, best_s = r, s
        if best_r is not None:
            self.best = best_s
            self.center = {n: float(best_r.values[n]) for n in self.names}
            self._advance(True)
        else:
            self._advance(False)

    def _advance(self, improved: bool):
        self.iter += 1
        if not improved:
            self.level += 1
        if self.level >= len(self.steps) or self.iter >= self.max_iter:
            self._done = True

    def state(self):
        return {**super().state(), "level": self.level, "iter": self.iter, "center": self.center, "best": self.best,
                "phase": self.phase}

    def restore(self, state, history):
        super().restore(state, history)
        self.level, self.iter = state.get("level", 0), state.get("iter", 0)
        self.center, self.best = state.get("center"), state.get("best", math.inf)
        self.phase = state.get("phase", "center")


class OptunaSampler(Sampler):
    """Optuna TPE / NSGA-II through ask/tell. Optuna keeps no storage: history is replayed on restore."""
    one_shot = False

    def __init__(self, variables, cfg, objectives):
        super().__init__(variables, cfg, objectives)
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.optuna = optuna
        if not objectives:
            raise ConfigError(f"{cfg['kind']} needs objectives")
        self.dirs = [o.direction for o in objectives.values()]
        self.dists = {}
        for n, v in variables.items():
            if v.kind == "continuous":
                if v.integer:
                    self.dists[n] = optuna.distributions.IntDistribution(int(v.lo), int(v.hi), log=v.log)
                else:
                    self.dists[n] = optuna.distributions.FloatDistribution(v.lo, v.hi, log=v.log)
            else:
                self.dists[n] = optuna.distributions.CategoricalDistribution(list(v.values))
        self.round_size = int(cfg.get("round_size", 8))
        self.budget = cfg.get("_budget_runs")
        self._make()
        self.trials: dict[str, Any] = {}

    def _make(self):
        seed = self.cfg.get("seed")
        # constraints are attached to each trial with set_constraint (optuna >= 5); <= 0 is feasible
        if self.cfg["kind"] == "optuna_nsga2":
            sampler = self.optuna.samplers.NSGAIISampler(seed=seed, population_size=self.round_size)
        else:
            sampler = self.optuna.samplers.TPESampler(seed=seed, n_startup_trials=int(self.cfg.get("startup", 10)))
        self.study = self.optuna.create_study(directions=self.dirs, sampler=sampler)

    def ask(self, n=None):
        n = n or self.round_size
        out = []
        for _ in range(n):
            t = self.study.ask(self.dists)
            vals = dict(t.params)
            key = repr(sorted(vals.items()))
            self.trials.setdefault(key, []).append(t)
            out.append(vals)
        self.issued += len(out)
        return out

    def _tell_one(self, trial, r: RowResult):
        if r.status != "done" or any(r.objectives.get(o) is None for o in self.objectives):
            self.study.tell(trial, state=self.optuna.trial.TrialState.FAIL)
            return
        for name, slack in r.constraints.items():
            trial.set_constraint(name, -float(slack) if math.isfinite(slack) else 1e30)
        vals = [float(r.objectives[o]) for o in self.objectives]
        self.study.tell(trial, vals if len(vals) > 1 else vals[0])

    def tell(self, results):
        for r in results:
            key = repr(sorted(r.values.items()))
            lst = self.trials.get(key)
            if lst:
                self._tell_one(lst.pop(0), r)

    def restore(self, state, history):
        super().restore(state, history)
        for r in history:
            params = {k: r.values[k] for k in self.dists}
            ok = r.status == "done" and all(r.objectives.get(o) is not None for o in self.objectives)
            vals = [float(r.objectives[o]) for o in self.objectives] if ok else None
            ft = self.optuna.trial.create_trial(
                params=params, distributions=self.dists,
                values=vals, state=self.optuna.trial.TrialState.COMPLETE if ok else self.optuna.trial.TrialState.FAIL,
                constraints=({k: (-float(v) if math.isfinite(v) else 1e30) for k, v in r.constraints.items()}
                             if ok and r.constraints else None))
            self.study.add_trial(ft)


KINDS = {"grid": Grid, "list": Listed, "sobol": QMC, "lhs": QMC, "product": Product, "compass": Compass,
         "optuna_tpe": OptunaSampler, "optuna_nsga2": OptunaSampler}


ALLOWED = {"grid": {"vars", "levels"}, "list": {"rows", "csv"}, "sobol": {"vars", "n", "seed"},
           "lhs": {"vars", "n", "seed"}, "product": {"of"}, "compass": {"start", "steps", "max_iter"},
           "optuna_tpe": {"seed", "round_size", "startup"}, "optuna_nsga2": {"seed", "round_size"}}


def make_sampler(variables: dict, cfg: dict, objectives: dict) -> Sampler:
    kind = cfg.get("kind")
    if kind not in KINDS:
        raise ConfigError(f"unknown sampler kind {kind!r} (known: {', '.join(KINDS)})")
    unknown = {k for k in cfg if not k.startswith("_") and k != "kind"} - ALLOWED[kind]
    if unknown:
        raise ConfigError(f"sampler {kind}: unknown setting(s) {sorted(unknown)} "
                          f"(allowed: {', '.join(sorted(ALLOWED[kind]))})")
    for n in cfg.get("vars") or []:
        if n not in variables:
            raise ConfigError(f"sampler {kind}: no study variable {n!r}")
    return KINDS[kind](variables, cfg, objectives)
