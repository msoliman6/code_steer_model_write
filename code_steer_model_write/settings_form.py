"""The one settings schema (docs/PLAN.md §7c; rule 4): every field of the start page, its
options, its default and the one-line reason for that default. The page renders FIELDS; the CLI
reads them (`csmw start --set key=value`); prefs.json remembers the last picks. A per-stage
model or effort row inherits from the plan row (`as plan`) or the checker row (`as checker`)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
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


def _stage_side_rows(recipe_name: str) -> list[FormField]:
    """Per stage, per side that stage uses (from the recipe's StageSpec): a model row and an
    effort row inheriting the side's base row. The start page lays these out under the stage's
    box; a new recipe gets its columns for free."""
    from .recipes import registry as recipes

    spec = recipes.get(recipe_name).spec
    out: list[FormField] = []
    for st in spec.stages:
        for role in ("author", "checker"):
            if not (st.author == role or st.checker == role):
                continue
            what = "writes" if st.author == role else "checks"
            out.append(
                FormField(
                    key=f"{st.id}_{role}_model",
                    name=f"{st.title} · {role} model",
                    group=f"stage:{st.id}",
                    description=f"The {role} {what} this stage; `as {role}` inherits the {role} row above",
                    options=[f"as {role}", *(AUTHOR_MODELS[1:] if role == "author" else CHECKER_MODELS[1:])],
                    default=f"as {role}",
                    inherits=f"{role}_model",
                )
            )
            out.append(
                FormField(
                    key=f"{st.id}_{role}_effort",
                    name=f"{st.title} · {role} effort",
                    group=f"stage:{st.id}",
                    description=f"Effort for the {role} on this stage; `as {role}` inherits the {role} row above",
                    options=[f"as {role}", *(AUTHOR_EFFORT[1:] if role == "author" else CHECKER_EFFORT)],
                    default=f"as {role}",
                    inherits=f"{role}_effort",
                )
            )
            out.append(
                FormField(
                    key=f"{st.id}_{role}_thinking",
                    name=f"{st.title} · {role} thinking",
                    group=f"stage:{st.id}",
                    description=f"Extended thinking for the {role} on this stage; `as {role}` inherits the {role} row above",
                    options=[f"as {role}", "off", "on"],
                    default=f"as {role}",
                    inherits=f"{role}_thinking",
                )
            )
    return out


def recipe_names() -> list[str]:
    from .recipes import registry as recipes

    return recipes.names()


def default_recipe() -> str:
    from .recipes import registry as recipes

    return recipes.default_name()


def recipe_of(values: dict[str, str]) -> str:
    """The recipe the form is for: the `recipe` value, else the default one."""
    return values.get("recipe") or default_recipe()


# the pre-selected setup (the one-round average task): the checker at high effort, the contract
# and verification rows carrying the judgment, the build on the cheapest model
STAGE_DEFAULTS = {
    "contracts_author_effort": "high",
    "verification_author_effort": "high",
    "build_author_model": "claude-haiku-4-5",
    "build_author_effort": "low",
}

UNIVERSAL_FIELDS: list[FormField] = [
    FormField(
        key="recipe",
        name="recipe",
        description="the workflow to run; every installed recipe package is listed, the bundled debate last",
        options=recipe_names(),
        default=default_recipe(),
    ),
    FormField(
        key="run_name",
        name="name",
        description="what you are building: the importable module's name (letters, digits, underscores); it is also the run's name and its folder under runs/, and a second run of the same name gets -2",
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
        key="author_backend",
        name="author backend",
        description="the claude CLI by default (its own login); the Anthropic SDK or the Agent SDK with a key; pydantic_ai for any provider through its API; fake offline",
        options=["claude_cli", "anthropic", "agent_sdk", "pydantic_ai", "fake"],
        default="claude_cli",
    ),
    FormField(
        key="author_model",
        name="author model",
        description="the author side's model, inherited by every stage row that says `as author`; `default` is CSMW_MODEL_A",
        options=AUTHOR_MODELS,
        default="claude-sonnet-5",
    ),
    FormField(
        key="author_effort",
        name="author effort",
        description="fastest; the saving usually returns as review rounds -- the checker finds what the author skipped",
        options=AUTHOR_EFFORT,
        default="low",
    ),
    FormField(
        key="author_thinking",
        name="author thinking",
        description="extended thinking on the author's calls: the API backends switch it on; Claude Code takes a thinking budget (16K tokens, `CSMW_THINKING_TOKENS`); off leaves each backend's own default",
        options=["off", "on"],
        default="off",
    ),
    FormField(
        key="checker_backend",
        name="checker backend",
        description="the other vendor (rule 3): codex exec by default; pydantic_ai for any provider through its API; fake for the offline walk",
        options=["codex_cli", "pydantic_ai", "fake"],
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
        key="author_budget",
        name="author tokens",
        group="ceilings",
        description="a ceiling on the author's tokens for the whole run; over it the run halts honestly and waits for the ceiling to be lifted, then resumes where it stopped (rule 14: tokens are the measure)",
        options=["none", "100K", "250K", "500K", "1M", "2M"],
        default="none",
    ),
    FormField(
        key="checker_budget",
        name="checker tokens",
        group="ceilings",
        description="the same ceiling for the checker; a live run so far spends 200K to 300K tokens in all, so 500K a side is a loose bound and 100K a tight one",
        options=["none", "100K", "250K", "500K", "1M", "2M"],
        default="none",
    ),
    FormField(
        key="total_budget",
        name="run tokens",
        group="ceilings",
        description="a ceiling on the run's tokens, both sides together; checked before every model call from the record, never estimated",
        options=["none", "250K", "500K", "1M", "2M", "5M"],
        default="none",
    ),
    FormField(
        key="max_calls",
        name="model calls",
        group="ceilings",
        description="a ceiling on the number of model calls; a one-round run makes 15 to 30, and every re-ask counts",
        options=["none", "25", "50", "100", "200"],
        default="none",
    ),
    FormField(
        key="max_minutes",
        name="minutes",
        group="ceilings",
        description="a ceiling on the run's wall clock; a one-round run takes 15 to 20 minutes on the CLI logins",
        options=["none", "15", "30", "60", "120", "240"],
        default="none",
    ),
    FormField(
        key="checker_thinking",
        name="checker thinking",
        description="extended thinking on the checker's calls: the API backends switch it on; Codex reasons at its effort and streams the reasoning in full; off leaves each backend's own default",
        options=["off", "on"],
        default="off",
    ),
]


@lru_cache(maxsize=None)
def fields_for(recipe_name: str) -> list[FormField]:
    """The universal fields, then the per-stage rows of that recipe."""
    out = [*UNIVERSAL_FIELDS, *_stage_side_rows(recipe_name)]
    for f in out:
        if f.key in STAGE_DEFAULTS:
            f.default = STAGE_DEFAULTS[f.key]
    return out


def all_fields() -> list[FormField]:
    """Every field any installed recipe can show, once each; the union that saved preferences,
    the CLI's `--set` and the run page's settings panel are keyed by."""
    seen: dict[str, FormField] = {}
    for name in recipe_names():
        for f in fields_for(name):
            seen.setdefault(f.key, f)
    return list(seen.values())


FIELDS: list[FormField] = all_fields()
BY_KEY = {f.key: f for f in FIELDS}


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
    f.key: ("checker_backend" if "checker" in f.key else "author_backend")
    for f in FIELDS
    if f.key.endswith("_model")
}
EFFORT_ROWS = {f.key: f.key[: -len("_effort")] + "_model" for f in FIELDS if f.key.endswith("_effort")}
INHERIT_WORDS = ("default", "as author", "as checker")


def _inherit_word(key: str) -> str | None:
    f = BY_KEY[key]
    return f.options[0] if f.options and f.options[0] in INHERIT_WORDS else None


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
    if out["author_model"] == "default":
        out["plan_model"] = (
            s.model_a if s.model_a else providers.for_backend(out["author_backend"]).default_model()
        )
    if out["checker_model"] == "default":
        out["checker_model"] = (
            s.model_b if s.model_b else providers.for_backend(out["checker_backend"]).default_model()
        )
    for f in FIELDS:
        if f.key.endswith("_model") and out[f.key] == "default":
            out[f.key] = out["checker_model"] if "checker" in f.key else out["author_model"]
    for f in FIELDS:
        if f.inherits and out[f.key] in INHERIT_WORDS:
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
    return [
        f.name for f in fields_for(recipe_of(values)) if f.required and not (values.get(f.key) or "").strip()
    ]


def module_of(name: str) -> str:
    """The module name from the form's name: lowercase, non-identifier characters to underscores."""
    m = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
    return m or "module"


def build_task(values: dict[str, str], *, recipe: str | None = None) -> TaskSpec:
    """The TaskSpec from the form: roles from the plan row and the checker row; every other stage
    row goes into metadata.stage_settings, which the recipe applies per step."""
    recipe = recipe or recipe_of(values)
    v = resolve(values)
    lines = lambda key: [ln.strip() for ln in (values.get(key) or "").splitlines() if ln.strip()]  # noqa: E731
    brief = {
        "request": values.get("request", ""),
        "context": values.get("context", ""),
        "must_be_true": lines("must_be_true"),
        "out_of_scope": lines("out_of_scope"),
        "module": module_of(values.get("run_name", "")),
        "surface": "",
        "known_reference": "",
        "language": "python",
        "constraints": [],
    }
    roles = {
        "author": RoleSpec(
            backend=BackendName(v["author_backend"]),
            model=v["author_model"],
            effort=v["author_effort"],
            thinking=v.get("author_thinking", "off") == "on",
        ),
        "checker": RoleSpec(
            backend=BackendName(v["checker_backend"]),
            model=v["checker_model"],
            effort=v["checker_effort"],
            thinking=v.get("checker_thinking", "off") == "on",
        ),
    }
    stage_settings: dict[str, dict[str, dict[str, str]]] = {}
    for f in fields_for(recipe):
        if f.group.startswith("stage:") and f.key.endswith("_model"):
            stage = f.group.split(":", 1)[1]
            role = "checker" if f.key.endswith("_checker_model") else "author"
            stage_settings.setdefault(stage, {})[role] = {
                "model": v[f.key],
                "effort": v[f"{stage}_{role}_effort"],
                "thinking": v.get(f"{stage}_{role}_thinking", "off"),
            }

    def tokens(x: str) -> int | None:
        x = (x or "none").strip().upper()
        if x in ("", "NONE"):
            return None
        return int(float(x[:-1]) * (1_000_000 if x.endswith("M") else 1_000)) if x[-1] in "KM" else int(x)

    def count(x: str) -> int | None:
        x = (x or "none").strip()
        return None if x.lower() in ("", "none") else int(x)

    roles["author"] = roles["author"].model_copy(update={"budget_tokens": tokens(v.get("author_budget", ""))})
    roles["checker"] = roles["checker"].model_copy(
        update={"budget_tokens": tokens(v.get("checker_budget", ""))}
    )
    return TaskSpec(
        task_id=values.get("run_name", "run").strip() or "run",
        objective=brief["request"][:200],
        recipe=recipe,
        inputs={"brief": brief, "fix_rounds": 1},
        roles=roles,
        max_tokens_total=tokens(v.get("total_budget", "")),
        max_llm_calls=count(v.get("max_calls", "")),
        max_runtime_minutes=count(v.get("max_minutes", "")),
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
        update={
            "model": over.get("model", base.model),
            "effort": over.get("effort", base.effort),
            "thinking": (over["thinking"] == "on") if "thinking" in over else base.thinking,
        }
    )


def _stage_meta(f: FormField, recipe_name: str) -> dict[str, str]:
    """For a per-stage row: the side (author/checker), its function on that stage (writer or
    checker), and the field (model/effort); the page lays the pair out on one line."""
    if not f.group.startswith("stage:"):
        # a side's base row: the field is the word after the side (backend, model, effort, thinking)
        field = f.key.split("_", 1)[1] if f.key.startswith(("author_", "checker_")) else ""
        return {"side": "", "func": "", "field": field}
    from .recipes import registry as recipes

    stage = f.group.split(":", 1)[1]
    side = "checker" if "_checker_" in f.key else "author"
    st = next(x for x in recipes.get(recipe_name).spec.stages if x.id == stage)
    func = st.side_labels.get(side) or ("writer" if st.author == side else "checker")
    field = (
        "effort" if f.key.endswith("_effort") else ("thinking" if f.key.endswith("_thinking") else "model")
    )
    return {"side": side, "func": func, "field": field}


def form_model(values: dict[str, str]) -> list[dict[str, Any]]:
    """What the page renders: one card per field, the selected value, the options now (model
    catalogues per backend, efforts per model). A selected value the options no longer hold
    falls back to the first option, so the page never shows a chip that cannot be sent."""
    v = {**defaults(), **values}
    recipe = recipe_of(v)
    out = []
    for f in fields_for(recipe):
        opts = options_for(f.key, v)
        val = v.get(f.key, f.default)
        if f.kind == "chips" and opts and val not in opts:
            val = f.default if f.default in opts else opts[0]
        out.append(
            {
                "key": f.key,
                "name": f.name[:1].upper() + f.name[1:],
                "description": sentence(f.description),
                "kind": f.kind,
                "options": opts,
                "value": val,
                "group": f.group,
                "required": f.required,
                "discovery": (
                    providers.for_backend(v[MODEL_ROWS[f.key]]).model_discovery if f.key in MODEL_ROWS else ""
                ),
                **_stage_meta(f, recipe),
            }
        )
    return out
