"""The one settings schema (docs/PLAN.md §7c; rule 4): every field of the start page, its
options, its default and the one-line reason for that default. The page renders FIELDS; the CLI
reads them (`csmw start --set key=value`); prefs.json remembers the last picks. A per-stage
model or effort row inherits from the plan row (`as plan`) or the checker row (`as checker`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import BackendName, Mode, RoleSpec, Settings
from .providers import registry as providers
from .providers.base import default_effort_for, efforts_for
from .spec.task import TaskSpec

AUTHOR_MODELS = ["default", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
CHECKER_MODELS = ["default", "gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
AUTHOR_EFFORT = ["default", "max", "xhigh", "high", "medium", "low"]
CHECKER_EFFORT = ["xhigh", "high", "medium", "low"]


class FormField(BaseModel):
    key: str
    name: str
    description: str = Field(description="the default's reasoning, one sentence")
    kind: Literal["chips", "text", "textarea", "lines"] = "chips"
    options: list[str] = Field(default_factory=list)
    default: str = ""
    group: str = "settings"
    required: bool = False
    inherits: str | None = None  # the key the first chip ("as plan" / "as checker") inherits from


def _stage_rows(
    stage: str, title: str, what: str, model_default: str, effort_default: str, effort_reason: str
) -> list[FormField]:
    return [
        FormField(
            key=f"{stage}_model",
            name=f"{title} model",
            description=what,
            options=["as plan", *AUTHOR_MODELS[1:]],
            default=model_default,
            inherits="plan_model",
        ),
        FormField(
            key=f"{stage}_effort",
            name=f"{title} effort",
            description=effort_reason,
            options=["as plan", *AUTHOR_EFFORT[1:]],
            default=effort_default,
            inherits="plan_effort",
        ),
    ]


FIELDS: list[FormField] = [
    FormField(
        key="run_name",
        name="run name",
        description="the folder under runs/ and the page's title",
        kind="text",
        group="brief",
        required=True,
    ),
    FormField(
        key="request",
        name="request",
        description="what to build, one paragraph, in your words",
        kind="textarea",
        group="brief",
        required=True,
    ),
    FormField(
        key="context",
        name="context",
        description="where it runs, who calls it, what exists already",
        kind="textarea",
        group="brief",
    ),
    FormField(
        key="must_be_true",
        name="must be true",
        description="one observable claim per line",
        kind="lines",
        group="brief",
    ),
    FormField(
        key="out_of_scope",
        name="out of scope",
        description="a boundary, not a suggestion: never a unit, never a step; one per line",
        kind="lines",
        group="brief",
    ),
    FormField(
        key="module",
        name="module",
        description="the importable module name the surface lives in",
        kind="text",
        group="brief",
        default="slug",
    ),
    FormField(
        key="mode",
        name="running mode",
        description="every decision at the block and verification gates comes to you as a question. Slowest, and the one that teaches you the pipeline; `light` asks only the risky ones and every input gate; `auto` asks nothing and flags every default it took",
        options=[m.value for m in Mode],
        default="light",
    ),
    FormField(
        key="rounds",
        name="attack rounds",
        description="one pass catches omissions and format errors, never a deep one -- nothing re-reads the revision; two is the average task; each round spent costs one review and one arbitration that re-emits the whole artifact",
        options=["1", "2", "3", "4"],
        default="1",
    ),
    FormField(
        key="checker_backend",
        name="checker backend",
        description="the other vendor (rule 3): codex exec by default; litellm for any provider; fake for the offline walk",
        options=["codex_cli", "litellm", "fake"],
        default="codex_cli",
    ),
    FormField(
        key="checker_model",
        name="checker model",
        description="the checker CLI's own choice -- always works, survives renames; a named model pins the review's strength",
        options=CHECKER_MODELS,
        default="default",
    ),
    FormField(
        key="checker_effort",
        name="checker effort",
        description="the default: adversarial reading is the job, and a weak review looks exactly like convergence",
        options=CHECKER_EFFORT,
        default="high",
    ),
    FormField(
        key="author_backend",
        name="author backend",
        description="the claude CLI by default (its own login); the Anthropic SDK or the Agent SDK with a key; litellm for any provider; fake offline",
        options=["claude_cli", "anthropic", "agent_sdk", "litellm", "fake"],
        default="claude_cli",
    ),
    FormField(
        key="plan_model",
        name="plan model",
        description="the plan row's model, for stage 0 (Plan) and its arbitrations; `default` is CSMW_MODEL_A",
        options=AUTHOR_MODELS,
        default="claude-sonnet-5",
    ),
    FormField(
        key="plan_effort",
        name="plan effort",
        description="fastest; the saving usually returns as review rounds -- the checker finds what the author skipped",
        options=AUTHOR_EFFORT,
        default="low",
    ),
    *_stage_rows(
        "contracts",
        "contracts",
        "stage 1 only -- the contract is what every later stage cites, so it is where a stronger model pays",
        "claude-sonnet-5",
        "high",
        "the default: a loose clause costs a whole review round, so effort here is cheaper than the round it saves",
    ),
    *_stage_rows(
        "verification",
        "verification",
        "stage 2 only -- the coverage review and its arbitrations",
        "claude-sonnet-5",
        "high",
        "the default: a loose clause costs a whole review round, so effort here is cheaper than the round it saves",
    ),
    *_stage_rows(
        "build",
        "build",
        "stage 3 only -- many mechanical units against an algorithm already written; the cheapest model does it",
        "claude-haiku-4-5",
        "low",
        "fastest; the saving usually returns as review rounds -- the checker finds what the author skipped",
    ),
    FormField(
        key="verify_author_model",
        name="verif. run author",
        description="stage 4's rulings and source fixes on the plan model",
        options=["as plan", *AUTHOR_MODELS[1:]],
        default="as plan",
        inherits="plan_model",
    ),
    FormField(
        key="verify_author_effort",
        name="verif. run author effort",
        description="inherit the plan effort",
        options=["as plan", *AUTHOR_EFFORT[1:]],
        default="as plan",
        inherits="plan_effort",
    ),
    FormField(
        key="verify_checker_model",
        name="verif. run checker",
        description="stage 4's triage and test fixes on the checker row's model",
        options=["as checker", *CHECKER_MODELS[1:]],
        default="as checker",
        inherits="checker_model",
    ),
    FormField(
        key="verify_checker_effort",
        name="verif. run checker effort",
        description="inherit the checker row's effort",
        options=["as checker", *CHECKER_EFFORT],
        default="as checker",
        inherits="checker_effort",
    ),
]

BY_KEY = {f.key: f for f in FIELDS}
STAGE_OF_KEY = {
    "plan": "plan",
    "contracts": "contracts",
    "verification": "verification",
    "build": "build",
    "verify_author": "verify",
    "verify_checker": "verify",
}


def sentence(text: str) -> str:
    """The page's punctuation rule: a description is a sentence -- it starts with a capital,
    it ends with a full stop, and a double hyphen becomes a semicolon."""
    t = text.strip().replace(" -- ", "; ").replace("--", ";")
    if not t:
        return t
    t = t[0].upper() + t[1:]
    return t if t.endswith((".", "!", "?")) else t + "."


def defaults() -> dict[str, str]:
    return {f.key: f.default for f in FIELDS}


MODEL_ROWS = {
    "checker_model": "checker_backend",
    "plan_model": "author_backend",
    "contracts_model": "author_backend",
    "verification_model": "author_backend",
    "build_model": "author_backend",
    "verify_author_model": "author_backend",
    "verify_checker_model": "checker_backend",
}
EFFORT_ROWS = {
    "checker_effort": "checker_model",
    "plan_effort": "plan_model",
    "contracts_effort": "contracts_model",
    "verification_effort": "verification_model",
    "build_effort": "build_model",
    "verify_author_effort": "verify_author_model",
    "verify_checker_effort": "verify_checker_model",
}


def _inherit_word(key: str) -> str | None:
    f = BY_KEY[key]
    return f.options[0] if f.options and f.options[0] in ("default", "as plan", "as checker") else None


def options_for(key: str, values: dict[str, str]) -> list[str]:
    """The chips a row shows now: model rows list the provider's catalogue for the chosen
    backend; effort rows list what the row's resolved model supports (rule: never a flat
    effort list). The inherit chip stays first."""
    f = BY_KEY[key]
    v = {**defaults(), **values}
    if key in MODEL_ROWS:
        prov = providers.for_backend(v[MODEL_ROWS[key]])
        first = _inherit_word(key)
        return ([first] if first else []) + [m.id for m in prov.list_models()]
    if key in EFFORT_ROWS:
        model_key = EFFORT_ROWS[key]
        r = resolve(v)
        prov = providers.for_backend(v[MODEL_ROWS[model_key]])
        first = _inherit_word(key)
        return ([first] if first else []) + efforts_for(
            prov.list_models(), r[model_key], f.options[1:] if first else f.options
        )
    return list(f.options)


def prefs_path(runs_dir: Path | str) -> Path:
    return (
        Path(runs_dir).parent / "prefs.json"
        if Path(runs_dir).name == "runs"
        else Path(runs_dir) / "prefs.json"
    )


def load_prefs(runs_dir: Path | str) -> dict[str, str]:
    p = prefs_path(runs_dir)
    if not p.exists():
        return {}
    saved = json.loads(p.read_text())
    return {
        k: v for k, v in saved.items() if k in BY_KEY and BY_KEY[k].kind == "chips" and v in BY_KEY[k].options
    }


def save_prefs(runs_dir: Path | str, values: dict[str, str]) -> None:
    p = prefs_path(runs_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({k: v for k, v in values.items() if k in BY_KEY and BY_KEY[k].kind == "chips"}, indent=2)
    )


def resolve(values: dict[str, str]) -> dict[str, str]:
    """Every field with a value: prefs over defaults; `default` resolved to the side's model; then
    `as plan` / `as checker` resolved from the row they inherit."""
    out = {**defaults(), **{k: v for k, v in values.items() if k in BY_KEY}}
    s = Settings()
    if out["plan_model"] == "default":
        out["plan_model"] = (
            s.model_a if s.model_a else providers.for_backend(out["author_backend"]).default_model()
        )
    if out["checker_model"] == "default":
        out["checker_model"] = (
            s.model_b if s.model_b else providers.for_backend(out["checker_backend"]).default_model()
        )
    for f in FIELDS:
        if f.key.endswith("_model") and out[f.key] == "default":
            out[f.key] = out["checker_model"] if "checker" in f.key else out["plan_model"]
    for f in FIELDS:
        if f.inherits and out[f.key] in ("as plan", "as checker"):
            out[f.key] = out[f.inherits]
    for key, model_key in EFFORT_ROWS.items():
        prov = providers.for_backend(out[MODEL_ROWS[model_key]])
        models = prov.list_models()
        if out[key] == "default":
            out[key] = default_effort_for(models, out[model_key], "medium")
        allowed = efforts_for(models, out[model_key], [out[key]])
        if out[key] not in allowed:
            out[key] = default_effort_for(
                models, out[model_key], allowed[0]
            )  # a model that lacks the level gets its default
    return out


def missing_required(values: dict[str, str]) -> list[str]:
    return [f.name for f in FIELDS if f.required and not (values.get(f.key) or "").strip()]


def build_task(values: dict[str, str], *, recipe: str = "code_builder") -> TaskSpec:
    """The TaskSpec from the form: roles from the plan row and the checker row; every other stage
    row goes into metadata.stage_settings, which the recipe applies per step."""
    v = resolve(values)
    lines = lambda key: [ln.strip() for ln in (values.get(key) or "").splitlines() if ln.strip()]  # noqa: E731
    brief = {
        "request": values.get("request", ""),
        "context": values.get("context", ""),
        "must_be_true": lines("must_be_true"),
        "out_of_scope": lines("out_of_scope"),
        "module": values.get("module") or "slug",
        "surface": "",
        "known_reference": "",
        "language": "python",
        "constraints": [],
    }
    roles = {
        "author": RoleSpec(
            backend=BackendName(v["author_backend"]), model=v["plan_model"], effort=v["plan_effort"]
        ),
        "checker": RoleSpec(
            backend=BackendName(v["checker_backend"]), model=v["checker_model"], effort=v["checker_effort"]
        ),
    }
    stage_settings: dict[str, dict[str, dict[str, str]]] = {
        "plan": {"author": {"model": v["plan_model"], "effort": v["plan_effort"]}},
        "contracts": {"author": {"model": v["contracts_model"], "effort": v["contracts_effort"]}},
        "verification": {"author": {"model": v["verification_model"], "effort": v["verification_effort"]}},
        "build": {"author": {"model": v["build_model"], "effort": v["build_effort"]}},
        "verify": {
            "author": {"model": v["verify_author_model"], "effort": v["verify_author_effort"]},
            "checker": {"model": v["verify_checker_model"], "effort": v["verify_checker_effort"]},
        },
    }
    return TaskSpec(
        task_id=values.get("run_name", "run").strip() or "run",
        objective=brief["request"][:200],
        recipe=recipe,
        inputs={"brief": brief, "fix_rounds": 1},
        roles=roles,
        swaps=[("author", "checker")],
        require_cross_vendor=(v["author_backend"] != "fake"),
        mode=Mode(v["mode"]),
        rounds=int(v["rounds"]),
        metadata={"stage_settings": stage_settings, "form": {k: values.get(k, "") for k in BY_KEY}},
    )


def stage_role(task: TaskSpec, stage: str, role: str) -> RoleSpec:
    """The role for a stage: the form's per-stage row when the task carries one, else the role."""
    base = task.roles[role]
    over = (task.metadata.get("stage_settings") or {}).get(stage, {}).get(role)
    if not over:
        return base
    return base.model_copy(
        update={"model": over.get("model", base.model), "effort": over.get("effort", base.effort)}
    )


def form_model(values: dict[str, str]) -> list[dict[str, Any]]:
    """What the page renders: one card per field, the selected value, the options."""
    v = {**defaults(), **values}
    return [
        {
            "key": f.key,
            "name": f.name,
            "description": sentence(f.description),
            "kind": f.kind,
            "options": f.options,
            "value": v.get(f.key, f.default),
            "group": f.group,
            "required": f.required,
        }
        for f in FIELDS
    ]
