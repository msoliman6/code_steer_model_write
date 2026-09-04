"""The MCP server over the gateway (ARCHITECTURE.md 7.10): the official SDK, stdio for Claude
Code and Codex, an in-memory client for the walk. Each tool's arguments and result are
pydantic models, so the schema the host sees is generated, never written. `workflow_run`
returns at once with the run id; the run executes detached under the Runner.

    claude mcp add --transport stdio csmw -- python -m code_steer_model_write.gateway
    codex mcp add csmw -- python -m code_steer_model_write.gateway
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from ..layers.runner import RunHandle
from .api import ArtifactInfo, EventPage, Gateway, RunStatus, WorkflowInfo


def build(gateway: Gateway | None = None) -> MCPServer:
    gw = gateway or Gateway()
    srv = MCPServer(
        "csmw",
        instructions="The production agentic workflow's control plane: list workflows, start runs, watch and steer them. A run executes detached; workflow_run returns its id at once.",
    )

    @srv.tool()
    def workflow_list() -> list[WorkflowInfo]:
        """The workflows this runtime can run, with their stages."""
        return gw.list_workflows()

    @srv.tool()
    def workflow_run(
        task: dict[str, Any], runs_dir: str | None = None, run_dir: str | None = None
    ) -> RunHandle:
        """Validate the task through its recipe, register the run, launch it detached, and return
        the run id at once. The task is the RunSpec: task_id, objective, recipe, inputs, roles,
        swaps, mode, rounds."""
        return gw.run(task, runs_dir=runs_dir, run_dir=run_dir)

    @srv.tool()
    def workflow_status(run: str) -> RunStatus:
        """Where a run is: status, steps done of total, the current step, a halt if any, the verdict when finished."""
        return gw.status(run)

    @srv.tool()
    def workflow_cancel(run: str) -> RunHandle:
        """Ask a live run to stop at the next step boundary; its record stays and it can be resumed."""
        return gw.cancel(run)

    @srv.tool()
    def workflow_pause(run: str) -> RunHandle:
        """Pause a live run at the next step boundary (a halt that resumes where it stopped)."""
        return gw.pause(run)

    @srv.tool()
    def workflow_resume(run: str) -> RunHandle:
        """Continue a paused or halted run from the first undone step."""
        return gw.resume(run)

    @srv.tool()
    def run_list() -> list[dict[str, Any]]:
        """Every run the registry knows, across all runs directories, newest first."""
        return gw.list_runs()

    @srv.tool()
    def run_get(run: str) -> dict[str, Any]:
        """A run's task, status and step records."""
        return gw.get(run)

    @srv.tool()
    def run_logs(run: str, after: int = 0, limit: int = 200) -> EventPage:
        """A page of the run's event log after sequence `after`; page with next_after."""
        return gw.logs(run, after=after, limit=limit)

    @srv.tool()
    def run_artifacts(run: str) -> list[ArtifactInfo]:
        """The run's artifacts: every key with its versions and the latest file."""
        return gw.artifacts(run)

    return srv


def main() -> None:
    build().run(transport="stdio")


if __name__ == "__main__":
    main()
