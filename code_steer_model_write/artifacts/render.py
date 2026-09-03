"""JSON -> markdown, by code, for the next model or the human (rule 2, rule 4).

The one place an artifact becomes text a model reads. A dict or a raw JSON string is refused:
only an `Artifact` renders. Two audiences:
  - "model": ids kept verbatim (the model must cite them);
  - "human": ids resolved to words with the id in parentheses, so a raw `C-0051` never stands
    alone in front of a person (ledger: "a raw id in human text").
`drop` removes top-level fields for a role's view (the test-visible contract has no
`algorithm`). Rendering is pure: same JSON -> same markdown.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel

from ..ids import ANY_ID_RE
from ..spec.base import Artifact

Audience = Literal["model", "human"]


def render(
    obj: Any,
    audience: Audience = "model",
    *,
    drop: Iterable[str] = (),
    glossary: dict[str, str] | None = None,
    title: str | None = None,
    level: int = 2,
) -> str:
    if not isinstance(obj, Artifact):
        raise TypeError(
            f"only an Artifact renders; got {type(obj).__name__} (rule 2: no raw JSON in a prompt)"
        )
    text = obj.render_md(audience=audience, drop=set(drop))
    if text is None:
        text = render_generic(obj, drop=set(drop), title=title or _title(type(obj).__name__), level=level)
    if audience == "human" and glossary:
        text = resolve_ids(text, glossary)
    return text.rstrip() + "\n"


def resolve_ids(text: str, glossary: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        i = f"{m.group(1)}-{m.group(2)}"
        words = glossary.get(i)
        return f"{words} ({i})" if words else i

    return ANY_ID_RE.sub(sub, text)


def _title(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


def _scalar(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.replace("|", "\\|").replace("\n", " ")
    if isinstance(v, list):
        return ", ".join(_scalar(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_scalar(x)}" for k, x in v.items())
    if isinstance(v, BaseModel):
        return _scalar(v.model_dump())
    return str(v)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def render_generic(
    obj: BaseModel, *, drop: set[str] = frozenset(), title: str | None = None, level: int = 2
) -> str:
    h = "#" * min(level, 6)
    out: list[str] = []
    if title:
        out.append(f"{h} {title}")
        out.append("")
    fields = {k: getattr(obj, k) for k in type(obj).model_fields if k not in drop}
    scalars = {
        k: v
        for k, v in fields.items()
        if _is_scalar(v) or (isinstance(v, list) and all(_is_scalar(x) for x in v))
    }
    for k, v in scalars.items():
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, str) and "\n" in v:
            out.append(f"**{k}**")
            out.append("")
            out.append(v.strip())
            out.append("")
        else:
            out.append(f"- **{k}**: {_scalar(v)}")
    if scalars:
        out.append("")
    for k, v in fields.items():
        if k in scalars:
            continue
        sub = "#" * min(level + 1, 6)
        if isinstance(v, BaseModel):
            out.append(render_generic(v, title=f"{k}", level=level + 1).rstrip())
            out.append("")
        elif isinstance(v, list) and v and all(isinstance(x, BaseModel) for x in v):
            out.append(f"{sub} {k}")
            out.append("")
            out.append(_table(v))
            out.append("")
        elif isinstance(v, list) and not v:
            out.append(f"{sub} {k}")
            out.append("")
            out.append("(none)")
            out.append("")
        elif isinstance(v, dict):
            out.append(f"{sub} {k}")
            out.append("")
            for kk, vv in v.items():
                out.append(f"- **{kk}**: {_scalar(vv)}")
            out.append("")
        else:
            out.append(f"- **{k}**: {_scalar(v)}")
    return "\n".join(out).rstrip() + "\n"


def _table(rows: list[BaseModel]) -> str:
    cols = [c for c in type(rows[0]).model_fields]
    # a nested list-of-models column is rendered inline; long text stays in the cell
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(_scalar(getattr(r, c)) for c in cols) + " |")
    return "\n".join(lines)
