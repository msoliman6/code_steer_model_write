"""Backends: streams (watchdog, scope, strict parse), the CLI backends against fake executables,
the API backends against fake clients. No network, no tokens."""

import json
import os
import stat
import sys
import types
from pathlib import Path

from code_steer_model_write.backends.anthropic_api import AnthropicBackend
from code_steer_model_write.backends.base import CallSpec, Fact
from code_steer_model_write.backends.cli import ClaudeCliBackend, CodexCliBackend
from code_steer_model_write.backends.litellm_backend import LiteLLMBackend
from code_steer_model_write.backends.streams import run_jsonl

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
    "title": "Ok",
}


def _call(**kw) -> CallSpec:
    base = dict(
        role="r",
        model="m",
        effort="low",
        system="sys",
        user="usr",
        schema=SCHEMA,
        schema_name="Ok",
        stall_seconds=2,
    )
    base.update(kw)
    return CallSpec(**base)


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_streams_parse_facts_and_notes_and_stderr(tmp_path):
    script = tmp_path / "emit.py"
    script.write_text(
        'import sys\nprint(\'{"type":"x","n":1}\')\nprint("not json")\nprint(\'{"type":"x","n":2}\')\nsys.stderr.write("warn\\n")\n'
    )
    facts = []
    run = run_jsonl(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=None,
        stdin_text=None,
        parse=lambda o: [Fact(kind="turn", text=str(o["n"]))],
        stream_path=tmp_path / "s.jsonl",
        stall_seconds=5,
        on_fact=facts.append,
    )
    assert (
        run.returncode == 0 and [f.text for f in facts] == ["1", "not json", "2"] and facts[1].kind == "note"
    )
    assert run.last_json == {"type": "x", "n": 2} and "warn" in run.stderr
    assert (tmp_path / "s.jsonl").read_text().count("\n") == 3


def test_streams_stall_watchdog_kills(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text('import time\nprint(\'{"a":1}\', flush=True)\ntime.sleep(30)\n')
    run = run_jsonl(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=None,
        stdin_text=None,
        parse=lambda o: [Fact(kind="turn")],
        stream_path=None,
        stall_seconds=1,
        on_fact=lambda f: None,
    )
    assert run.stopped == "stall" and run.returncode != 0


def test_streams_scope_kill(tmp_path):
    script = tmp_path / "w.py"
    script.write_text('import time\nprint(\'{"path":"/etc/passwd"}\', flush=True)\ntime.sleep(30)\n')
    run = run_jsonl(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=None,
        stdin_text=None,
        parse=lambda o: [Fact(kind="write", data={"path": o["path"]})],
        stream_path=None,
        stall_seconds=5,
        on_fact=lambda f: None,
        scope_root=tmp_path,
    )
    assert run.stopped == "scope"


def test_claude_cli_backend_against_a_fake_claude(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    init = json.dumps(
        {"type": "system", "subtype": "init", "tools": ["StructuredOutput"], "mcp_servers": [], "model": "m"}
    )
    asst = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "StructuredOutput", "input": {"ok": True}}]},
        }
    )
    result = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "structured_output": {"ok": True},
            "num_turns": 1,
            "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 0},
        }
    )
    _exe(bin_dir / "claude", f"cat > /dev/null\necho '{init}'\necho '{asst}'\necho '{result}'\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    facts = []
    r = ClaudeCliBackend().complete(_call(stream_path=tmp_path / "c.jsonl"), facts.append)
    assert r.status == "final" and r.parsed == {"ok": True} and r.usage.input_tokens == 12
    assert [f.kind for f in facts] == ["note", "final", "usage", "final"]
    # a run with no structured output is no_output with the subtype as the reason
    _exe(
        bin_dir / "claude",
        "cat > /dev/null\necho '"
        + json.dumps({"type": "result", "subtype": "error_max_structured_output_retries", "usage": {}})
        + "'\n",
    )
    r2 = ClaudeCliBackend().complete(_call(), lambda f: None)
    assert r2.status == "no_output" and "error_max_structured_output_retries" in r2.reason


def test_codex_cli_backend_against_a_fake_codex(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ev1 = json.dumps({"type": "thread.started", "thread_id": "t1"})
    ev2 = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "{\"ok\": true}"}})
    ev3 = json.dumps(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 40, "cached_input_tokens": 10, "output_tokens": 5},
        }
    )
    # the fake finds -o <file> in its args and writes the answer there
    _exe(
        bin_dir / "codex",
        'cat > /dev/null\nwhile [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then OUT="$2"; fi; shift; done\n'
        f"echo '{ev1}'\necho '{ev2}'\necho '{ev3}'\n" + 'echo \'{"ok": true}\' > "$OUT"\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    facts = []
    r = CodexCliBackend().complete(_call(), facts.append)
    assert r.status == "final" and r.parsed == {"ok": True} and r.usage.cache_read_tokens == 10
    assert [f.kind for f in facts] == ["note", "final", "usage"]


def test_anthropic_backend_with_a_fake_client():
    class Block:
        def __init__(self, t, text=None):
            self.type = t
            self.text = text

    class Msg:
        stop_reason = "end_turn"
        model = "claude-x"
        content = [Block("text", '{"ok": true}')]
        usage = types.SimpleNamespace(input_tokens=5, output_tokens=2, cache_read_input_tokens=1)

    class Stream:
        def __init__(self, **kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            yield types.SimpleNamespace(
                type="content_block_start", content_block=types.SimpleNamespace(type="text")
            )

        def get_final_message(self):
            return Msg()

    captured = {}

    class Client:
        class messages:
            @staticmethod
            def stream(**kw):
                captured.update(kw)
                return Stream(**kw)

    facts = []
    r = AnthropicBackend(client=Client()).complete(_call(thinking=True), facts.append)
    assert r.status == "final" and r.parsed == {"ok": True} and r.usage.cache_read_tokens == 1
    assert captured["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA} and captured[
        "thinking"
    ] == {"type": "adaptive"}
    assert "tools" not in captured and captured["system"] == "sys"
    Msg.stop_reason = "refusal"
    Msg.stop_details = types.SimpleNamespace(category="cyber", explanation="no")
    r2 = AnthropicBackend(client=Client()).complete(_call(), lambda f: None)
    assert r2.status == "no_output" and "refusal: cyber" in r2.reason


def test_litellm_backend_with_a_fake_completion():
    def completion(**kw):
        assert (
            kw["response_format"]["json_schema"]["strict"] is True and kw["messages"][0]["role"] == "system"
        )
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(message=types.SimpleNamespace(content='```json\n{"ok": true}\n```'))
            ],
            usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            model="gpt-x",
        )

    r = LiteLLMBackend(completion=completion).complete(_call(), lambda f: None)
    assert (
        r.status == "final"
        and r.parsed == {"ok": True}
        and r.usage.input_tokens == 7
        and r.model_used == "gpt-x"
    )

    def bad(**kw):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="not json"))],
            usage=None,
            model="m",
        )

    assert LiteLLMBackend(completion=bad).complete(_call(), lambda f: None).status == "no_output"


def test_every_backend_refuses_tools_in_v1():
    from code_steer_model_write.backends.base import ToolDef

    t = ToolDef(name="x", description="d", input_schema={}, fn=lambda: None)
    for b in (AnthropicBackend(client=object()), LiteLLMBackend(completion=lambda **k: None)):
        r = b.complete(_call(tools=[t]), lambda f: None)
        assert r.status == "error" and "tool-less" in r.reason


def test_claude_cli_is_error_beats_subtype_success(tmp_path, monkeypatch):
    """A result line with is_error is an error whatever its subtype says (ledger: an exit code that lies)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    line = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Failed to authenticate",
            "usage": {},
        }
    )
    _exe(bin_dir / "claude", f"cat > /dev/null\necho '{line}'\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    r = ClaudeCliBackend().complete(_call(), lambda f: None)
    assert r.status == "error" and "authenticate" in r.reason


def test_wire_schema_ref_stands_alone(finding_models):
    """codex/OpenAI strict mode rejects a description beside a $ref."""
    from code_steer_model_write.spec.findings import Findings as RealFindings

    s = RealFindings.wire_schema()
    for node in s["$defs"]["Finding"]["properties"].values():
        if "$ref" in node:
            assert list(node) == ["$ref"], node
    assert "allOf" not in json.dumps(s)
