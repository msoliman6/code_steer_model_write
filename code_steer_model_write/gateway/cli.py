"""The control plane from the terminal (ARCHITECTURE.md 7.10, Typer): the same operations the
MCP server exposes, so a shell, a host and the walk all go through one Gateway.

    csmw gateway list | run TASK.json | status RUN | cancel RUN | pause RUN | resume RUN
    csmw gateway logs RUN [--after N] | artifacts RUN | runs | serve
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="the control plane: workflows and runs")


def _gw():
    from .api import Gateway

    return Gateway()


def _out(obj) -> None:
    typer.echo(
        json.dumps(obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj, indent=2, default=str)
    )


@app.command("list")
def list_workflows() -> None:
    """The workflows this runtime can run."""
    _out([w.model_dump() for w in _gw().list_workflows()])


@app.command()
def run(task: Path, runs_dir: str | None = None, run_dir: str | None = None, mlflow: bool = True) -> None:
    """Validate, register, launch detached; print the run handle at once."""
    _out(_gw().run(json.loads(task.read_text()), runs_dir=runs_dir, run_dir=run_dir, mlflow=mlflow))


@app.command()
def status(run: str) -> None:
    """Where a run is."""
    _out(_gw().status(run))


@app.command()
def cancel(run: str) -> None:
    """Stop at the next step boundary; resumable."""
    _out(_gw().cancel(run))


@app.command()
def pause(run: str) -> None:
    """Pause at the next step boundary."""
    _out(_gw().pause(run))


@app.command()
def resume(run: str, mlflow: bool = True) -> None:
    """Continue at the first undone step."""
    _out(_gw().resume(run, mlflow=mlflow))


@app.command()
def logs(run: str, after: int = 0, limit: int = 200) -> None:
    """A page of the event log after sequence `after`."""
    _out(_gw().logs(run, after=after, limit=limit))


@app.command()
def artifacts(run: str) -> None:
    """The run's artifacts with their versions."""
    _out([a.model_dump() for a in _gw().artifacts(run)])


@app.command()
def runs() -> None:
    """Every run the registry knows, across all runs directories."""
    _out(_gw().list_runs())


@app.command()
def serve() -> None:
    """The MCP server over stdio (what `claude mcp add` and `codex mcp add` start)."""
    from .server import main

    main()


prefect_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Prefect as the Runner (7.3): the packaged server and the serve process",
)
app.add_typer(prefect_app, name="prefect")


@prefect_app.command("serve")
def prefect_serve(limit: int = 4) -> None:
    """Serve the run deployment: takes runs from the Prefect server and executes them. One
    command; pair it with `prefect server start`."""
    from ..workflow.flows import serve

    serve(limit=limit)


@prefect_app.command("check")
def prefect_check() -> None:
    """Is the Prefect runner available: the server reachable, the deployment served?"""
    from ..layers.prefect_runner import PrefectRunner

    ok, why = PrefectRunner().available()
    typer.echo(("available: " if ok else "not available: ") + why)
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
