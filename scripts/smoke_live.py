"""One real call per configured backend (rule 12: live is the backstop, the walk is the proof).
Costs tokens. Asserts: the answer conforms, no id was typed by the model, tokens were reported.

    .venv/bin/python scripts/smoke_live.py anthropic claude_cli codex_cli litellm
    CSMW_MODEL_A / CSMW_MODEL_B pick the model per side (anthropic-family backends use A, others B).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from code_steer_model_write.ask import CallContext, ask
from code_steer_model_write.backends import registry
from code_steer_model_write.config import BackendName, RoleSpec, Settings
from code_steer_model_write.events import EventLog
from code_steer_model_write.prompts import Template, fill
from code_steer_model_write.spec.base import CheckContext
from code_steer_model_write.spec.findings import Findings

PROMPT = Template(
    name="smoke",
    text=(
        "You are the reviewer. Review this contract clause and file at most one minor finding citing C-0001, "
        "or approve.\n\n## The contract\n\n| id | claim |\n|---|---|\n| C-0001 | the result has at most MAX_LEN characters |\n"
    ),
    keys=[],
)


def main(names: list[str]) -> int:
    s = Settings()
    rc = 0
    for name in names:
        bn = BackendName(name)
        model = (
            s.model_a
            if bn in (BackendName.ANTHROPIC, BackendName.AGENT_SDK, BackendName.CLAUDE_CLI)
            else s.model_b
        )
        tmp = Path(tempfile.mkdtemp(prefix=f"csmw-smoke-{name}-"))
        log = EventLog(tmp / "events.jsonl", "smoke")
        ctx = CallContext(
            backend=registry.make(bn),
            role_spec=RoleSpec(backend=bn, model=model, effort="low"),
            events=log,
            step=f"smoke-{name}",
            streams_dir=tmp / "streams",
            check_ctx=CheckContext(known_ids={"C-0001"}),
            stall_seconds=300,
        )
        prompt = fill(PROMPT, {}, schema=Findings)
        r = ask(prompt, Findings, role="reviewer", ctx=ctx)
        ok = hasattr(r, "value")
        usage = r.usage
        line = f"{name:12s} {model:28s} {'ok ' if ok else 'REFUSED'} attempts={getattr(r, 'attempts', '-')} tokens={usage.total} "
        line += (
            f"verdict={r.value.verdict} findings={len(r.value.findings)}"
            if ok
            else f"reason={r.reason}: {r.message[:200]}"
        )
        print(line, f"  ({tmp})")
        if not ok:
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["anthropic"]))
