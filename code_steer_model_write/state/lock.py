"""One writer at a time (rule 10; ledger class "a shared record written by parallel workers").

`locked(path)` takes an advisory lock on `<path>.lock` for the duration of the block. Every
write to state.json and every append to events.jsonl goes through it.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def locked(path: Path | str) -> Iterator[None]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_name(p.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_text(path: Path | str, text: str) -> None:
    """Stage next to the target, then `os.replace` (rule 6: an effect only after acceptance;
    a crash in between leaves the old file whole)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
