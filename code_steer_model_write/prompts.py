"""Prompt templates -- code-filled text a fresh process is handed once (rule 13).

`prompts/<name>.md` holds `{{KEY}}` placeholders. `fill()` refuses a key with no value AND a
value with no key (content computed and delivered nowhere) before a token is spent. A value
must be text: markdown rendered by code from JSON (rule 2); a value that is itself JSON is
refused. The system part is written by code from the schema: the template, the guide, the
re-ask budget, the tool denial as a statement of fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from .config import RE_ASK_MAX
from .spec.base import Artifact

KEY_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class Template(BaseModel):
    name: str
    text: str
    keys: list[str]

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]


class FilledPrompt(BaseModel):
    name: str
    system: str
    user: str
    keys: dict[str, str]
    template_hash: str
    rendered_keys: list[str]  # the artifact keys whose markdown was inlined (walk assertion)

    @property
    def sha(self) -> str:
        return hashlib.sha256((self.system + "\n\n" + self.user).encode("utf-8")).hexdigest()[:12]


class PromptError(ValueError):
    pass


def load(name: str, root: Path | None = None) -> Template:
    path = (root or PROMPTS_DIR) / f"{name}.md"
    if not path.exists():
        raise PromptError(f"no prompt template {name!r} at {path}")
    text = path.read_text(encoding="utf-8")
    keys = sorted(set(KEY_RE.findall(text)))
    return Template(name=name, text=text, keys=keys)


def _looks_like_json(value: str) -> bool:
    v = value.strip()
    if not v or v[0] not in "{[":
        return False
    try:
        json.loads(v)
        return True
    except ValueError:
        return False


def fill(
    t: Template,
    sets: dict[str, str],
    *,
    schema: type[Artifact],
    rendered_keys: list[str] | None = None,
    needs_tools: bool = False,
) -> FilledPrompt:
    missing = [k for k in t.keys if k not in sets]
    unused = [k for k in sets if k not in t.keys]
    if missing:
        raise PromptError(f"prompt {t.name!r}: no value for {missing} -- refused before a token is spent")
    if unused:
        raise PromptError(f"prompt {t.name!r}: values with no key {unused} -- content delivered nowhere")
    for k, v in sets.items():
        if not isinstance(v, str):
            raise PromptError(
                f"prompt {t.name!r}: value for {k} is {type(v).__name__}, not text (render it first)"
            )
        if _looks_like_json(v):
            raise PromptError(
                f"prompt {t.name!r}: value for {k} is raw JSON -- a model reads markdown rendered by code (rule 2)"
            )
    user = KEY_RE.sub(lambda m: sets[m.group(1)], t.text)
    return FilledPrompt(
        name=t.name,
        system=how_to_answer(schema, needs_tools=needs_tools),
        user=user,
        keys=dict(sets),
        template_hash=t.sha,
        rendered_keys=list(rendered_keys or []),
    )


def how_to_answer(schema: type[Artifact], *, needs_tools: bool = False, re_ask_max: int = RE_ASK_MAX) -> str:
    tools = (
        "You have the tools listed in this conversation and nothing else; every call is logged."
        if needs_tools
        else "You have no tools, no files, no shell and no way to read anything -- everything you need is in this message."
    )
    return "\n".join(
        [
            f"You answer with ONE JSON object matching the `{schema.schema_name()}` schema; the backend enforces it.",
            tools,
            "Code writes every file and assigns every id. Cite ids you were given; never invent one.",
            f"An answer that fails a check is sent back to you with the exact problems, at most {re_ask_max} times.",
            "",
            "## The shape of your answer",
            "",
            "```json",
            schema.template(),
            "```",
            "",
            "## What goes in each field",
            "",
            schema.guide(),
        ]
    )


def re_ask_suffix(problems: list[str], refused_answer: dict | None) -> str:
    """Appended to the user prompt on a re-ask: the exact problems and the refused answer,
    verbatim (rule 6). The model revises the artifact; it never explains."""
    lines = [
        "",
        "---",
        "",
        "## Your previous answer was refused",
        "",
        "Fix every problem below and answer again in full:",
        "",
    ]
    lines += [f"- {p}" for p in problems]
    if refused_answer is not None:
        lines += [
            "",
            "## The refused answer",
            "",
            "```json",
            json.dumps(refused_answer, indent=2, ensure_ascii=False),
            "```",
        ]
    return "\n".join(lines)
