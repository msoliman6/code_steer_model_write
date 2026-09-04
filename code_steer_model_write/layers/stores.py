"""L7 -- resources, knowledge, state (ARCHITECTURE.md 7.7): three stores with distinct
interfaces. State is run-scoped (the step records and the event log); Artifacts are versioned
and cited by id; Memory is cross-run and present only when a step declares it.

First implementations are what exists: `RunState` + `EventLog` are the StateStore, the
versioned `Store` is the ArtifactStore (obstore sits behind it in phase 1's follow-up once
the interface is proven), and `NoMemory` refuses, because the correctness profile declares
none (P14). The interfaces are the seam; the classes below only name what already holds."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Protocol, TypeVar, runtime_checkable

from ..spec.base import Artifact
from ..spec.events import Event, EventKind

A = TypeVar("A", bound=Artifact)


@runtime_checkable
class StateStore(Protocol):
    """Run-scoped: the record. One writer at a time, atomic replace, append-only events."""

    def append(self, kind: EventKind, /, **data: Any) -> Event: ...
    def subscribe(self, fn) -> None: ...
    def read(self, *, offset: int = 0) -> Iterator[Event]: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Versioned and immutable once written; every version kept; a write is the next version."""

    def write(self, key: str, artifact: Artifact) -> int: ...
    def read(self, key: str, model: type[A], version: int | None = None) -> A: ...
    def versions(self, key: str) -> list[int]: ...
    def path(self, key: str, version: int) -> Path: ...


class MemoryStore(Protocol):
    """Cross-run, searchable, reached only through L6 (section 2). Dormant until P14 says so."""

    def write(self, run_id: str, text: str, meta: dict[str, Any]) -> str: ...
    def query(
        self, text: str, *, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


class NoMemory:
    """The correctness profile declares no memory; a step that reaches for it is a recipe bug."""

    def write(self, run_id: str, text: str, meta: dict[str, Any]) -> str:
        raise RuntimeError("this profile declares no memory (P14); the recipe may not write to it")

    def query(
        self, text: str, *, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        raise RuntimeError("this profile declares no memory (P14); the recipe may not read from it")
