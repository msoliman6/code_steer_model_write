"""events.jsonl -- the one owner of what happened (rule 10).

Append under the lock with a monotonic `seq`; read back strictly (one JSON object per line,
never parsed by position -- ledger class "a message parsed by position").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterator

from .spec.events import Event, EventKind
from .state.lock import locked

Listener = Callable[[Event], None]


class EventLog:
    def __init__(self, path: Path | str, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._listeners: list[Listener] = []

    def subscribe(self, fn: Listener) -> None:
        """A mirror (MLflow, a live page) reads every event after it is on disk; the log never
        depends on a mirror succeeding."""
        self._listeners.append(fn)

    def append(
        self,
        kind: EventKind,
        /,
        *,
        step: str | None = None,
        role: str | None = None,
        attempt: int | None = None,
        **data: Any,
    ) -> Event:
        """`kind` is positional-only so a data key named `kind` can never collide with it
        (ledger class: a name shadowed; found twice on 2026-09-03)."""
        with locked(self.path):
            seq = self._last_seq() + 1
            ev = Event(
                seq=seq, run_id=self.run_id, kind=kind, step=step, role=role, attempt=attempt, data=data
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(ev.model_dump_json() + "\n")
        for fn in self._listeners:
            try:
                fn(ev)
            except Exception as e:  # noqa: BLE001 -- a mirror failing must not stop the run
                print(f"[events] listener {fn!r} failed: {e}")
        return ev

    def _last_seq(self) -> int:
        if not self.path.exists():
            return 0
        last = 0
        with self.path.open("rb") as f:
            try:
                f.seek(-4096, 2)
            except OSError:
                f.seek(0)
            tail = f.read().decode("utf-8", errors="replace").strip().splitlines()
        for line in reversed(tail):
            line = line.strip()
            if line:
                last = json.loads(line)["seq"]
                break
        return last

    def read(self, *, offset: int = 0) -> Iterator[Event]:
        """Every event from byte `offset`. Strict: a line that is not one JSON object halts."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield Event.model_validate_json(line)

    def all(self) -> list[Event]:
        return list(self.read())

    def size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def last(self, kind: EventKind | None = None) -> Event | None:
        out = None
        for ev in self.read():
            if kind is None or ev.kind == kind:
                out = ev
        return out
