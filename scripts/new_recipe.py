"""csmw new-recipe <name>: copy the skeleton into code_steer_model_write/recipes/<name>/, prompts/<name>/,
fixtures/<name>/, examples/<name>/, and register it. Then: spec.py -> fixtures -> prompts -> `just walk <name>` green."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKELETON = '''"""The {name} recipe -- status: unproven until one clean live pass (docs/ADD-A-RECIPE.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from ...artifacts.brief import Brief
from ...artifacts.store import Store
from ...driver.steps import ProgramContext, Step, StepKind
from ...gates.gate import GateBuilder
from ...spec.base import Artifact
from ...spec.decisions import Gate
from ...state.run import RunPaths, RunState
from ..base import CheckKind, EvalSpec, FigurePhrases, GateSpec, Recipe, RecipeSpec, StageSpec

ROOT = Path(__file__).resolve().parents[3]


class {cls}Params(BaseModel):
    brief: Brief


SPEC = RecipeSpec(
    name="{name}",
    version="0.1.0",
    status="unproven",
    assumes=["say what this recipe assumes about its inputs"],
    if_wrong=["say what breaks if that is wrong"],
    params_model={cls}Params,
    roles={{"author": "a", "checker": "b"}},
    stages=[
        StageSpec(id="draft", n=0, title="Draft", emoji="✍️", hue="blue", author="author", checker="checker",
                  description="The author drafts; the checker attacks it for rounds.",
                  figure=FigurePhrases(author="{{A}} writes the draft", checker="{{B}} attacks it", rounds="rounds")),
    ],
    gates=[GateSpec(id="brief", after_stage="draft", kind="input", trigger="always", title="Confirm the brief", figure_label="You confirm the brief")],
    evals=[EvalSpec(metric="carried_findings", tier="code", target=0, higher_is_better=False)],
    required_checks={{CheckKind.SCHEMA, CheckKind.CITES_RESOLVE, CheckKind.AI_REVIEW, CheckKind.HUMAN_GATE, CheckKind.ARBITRATION_ENGAGES}},
)


class {cls}(Recipe):
    spec = SPEC
    prompts_root = ROOT / "prompts" / "{name}"
    fixtures_root = ROOT / "fixtures" / "{name}"

    def __init__(self) -> None:
        self.schemas: dict[str, type[Artifact]] = {{}}
        self.code_steps: dict[str, Callable[[ProgramContext], None]] = {{"brief": self._c_brief}}
        self.checks: dict[str, Callable[[ProgramContext], list[str]]] = {{}}

    def provided_checks(self) -> set[CheckKind]:
        return {{CheckKind.SCHEMA, CheckKind.CITES_RESOLVE, CheckKind.AI_REVIEW, CheckKind.HUMAN_GATE, CheckKind.ARBITRATION_ENGAGES}}

    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]:
        out = [Step(key="p0-brief", kind=StepKind.CODE, phase="0", fn="brief", deliverables=["artifacts/brief/v001.json"], note="code writes the brief")]
        # derive every later step from the files in `store` and `paths` (rule 1); never from a counter
        return out

    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]:
        v = ctx.store.write(step.land or "artifact", value)
        return [f"artifacts/{{step.land}}/v{{v:03d}}.json"]

    def gate_builders(self) -> dict[str, GateBuilder]:
        return {{"brief": lambda step, ctx: Gate(id=step.gate or "brief.r1", name="brief", kind="input", title="Confirm the brief", questions=[])}}

    def fakers(self, paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
        return {{}}

    def _c_brief(self, ctx: ProgramContext) -> None:
        ctx.store.write("brief", self.params(ctx.state.task).brief)
'''


def main(name: str) -> int:
    if not re.match(r"^[a-z][a-z0-9_]+$", name):
        print("refused: a recipe name is a python identifier in snake_case")
        return 2
    cls = "".join(p.capitalize() for p in name.split("_"))
    pkg = ROOT / "code_steer_model_write" / "recipes" / name
    if pkg.exists():
        print(f"refused: {pkg} exists")
        return 2
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "recipe.py").write_text(SKELETON.format(name=name, cls=cls))
    for d in (ROOT / "prompts" / name, ROOT / "fixtures" / name, ROOT / "examples" / name):
        d.mkdir(parents=True, exist_ok=True)
    (ROOT / "examples" / name / "task.json").write_text(
        '{\n  "task_id": "%s-demo",\n  "objective": "say what to do",\n  "recipe": "%s",\n  "inputs": {"brief": {"request": "say what to build, in one paragraph"}},\n'
        '  "roles": {"author": {"backend": "claude_cli", "model": "claude-sonnet-5"}, "checker": {"backend": "codex_cli", "model": "gpt-5.4-mini"}},\n'
        '  "swaps": [["author", "checker"]],\n  "mode": "light",\n  "rounds": 1\n}\n' % (name, name)
    )
    reg = ROOT / "code_steer_model_write" / "recipes" / "registry.py"
    s = reg.read_text()
    row = f'    "{name}": ("code_steer_model_write.recipes.{name}.recipe", "{cls}"),\n'
    if row not in s:
        s = s.replace(
            '_BUILTIN: dict[str, tuple[str, str]] = {\n',
            '_BUILTIN: dict[str, tuple[str, str]] = {\n' + row,
            1,
        )
    reg.write_text(s)
    print(
        "note: a recipe that is a project of its own registers by entry point instead (docs/ADD-A-RECIPE.md)"
    )
    print(f"created recipes/{name}, prompts/{name}, fixtures/{name}, examples/{name}; registered.")
    print(
        f"next: spec.py -> fixtures (fakers) -> prompts -> `just walk {name}` green -> flip status to proven after one live pass"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
