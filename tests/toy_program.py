"""A two-stage toy program for the driver tests: plan (AUTHOR) -> freeze (CODE) -> check ->
gate -> a RUN step. Steps derive from disk: a stage is issued only when the previous one's
artifact exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from code_steer_model_write.artifacts.render import render
from code_steer_model_write.artifacts.store import Store
from code_steer_model_write.driver.steps import ProgramContext, Step, StepKind
from code_steer_model_write.spec.base import Artifact
from code_steer_model_write.state.run import RunPaths, RunState


class Plan(Artifact):
    blocks: list[str] = Field(min_length=1, description="block names")
    summary: str = Field(min_length=10, description="one paragraph")


class Findings(Artifact):
    findings: list[dict] = Field(default_factory=list)
    verdict: Literal["APPROVED", "REVISE"]


PROMPTS = Path(__file__).parent / "toy_prompts"


class ToyProgram:
    name = "toy"
    prompts_root = PROMPTS
    fixtures_root = None
    schemas = {"Plan": Plan, "Findings": Findings}

    def __init__(self, *, run_cmd: list[str] | None = None, check_problems: list[str] | None = None) -> None:
        self.run_cmd = run_cmd or ["python3", "-c", "open('out.txt','w').write('ok')"]
        self.check_problems = check_problems or []
        self.code_steps = {"freeze": self._freeze}
        self.checks = {"plan_ok": self._plan_ok}

    def _freeze(self, ctx: ProgramContext) -> None:
        sha = ctx.store.sha("plan")
        (ctx.paths.run_dir / "freeze.json").write_text(json.dumps({"plan_sha": sha}))

    def _plan_ok(self, ctx: ProgramContext) -> list[str]:
        return list(self.check_problems)

    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]:
        out = [
            Step(
                key="p0-plan",
                kind=StepKind.AUTHOR,
                phase="0",
                prompt="plan",
                schema_name="Plan",
                role="author",
                sets={"BRIEF_MD": "## Brief\n\n- **request**: a slug library\n"},
                rendered_keys=["brief"],
                land="plan",
                deliverables=["artifacts/plan/v001.json"],
                note="Claude writes the plan",
            )
        ]
        if store.exists("plan"):
            out.append(
                Step(
                    key="p0-freeze",
                    kind=StepKind.CODE,
                    phase="0",
                    after=["p0-plan"],
                    fn="freeze",
                    deliverables=["freeze.json"],
                    note="Freeze: the plan is hashed",
                )
            )
            out.append(
                Step(key="p0-check", kind=StepKind.CHECK, phase="0", after=["p0-freeze"], fn="plan_ok")
            )
            out.append(
                Step(
                    key="p0-gate",
                    kind=StepKind.GATE,
                    phase="0",
                    after=["p0-check"],
                    gate="blocks",
                    deliverables=["gates/blocks.decision.json"],
                    note="You confirm the blocks",
                )
            )
            out.append(
                Step(
                    key="p1-run",
                    kind=StepKind.RUN,
                    phase="1",
                    after=["p0-gate"],
                    command=self.run_cmd,
                    deliverables=["out.txt"],
                    note="the real run",
                )
            )
        return out

    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]:
        v = ctx.store.write(step.land, value)  # type: ignore[arg-type]
        (ctx.paths.run_dir / f"{step.land}.md").write_text(render(value))
        return [f"artifacts/{step.land}/v{v:03d}.json", f"{step.land}.md"]
