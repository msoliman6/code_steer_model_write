"""csmw -- the command line. Exit codes are honest (rule 10): 0 done, 1 a record to read, 2 a refusal or halt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .spec.task import TaskSpec
from .state.run import RunPaths, RunState


def _load_task(path: str) -> TaskSpec:
    return TaskSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))


def cmd_validate(a: argparse.Namespace) -> int:
    from .recipes import registry

    task = _load_task(a.task)
    recipe = registry.get(task.recipe)
    probs = recipe.validate_task(task)
    for p in probs:
        print(f"refused: {p}")
    if probs:
        return 2
    print(
        f"ok: task {task.task_id} fits recipe {task.recipe} ({recipe.spec.status}); roles {sorted(task.roles)}; mode {task.mode}; rounds {task.rounds}"
    )
    return 0


def _backends(task: TaskSpec, recipe, paths: RunPaths):
    from .artifacts.store import Store
    from .backends.fake import FakeBackend
    from .backends import knobs

    out = {}
    names = {r.backend.value for r in task.roles.values()}
    if knobs.enabled():
        names = {"fake"}
    for n in names:
        if n == "fake":
            out["fake"] = FakeBackend(
                fixtures_root=recipe.fixtures_root, fakers=recipe.fakers(paths, Store(paths.run_dir))
            )
        else:
            from .backends.registry import make

            out[n] = make(n)
    return out


def cmd_run(a: argparse.Namespace) -> int:
    from .backends import knobs
    from .driver.runner import Runner
    from .gates.gate import make_waiter
    from .recipes import registry

    task = _load_task(a.task)
    recipe = registry.get(task.recipe)
    probs = recipe.validate_task(task)
    if probs:
        for p in probs:
            print(f"refused: {p}")
        return 2
    run_dir = Path(a.run_dir) if a.run_dir else Path(Settings().runs_dir) / task.task_id
    paths = RunPaths(run_dir=run_dir)
    if paths.state.exists():
        print(f"refused: a run already lives at {run_dir}; use `csmw resume {run_dir}` or another --run-dir")
        return 2
    if knobs.enabled():
        task = task.model_copy(
            update={"roles": {r: s.model_copy(update={"backend": "fake"}) for r, s in task.roles.items()}}
        )
    RunState.create(paths, task)
    print(f"run {task.task_id} at {run_dir} (mode {task.mode}, rounds {task.rounds}, fake={knobs.enabled()})")
    runner = Runner(
        paths,
        recipe,
        _backends(task, recipe, paths),
        task.roles,
        make_waiter(task.mode, recipe.gate_builders()),
        gate_timeout=a.gate_timeout,
    )
    outcome = runner.drive()
    return _report_outcome(paths, outcome)


def cmd_resume(a: argparse.Namespace) -> int:
    from .driver.runner import Runner
    from .gates.gate import make_waiter
    from .recipes import registry

    paths = RunPaths(run_dir=Path(a.run_dir))
    st = RunState.load(paths)
    recipe = registry.get(st.recipe)
    runner = Runner(
        paths,
        recipe,
        _backends(st.task, recipe, paths),
        st.task.roles,
        make_waiter(st.task.mode, recipe.gate_builders()),
        gate_timeout=a.gate_timeout,
    )
    return _report_outcome(paths, runner.drive())


def _report_outcome(paths: RunPaths, outcome) -> int:
    from .driver.halt import Halt

    st = RunState.load(paths)
    print(f"{outcome.value}: status {st.status.value}, {len(st.done_keys())}/{len(st.steps)} steps done")
    h = Halt.read(paths)
    if h:
        print(h.line())
        for f in h.facts[-6:]:
            print("  ", json.dumps(f)[:200])
        return 2 if h.resumable else 1
    if st.carried:
        print(f"{len(st.carried)} item(s) carried into the report:")
        for c in st.carried[:10]:
            print(f"  - {c.kind} {c.id}: {c.summary[:120]}")
    rep = paths.run_dir / "REPORT.md"
    if rep.exists():
        print(f"report: {rep}")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    from .driver.halt import Halt

    paths = RunPaths(run_dir=Path(a.run_dir))
    st = RunState.load(paths)
    print(
        f"{st.run_id} · {st.recipe} · {st.status.value} · outcome {st.outcome.value if st.outcome else '-'} · resumed x{st.resumed_count}"
    )
    for k, r in st.steps.items():
        print(f"  {'done' if r.done_at else 'open':4s} {k}")
    h = Halt.read(paths)
    if h:
        print(h.line())
    return 0


def cmd_walk(a: argparse.Namespace) -> int:
    from . import walk

    rs = walk.run(a.recipe, only=a.only, keep=a.keep)
    print(walk.report(rs))
    return 0 if all(r.ok for r in rs) else 2


def cmd_doctor(a: argparse.Namespace) -> int:
    from .doctor import run as doctor_run

    return doctor_run(deep=a.deep)


def cmd_figure(a: argparse.Namespace) -> int:
    from .figure import write_figure

    out = write_figure(a.recipe, Path(a.out), theme=a.theme)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="csmw", description="code steers, models write")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate", help="DRAFT -> VALIDATED: the task fits the recipe")
    p.add_argument("task")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("run", help="start a run and drive it")
    p.add_argument("task")
    p.add_argument("--run-dir")
    p.add_argument("--gate-timeout", type=float)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("resume", help="continue a halted or gated run")
    p.add_argument("run_dir")
    p.add_argument("--gate-timeout", type=float)
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("status", help="where a run is")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("walk", help="the offline walk: fake models, every branch, zero tokens")
    p.add_argument("recipe", nargs="?", default="all")
    p.add_argument("--only")
    p.add_argument("--keep", action="store_true")
    p.set_defaults(fn=cmd_walk)
    p = sub.add_parser("doctor", help="preflight; exit 0 ready, 1 warnings, 2 halt")
    p.add_argument("--deep", action="store_true")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("figure", help="the workflow figure from a recipe")
    p.add_argument("recipe")
    p.add_argument("-o", "--out", default="docs/media/workflow.svg")
    p.add_argument("--theme", choices=["dark", "light"], default="dark")
    p.set_defaults(fn=cmd_figure)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
