"""The page proven by code (docs/PLAN.md §7, §7a rule 29): the view model from a run dir, with
no browser, must satisfy every rule the design states. Exit 0 ok, 1 warnings, 2 a rule broken."""

from __future__ import annotations

import json
import re
from pathlib import Path

from code_steer_model_write.events import EventLog
from code_steer_model_write.state.run import RunPaths, RunState

from . import theme
from .model import RunView, build_view

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def check(run_dir: Path | str) -> tuple[list[str], list[str]]:
    """Returns (problems, warnings)."""
    paths = RunPaths(run_dir=Path(run_dir))
    v = build_view(paths.run_dir)
    st = RunState.load(paths)
    evs = EventLog(paths.events, st.run_id).all()
    probs: list[str] = []
    warns: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            probs.append(msg)

    # header: identity, the four signals
    need(bool(v.run_id and v.recipe and v.mode and v.models), "identity line has an empty field")
    need(
        v.process in ("running", "completed", "halted honestly", "broke", "waiting"),
        f"process signal unknown: {v.process}",
    )
    need(bool(v.elapsed and v.elapsed != "–"), "elapsed is empty")
    used = {e.role for e in evs if e.kind == "call.usage" and e.role}
    need(
        set(v.tokens) == used,
        f"tokens per side {sorted(v.tokens)} != the sides that spent any {sorted(used)}",
    )
    # the rail: every stage, exactly one current, states legal
    need(len(v.stages) >= 1, "no stages")
    need(
        all(s.state in ("pending", "now", "done", "halted") for s in v.stages), "a stage has an unknown state"
    )
    need(v.current_stage in {s.id for s in v.stages}, "current stage is not a stage")
    for s in v.stages:
        if s.state == "done":
            need(bool(s.duration), f"stage {s.id} done without a duration")
        if s.rounds:
            k, n = s.rounds.replace("Round ", "").split("/")
            need(int(k) <= int(n), f"stage {s.id} shows {s.rounds}: more rounds than the cap")
    # the NOW line equals the record
    last = evs[-1] if evs else None
    if v.process == "completed":
        need(
            v.now_word == "COMPLETE" and v.product in v.now_text,
            "completed run: the now line does not carry the verdict",
        )
        need(v.completed_at is not None, "completed run without completed_at (the timer would keep running)")
    elif v.process == "halted honestly":
        need(v.now_word == "HALT" and paths.halt.exists(), "halted run: the now line is not the halt")
    elif last is not None and any(s.gate for s in v.stages):
        need(v.now_word == "GATE", "an open gate is not the now line")
    # chips equal recounts from the events
    refused = sum(1 for e in evs if e.kind == "step.refused")
    halts = sum(1 for e in evs if e.kind == "halt")
    by_key = {c.key: c.count for c in v.chips}
    need(by_key.get("refused", 0) == refused, f"refused chip {by_key.get('refused', 0)} != events {refused}")
    need(by_key.get("halts", 0) == halts, f"halts chip {by_key.get('halts', 0)} != events {halts}")
    need(by_key.get("carried", 0) == len(st.carried), "carried chip != state.carried")
    # a gate form is present iff an ask file has no decision
    open_gates = (
        sorted(
            p.name[: -len(".ask.json")]
            for p in paths.gates.glob("*.ask.json")
            if not (paths.gates / (p.name[: -len(".ask.json")] + ".decision.json")).exists()
        )
        if paths.gates.exists()
        else []
    )
    shown = sorted(s.gate["id"] for s in v.stages if s.gate)
    need(open_gates == shown, f"open gates {open_gates} but the page shows {shown}")
    # evidence agrees with the log
    calls = sum(1 for e in evs if e.kind == "call.started")
    need(len(v.agent_runs) == calls, f"{len(v.agent_runs)} agent runs shown, {calls} calls in the log")
    need(len(v.events) == len(evs), "event log rows != events")
    # the refresh hash covers every live file in the run dir
    live = set(v.live_files)
    for p in paths.run_dir.rglob("*"):
        if (
            p.is_file()
            and p.suffix in (".json", ".jsonl")
            and "_undone" not in p.parts
            and "build" not in p.parts
            and "streams" not in p.parts
        ):
            rel = str(p.relative_to(paths.run_dir))
            if rel not in live and not rel.endswith(".lock"):
                probs.append(f"refresh hash does not cover live file {rel}")
    # §7d: the home's row for this run says what the view says, and the timeline is the record
    from . import home, timeline

    hr = home.row_for(paths.run_dir)
    need(hr.id == v.run_id and hr.recipe == v.recipe, "home row: identity differs from the view")
    need(
        hr.dot == v.dot and hr.ring == v.dot_ring,
        f"home row dot {hr.dot}/{hr.ring} != the view's {v.dot}/{v.dot_ring}",
    )
    need(
        hr.tokens == sum(v.tokens.values()),
        f"home row tokens {hr.tokens} != the view's {sum(v.tokens.values())}",
    )
    need(hr.steps_done == sum(1 for r in st.steps.values() if r.done_at), "home row steps done != state.json")
    if v.process == "completed":
        need(hr.verdict == v.product, f"home row verdict {hr.verdict!r} != the view's {v.product!r}")
        ep = paths.run_dir / "evals.json"
        if ep.exists():
            want = {
                str(r["metric"])
                for r in json.loads(ep.read_text()).get("results", [])
                if isinstance(r.get("value"), (int, float))
            }
            need(set(hr.eval_values) == want, "home row evals != evals.json")
    tl = timeline.rows(evs)
    need([r.step for r in v.timeline] == [r.step for r in tl], "the view's timeline != rows from the events")
    started = [k for k, r in st.steps.items() if r.started_at is not None]
    need(len(tl) == len(started), f"{len(tl)} timeline rows, {len(started)} steps started in state.json")
    need(all(r.end >= r.start for r in tl), "a timeline row ends before it starts")
    par = [e for e in evs if e.kind == "run.progress" and e.data.get("parallel")]
    for e in par:
        keys = list(e.data["parallel"])
        ov = {(a, b) for a, b, _ in timeline.overlaps(tl)} | {(b, a) for a, b, _ in timeline.overlaps(tl)}
        by = {r.step: r for r in tl}
        if all(k in by and by[k].done for k in keys) and len(keys) >= 2:
            need((keys[0], keys[1]) in ov, f"parallel round {keys} shows no overlap on the timeline")
    # every colour used by the page module is a token
    src = Path(__file__).parent / "dashboard.py"
    if src.exists():
        for hexv in set(_HEX.findall(src.read_text())):
            if hexv.lower() not in {t.lower() for t in theme.TOKENS}:
                probs.append(f"dashboard.py uses a colour outside the token table: {hexv}")
        # every disclosure has a stable id
        body = src.read_text()
        need("details(" not in body or "id=" in body, "a disclosure without a stable id")
    else:
        warns.append("dashboard/dashboard.py not present; component checks skipped")
    return probs, warns


def main(run_dir: str) -> int:
    probs, warns = check(run_dir)
    v: RunView = build_view(run_dir)
    print(
        f"selfcheck {v.run_id}: {v.process} · {v.now_word} · {len(v.stages)} stages · {len(v.events)} events · hash {v.refresh_hash}"
    )
    for w in warns:
        print(f"  warn  {w}")
    for p in probs:
        print(f"  BROKEN {p}")
    if probs:
        return 2
    return 1 if warns else 0


def to_json(run_dir: str) -> str:
    return json.dumps(build_view(run_dir).model_dump(mode="json"), indent=1, default=str)
