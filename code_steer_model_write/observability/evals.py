"""L8's Evaluator (ARCHITECTURE.md 7.9): the recipe's eval specs (P12) scored over the run's
own record, never over anything else. `evals.json` in the run directory is the record (rule
4); MLflow holds a mirror of it as metrics on the run, and the page reads the file.

Scorers are code functions keyed by the spec's metric name. A recipe may declare a metric this
module has no scorer for; the result then says `unscored` rather than inventing a number."""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from ..events import EventLog
from ..state.lock import atomic_write_text
from ..state.run import RunPaths, RunState


class EvalResult(BaseModel):
    metric: str
    value: float | None
    target: float | None = None
    higher_is_better: bool = True
    tier: str = "code"
    passed: bool | None = None  # None when there is no target or no value
    note: str = ""


class EvalReport(BaseModel):
    run_id: str
    results: list[EvalResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed is not False for r in self.results)


Scorer = Callable[[RunPaths, RunState, list[Any]], tuple[float | None, str]]


def _latest(paths: RunPaths, key: str) -> dict[str, Any] | None:
    d = paths.artifacts / key
    if not d.exists():
        return None
    vs = sorted(d.glob("v*.json"))
    return json.loads(vs[-1].read_text()) if vs else None


def _pass_rate(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    res = _latest(paths, "results")
    if not res or not res.get("properties"):
        return None, "no results artifact"
    props = res["properties"]
    return sum(p.get("real") == "pass" for p in props) / len(
        props
    ), f"{sum(p.get('real') == 'pass' for p in props)}/{len(props)} pass against the source"


def _null_fail_rate(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    res = _latest(paths, "results")
    if not res or not res.get("properties"):
        return None, "no results artifact"
    props = res["properties"]
    return sum(p.get("null") == "fail" for p in props) / len(
        props
    ), f"{sum(p.get('null') == 'fail' for p in props)}/{len(props)} fail against the null"


def _carried_findings(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    rep = _latest(paths, "report")
    if rep is None:
        return None, "no report artifact"
    carried = rep.get("carried", [])
    return float(len(carried)), f"{len(carried)} carried into the report"


def _rounds_to_converge(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    closed = [e for e in evs if e.kind == "round.closed"]
    if not closed:
        return None, "no review rounds"
    loops: dict[str, int] = {}
    for e in closed:
        loops[e.data.get("loop", "?")] = max(
            loops.get(e.data.get("loop", "?"), 0), int(e.data.get("round", 0))
        )
    return float(sum(loops.values())) / len(loops), ", ".join(f"{k}: {v}" for k, v in loops.items())


def _refused_answers(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    n = sum(1 for e in evs if e.kind == "step.refused")
    return float(n), f"{n} answers refused and re-asked"


def _rubric_score(paths: RunPaths, st: RunState, evs: list[Any]) -> tuple[float | None, str]:
    p = paths.run_dir / "evals.recipe.json"
    if p.exists():
        d = json.loads(p.read_text())
        v = d.get("rubric_score") or d.get("rubric")
        return (float(v), "from the recipe's own evals") if v is not None else (None, "no rubric score")
    return None, "no recipe evals file"


SCORERS: dict[str, Scorer] = {
    "pass_rate": _pass_rate,
    "null_fail_rate": _null_fail_rate,
    "carried_findings": _carried_findings,
    "rounds_to_converge": _rounds_to_converge,
    "refused_answers": _refused_answers,
    "rubric_score": _rubric_score,
}


class Evaluator:
    """Score a finished run against its recipe's specs; write `evals.json`; return the report."""

    def __init__(self, scorers: dict[str, Scorer] | None = None) -> None:
        self.scorers = {**SCORERS, **(scorers or {})}

    def score(self, paths: RunPaths, specs: list[Any]) -> EvalReport:
        st = RunState.load(paths)
        evs = EventLog(paths.events, st.run_id).all()
        out = EvalReport(run_id=st.run_id)
        for spec in specs:
            fn = self.scorers.get(spec.metric)
            if fn is None:
                out.results.append(
                    EvalResult(
                        metric=spec.metric,
                        value=None,
                        target=spec.target,
                        tier=spec.tier,
                        higher_is_better=spec.higher_is_better,
                        note="unscored: no scorer for this metric",
                    )
                )
                continue
            value, note = fn(paths, st, evs)
            passed: bool | None = None
            if value is not None and spec.target is not None:
                passed = value >= spec.target if spec.higher_is_better else value <= spec.target
            out.results.append(
                EvalResult(
                    metric=spec.metric,
                    value=value,
                    target=spec.target,
                    tier=spec.tier,
                    higher_is_better=spec.higher_is_better,
                    passed=passed,
                    note=note,
                )
            )
        atomic_write_text(paths.run_dir / "evals.json", out.model_dump_json(indent=2))
        return out

    @staticmethod
    def read(paths: RunPaths) -> EvalReport | None:
        p = paths.run_dir / "evals.json"
        return EvalReport.model_validate_json(p.read_text()) if p.exists() else None
