"""Streams are the signal; exit is the backstop (rule 10; RELIABILITY D7).

One reader for every subprocess backend: stdout is JSONL, each line is parsed by the backend's
`parse` into zero or more Facts, every line is copied to the stream file, and two clocks run --
the last fact's time (the model's own signal) and the process's exit. No fact for
`stall_seconds` kills the process group; a write fact outside `scope_root` kills it too.
Never parsed by position: a line that is not JSON is a `note`, never "the last line".
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .base import Fact

Parser = Callable[[dict[str, Any]], list[Fact]]


class StreamRun:
    def __init__(
        self,
        returncode: int | None,
        facts: list[Fact],
        stopped: str | None,
        stderr: str,
        last_json: dict[str, Any] | None,
    ) -> None:
        self.returncode = returncode
        self.facts = facts
        self.stopped = stopped  # None | "stall" | "scope"
        self.stderr = stderr
        self.last_json = last_json

    @property
    def tail(self) -> list[Fact]:
        return self.facts[-6:]


def run_jsonl(
    cmd: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str] | None,
    stdin_text: str | None,
    parse: Parser,
    stream_path: Path | None,
    stall_seconds: int,
    on_fact: Callable[[Fact], None],
    scope_root: Path | None = None,
    timeout: int | None = None,
) -> StreamRun:
    if stream_path:
        stream_path.parent.mkdir(parents=True, exist_ok=True)
    out_f = stream_path.open("a", encoding="utf-8") if stream_path else None
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    facts: list[Fact] = []
    last_json: dict[str, Any] | None = None
    last_fact = time.monotonic()
    lock = threading.Lock()
    stopped: str | None = None
    stderr_buf: list[str] = []

    def kill(reason: str) -> None:
        nonlocal stopped
        stopped = reason
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def feed() -> None:
        try:
            if proc.stdin is not None:
                proc.stdin.write(stdin_text or "")
                proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def read_err() -> None:
        assert proc.stderr is not None
        for ln in proc.stderr:
            stderr_buf.append(ln)

    def read_out() -> None:
        nonlocal last_fact, last_json
        assert proc.stdout is not None
        for line in proc.stdout:
            if out_f:
                out_f.write(line)
                out_f.flush()
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except ValueError:
                new = [Fact(kind="note", text=s[:200])]
            else:
                last_json = obj if isinstance(obj, dict) else last_json
                new = parse(obj) if isinstance(obj, dict) else []
            with lock:
                last_fact = time.monotonic()
            for f in new:
                facts.append(f)
                on_fact(f)
                if f.kind == "write" and scope_root is not None:
                    p = Path(f.data.get("path", ""))
                    try:
                        (scope_root / p if not p.is_absolute() else p).resolve().relative_to(
                            scope_root.resolve()
                        )
                    except ValueError:
                        kill("scope")
                        return

    threads = [
        threading.Thread(target=feed, daemon=True),
        threading.Thread(target=read_out, daemon=True),
        threading.Thread(target=read_err, daemon=True),
    ]
    for t in threads:
        t.start()
    t0 = time.monotonic()
    while proc.poll() is None:
        time.sleep(0.05)
        with lock:
            quiet = time.monotonic() - last_fact
        if quiet > stall_seconds:
            kill("stall")
            break
        if timeout and time.monotonic() - t0 > timeout:
            kill("timeout")
            break
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    for t in threads[1:]:
        t.join(timeout=2)
    if out_f:
        out_f.close()
    return StreamRun(proc.returncode, facts, stopped, "".join(stderr_buf)[-4000:], last_json)
