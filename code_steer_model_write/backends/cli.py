"""The `claude -p` and `codex exec` backends (rule 2, 13): the schema on the command line, every
tool disabled, the prompt on stdin, JSONL facts on stdout through streams.py."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .base import CallResult, CallSpec, Capabilities, Fact, SchemaMode, Usage
from .streams import run_jsonl

CLAUDE_ALL_TOOLS = [
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "Task",
    "Agent",
    "TodoWrite",
    "MultiEdit",
]


def _claude_parse(obj: dict[str, Any]) -> list[Fact]:
    t = obj.get("type")
    if t == "system" and obj.get("subtype") == "init":
        return [
            Fact(
                kind="note",
                text="init",
                data={
                    "tools": obj.get("tools", []),
                    "mcp_servers": obj.get("mcp_servers", []),
                    "model": obj.get("model"),
                },
            )
        ]
    if t == "assistant":
        msg = obj.get("message", {})
        out: list[Fact] = []
        for block in msg.get("content", []):
            bt = block.get("type")
            if bt == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                    out.append(
                        Fact(kind="write", text=name, data={"path": inp.get("file_path", ""), "tool": name})
                    )
                elif name == "StructuredOutput":
                    out.append(Fact(kind="final", text="structured output", data={}))
                else:
                    out.append(Fact(kind="tool", text=name, data={"tool": name}))
            elif bt == "thinking":
                out.append(Fact(kind="thinking", text=(block.get("thinking") or "")[:120]))
            elif bt == "text":
                out.append(Fact(kind="turn", text=(block.get("text") or "")[:120]))
        return out or [Fact(kind="turn", text="assistant")]
    if t == "result":
        u = obj.get("usage", {}) or {}
        return [
            Fact(
                kind="usage",
                data={
                    "input_tokens": int(u.get("input_tokens", 0)),
                    "output_tokens": int(u.get("output_tokens", 0)),
                    "cache_read_tokens": int(u.get("cache_read_input_tokens", 0)),
                    "turns": int(obj.get("num_turns", 1)),
                    "tool_calls": 0,
                },
            ),
            Fact(
                kind="final" if obj.get("subtype") == "success" else "error",
                text=str(obj.get("subtype")),
                data={"subtype": obj.get("subtype")},
            ),
        ]
    return []


class ClaudeCliBackend:
    name = "claude_cli"

    def capabilities(self) -> Capabilities:
        return Capabilities(
            schema_mode=SchemaMode.TOOL_BOUNDARY, tools_denyable=True, streams=True, threads=True
        )

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        if not shutil.which("claude"):
            return CallResult(status="error", reason="`claude` is not on PATH")
        if call.tools:
            return CallResult(status="error", reason="the claude_cli backend runs tool-less steps only in v1")
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(call.schema_),
            "--tools",
            "",
            "--disallowedTools",
            *CLAUDE_ALL_TOOLS,
            "--max-turns",
            str(call.max_turns),
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--model",
            call.model,
            "--system-prompt",
            call.system,
        ]
        if call.effort:
            cmd += ["--effort", call.effort]
        with tempfile.TemporaryDirectory() as empty:
            run = run_jsonl(
                cmd,
                cwd=Path(empty),
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
                stdin_text=call.user,
                parse=_claude_parse,
                stream_path=call.stream_path,
                stall_seconds=call.stall_seconds,
                on_fact=on_fact,
                scope_root=call.scope_root,
            )
        usage = Usage()
        for f in run.facts:
            if f.kind == "usage":
                usage = Usage(**f.data)
        if run.stopped:
            return CallResult(
                status="stall" if run.stopped == "stall" else "scope",
                reason=f"{run.stopped} after {len(run.facts)} facts",
                usage=usage,
                facts=run.tail,
            )
        last = run.last_json or {}
        if (
            last.get("type") == "result"
            and last.get("subtype") == "success"
            and last.get("structured_output") is not None
        ):
            return CallResult(
                status="final",
                raw_text=json.dumps(last["structured_output"]),
                parsed=last["structured_output"],
                usage=usage,
                model_used=call.model,
                facts=run.tail,
            )
        reason = (
            last.get("subtype")
            or f"exit {run.returncode}: {run.stderr.strip().splitlines()[-1] if run.stderr.strip() else 'no result line'}"
        )
        return CallResult(
            status="no_output",
            reason=f"claude -p returned no structured output ({reason})",
            usage=usage,
            facts=run.tail,
        )


def _codex_parse(obj: dict[str, Any]) -> list[Fact]:
    t = obj.get("type", "")
    if t == "thread.started":
        return [Fact(kind="note", text="thread", data={"thread_id": obj.get("thread_id")})]
    if t == "item.completed" or t == "item.started":
        item = obj.get("item", {}) or {}
        it = item.get("type", "")
        if it == "reasoning":
            return [Fact(kind="thinking", text=(item.get("text") or "")[:120])]
        if it in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
            data = {"tool": it}
            if it == "file_change":
                data["path"] = (item.get("changes") or [{}])[0].get("path", "")
                return [Fact(kind="write", text=it, data=data)]
            return [Fact(kind="tool", text=it, data=data)]
        if it == "agent_message":
            return [Fact(kind="final", text=(item.get("text") or "")[:120])]
        return [Fact(kind="turn", text=it)]
    if t == "turn.completed":
        u = obj.get("usage", {}) or {}
        return [
            Fact(
                kind="usage",
                data={
                    "input_tokens": int(u.get("input_tokens", 0)),
                    "output_tokens": int(u.get("output_tokens", 0)),
                    "cache_read_tokens": int(u.get("cached_input_tokens", 0)),
                    "turns": 1,
                    "tool_calls": 0,
                },
            )
        ]
    if t == "turn.failed" or t == "error":
        return [Fact(kind="error", text=str(obj.get("error") or obj.get("message") or t)[:200])]
    return []


class CodexCliBackend:
    name = "codex_cli"

    def capabilities(self) -> Capabilities:
        return Capabilities(schema_mode=SchemaMode.GRAMMAR, tools_denyable=True, streams=True, threads=True)

    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult:
        if not shutil.which("codex"):
            return CallResult(status="error", reason="`codex` is not on PATH")
        if call.tools:
            return CallResult(status="error", reason="the codex_cli backend runs tool-less steps only in v1")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps(call.schema_))
            out_path = root / "out.json"
            empty = root / "empty"
            empty.mkdir()
            cmd = [
                "codex",
                "exec",
                "--json",
                "--output-schema",
                str(schema_path),
                "-o",
                str(out_path),
                "-m",
                call.model,
                "-s",
                "read-only",
                "-C",
                str(empty),
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "-c",
                f'model_reasoning_effort="{call.effort}"',
                "-c",
                'sandbox_mode="read-only"',
                "-",
            ]
            prompt = call.system + "\n\n---\n\n" + call.user
            run = run_jsonl(
                cmd,
                cwd=empty,
                env=dict(os.environ),
                stdin_text=prompt,
                parse=_codex_parse,
                stream_path=call.stream_path,
                stall_seconds=call.stall_seconds,
                on_fact=on_fact,
                scope_root=call.scope_root,
            )
            usage = Usage()
            for f in run.facts:
                if f.kind == "usage":
                    usage = Usage(**f.data)
            if run.stopped:
                return CallResult(
                    status="stall" if run.stopped == "stall" else "scope",
                    reason=f"{run.stopped} after {len(run.facts)} facts",
                    usage=usage,
                    facts=run.tail,
                )
            if out_path.exists() and out_path.read_text().strip():
                text = out_path.read_text()
                try:
                    return CallResult(
                        status="final",
                        raw_text=text,
                        parsed=json.loads(text),
                        usage=usage,
                        model_used=call.model,
                        facts=run.tail,
                    )
                except ValueError as e:
                    return CallResult(
                        status="no_output",
                        raw_text=text,
                        reason=f"codex's last message is not JSON: {e}",
                        usage=usage,
                        facts=run.tail,
                    )
            err = next((f.text for f in reversed(run.facts) if f.kind == "error"), None)
            return CallResult(
                status="error" if run.returncode else "no_output",
                reason=err
                or f"exit {run.returncode}: {(run.stderr.strip().splitlines() or ['no output file'])[-1][:200]}",
                usage=usage,
                facts=run.tail,
            )
