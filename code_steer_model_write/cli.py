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


def runner_for(run_dir: Path, *, gate_timeout: float | None = None):
    from .driver.runner import Runner
    from .gates.gate import make_waiter
    from .recipes import registry

    paths = RunPaths(run_dir=run_dir)
    st = RunState.load(paths)
    recipe = registry.get(st.recipe)
    return Runner(
        paths,
        recipe,
        _backends(st.task, recipe, paths),
        st.task.roles,
        make_waiter(st.task.mode, recipe.gate_builders()),
        gate_timeout=gate_timeout,
    )


def attach_mlflow(runner) -> bool:
    """The L8 mirror on the runner's log (7.9): a sink (rule 4), so failing to attach is a warning,
    never a halt. One owner for every path that drives a run: `csmw resume`, the LocalRunner's
    child, the Prefect flow."""
    try:
        from .observability.mlflow_bridge import MlflowMirror

        st = runner.driver.state
        MlflowMirror(Settings().mlflow_tracking_uri, st.run_id, st.recipe, runner.paths.run_dir).attach(
            runner.events
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"warn: mlflow mirror not attached: {e}")
        return False


def _attach_mirrors(runner, a: argparse.Namespace) -> None:
    """MLflow is a sink (rule 4); failing to attach is a warning, never a halt. (monitor.db, the
    page's private index, left with the Run Registry in L7: one index of runs, read by the page.)"""
    if not getattr(a, "no_mlflow", False):
        attach_mlflow(runner)


def _drive(runner, a: argparse.Namespace):
    if getattr(a, "prefect", False):
        from .workflow.flows import drive_with_prefect

        return drive_with_prefect(runner)
    return runner.drive()


def cmd_run(a: argparse.Namespace) -> int:
    from .backends import knobs
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
    runner = runner_for(run_dir, gate_timeout=a.gate_timeout)
    _attach_mirrors(runner, a)
    outcome = _drive(runner, a)
    return _report_outcome(paths, outcome)


def cmd_start(a: argparse.Namespace) -> int:
    """The start page from the terminal: the form's defaults, prefs.json, then --set key=value."""
    from . import settings_form as sf

    runs_dir = Path(Settings().runs_dir)
    values = {**sf.load_prefs(runs_dir)}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if k not in sf.BY_KEY:
            print(f"refused: no setting named {k!r}; the fields are {list(sf.BY_KEY)}")
            return 2
        values[k] = v
    missing = sf.missing_required(values)
    if missing:
        print(f"refused: fill {missing} (--set run_name=... --set request=...)")
        return 2
    task = sf.build_task(values)
    sf.save_prefs(runs_dir, values)
    run_dir = runs_dir / task.task_id
    n = 2
    while RunPaths(run_dir=run_dir).state.exists():
        run_dir = runs_dir / f"{task.task_id}-{n}"
        n += 1
    task = task.model_copy(update={"task_id": run_dir.name})
    print(
        f"run {task.task_id} at {run_dir}: {task.mode} · rounds {task.rounds} · author {task.roles['author'].backend.value}/{task.roles['author'].model} · checker {task.roles['checker'].backend.value}/{task.roles['checker'].model}"
    )
    if a.dry:
        print(task.model_dump_json(indent=2)[:1200])
        return 0
    RunState.create(RunPaths(run_dir=run_dir), task)
    runner = runner_for(run_dir, gate_timeout=a.gate_timeout)
    _attach_mirrors(runner, a)
    return _report_outcome(runner.paths, _drive(runner, a))


def cmd_resume(a: argparse.Namespace) -> int:
    runner = runner_for(Path(a.run_dir), gate_timeout=a.gate_timeout)
    _attach_mirrors(runner, a)
    return _report_outcome(runner.paths, _drive(runner, a))


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


def cmd_sandbox(a: argparse.Namespace) -> int:
    from .layers import container_sandbox as cs

    if a.sandbox_cmd == "build":
        print(f"built {cs.IMAGE}: {cs.build()}")
        return 0
    if a.sandbox_cmd == "check":
        ok, why = cs.available()
        print(("available: " if ok else "unavailable: ") + why)
        return 0 if ok else 1
    from .layers.sandbox import Execution

    ok, why = cs.available()
    if not ok:
        print(f"unavailable: {why}")
        return 2
    argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
    r = cs.ContainerSandbox().run(Execution(command=argv, root=Path.cwd(), network=a.network, timeout=600))
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    print(
        f"[{r.tier}] exit {r.exit_code} in {r.seconds}s · touched {len(r.touched)}"
        + (" · TIMED OUT" if r.timed_out else "")
    )
    return r.exit_code


def cmd_dash(a: argparse.Namespace) -> int:
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if a.dash_cmd == "selfcheck":
        from dashboard.selfcheck import main as selfcheck

        return selfcheck(a.run_dir)
    if a.dash_cmd == "view":
        from dashboard.selfcheck import to_json

        print(to_json(a.run_dir))
        return 0
    import subprocess

    root = Path(__file__).resolve().parent.parent
    env = dict(__import__("os").environ)
    env["CSMW_RUNS_DIR"] = str(Path(a.runs_dir).resolve())
    print(f"serving the dashboard from {root} on 127.0.0.1:{a.port} (runs dir {env['CSMW_RUNS_DIR']})")
    return subprocess.call(
        [
            _sys.executable,
            "-m",
            "reflex",
            "run",
            "--frontend-port",
            str(a.port),
            "--backend-port",
            str(a.port + 1),
        ],
        cwd=root,
        env=env,
    )


def cmd_figure(a: argparse.Namespace) -> int:
    from .figure import write_figure

    if a.recipe == "harness":
        from .figure_harness import write

        out = write(Path(a.out), theme=a.theme)
        print(f"wrote {out}")
        return 0
    out = write_figure(a.recipe, Path(a.out), theme=a.theme)
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "gateway":
        # the control plane's verbs (Typer, ARCHITECTURE.md 7.10): one Gateway for the shell,
        # the hosts and the walk
        from .gateway.cli import app as gateway_app

        try:
            gateway_app(args=argv[1:], prog_name="csmw gateway")
        except SystemExit as e:
            return int(e.code or 0)
        return 0
    ap = argparse.ArgumentParser(prog="csmw", description="code steers, models write")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate", help="DRAFT -> VALIDATED: the task fits the recipe")
    p.add_argument("task")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("run", help="start a run and drive it")
    p.add_argument("task")
    p.add_argument("--run-dir")
    p.add_argument("--gate-timeout", type=float)
    p.add_argument("--prefect", action="store_true", help="run the loop as a Prefect flow (a task per step)")
    p.add_argument("--no-mlflow", action="store_true")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser(
        "start", help="build a task from the settings form (defaults, prefs.json, --set key=value) and run it"
    )
    p.add_argument("--set", action="append", metavar="KEY=VALUE")
    p.add_argument("--dry", action="store_true", help="print the task, do not run")
    p.add_argument("--gate-timeout", type=float)
    p.add_argument("--prefect", action="store_true")
    p.add_argument("--no-mlflow", action="store_true")
    p.set_defaults(fn=cmd_start)
    p = sub.add_parser("resume", help="continue a halted or gated run")
    p.add_argument("run_dir")
    p.add_argument("--gate-timeout", type=float)
    p.add_argument("--prefect", action="store_true")
    p.add_argument("--no-mlflow", action="store_true")
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
    p = sub.add_parser("dash", help="the dashboard: serve, selfcheck a run, or dump its view model")
    ps = p.add_subparsers(dest="dash_cmd", required=True)
    q = ps.add_parser("serve")
    q.add_argument("--port", type=int, default=3000)
    q.add_argument("--runs-dir", default="runs")
    q = ps.add_parser("selfcheck")
    q.add_argument("run_dir")
    q = ps.add_parser("view")
    q.add_argument("run_dir")
    p.set_defaults(fn=cmd_dash)
    p = sub.add_parser(
        "sandbox", help="the container tier (L5): build the image, check the engine, run one command"
    )
    ps = p.add_subparsers(dest="sandbox_cmd", required=True)
    ps.add_parser("build", help="build the sandbox image from data/sandbox.Dockerfile")
    ps.add_parser("check", help="is an engine answering and the image there")
    q = ps.add_parser("run", help="run one command in the tier, the cwd the only mount, network off")
    q.add_argument("--network", action="store_true")
    q.add_argument("argv", nargs=argparse.REMAINDER, help="the command, after `--`")
    p.set_defaults(fn=cmd_sandbox)
    p = sub.add_parser("figure", help="the workflow figure from a recipe")
    p.add_argument("recipe")
    p.add_argument("-o", "--out", default="docs/media/workflow.svg")
    p.add_argument("--theme", choices=["dark", "light"], default="dark")
    p.set_defaults(fn=cmd_figure)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
