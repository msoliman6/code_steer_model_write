"""JSON is the truth; a version is a file; markdown is a view (rules 4, 6, 8).

`runs/<id>/artifacts/<key>/vNNN.json` -- every version kept (an exact diff is impossible
otherwise), written atomically, never overwritten. `latest(key)` is the highest version.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import TypeVar

from ..spec.base import Artifact
from ..state.lock import atomic_write_text, locked

A = TypeVar("A", bound=Artifact)
_V = re.compile(r"^v(\d{3})\.json$")


class Store:
    def __init__(self, run_dir: Path | str) -> None:
        self.root = Path(run_dir) / "artifacts"

    def _dir(self, key: str) -> Path:
        if not re.match(r"^[a-z0-9_\-]+$", key):
            raise ValueError(f"artifact key must be [a-z0-9_-]+: {key!r}")
        return self.root / key

    def versions(self, key: str) -> list[int]:
        d = self._dir(key)
        if not d.exists():
            return []
        return sorted(int(m.group(1)) for p in d.iterdir() if (m := _V.match(p.name)))

    def latest_version(self, key: str) -> int | None:
        vs = self.versions(key)
        return vs[-1] if vs else None

    def path(self, key: str, version: int) -> Path:
        return self._dir(key) / f"v{version:03d}.json"

    def write(self, key: str, artifact: Artifact) -> int:
        """Store the next version. Called only after every check accepted the answer (rule 6)."""
        d = self._dir(key)
        with locked(d / "versions"):
            v = (self.latest_version(key) or 0) + 1
            text = artifact.model_dump_json(indent=2)
            atomic_write_text(self.path(key, v), text)
        return v

    def read(self, key: str, model: type[A], version: int | None = None) -> A:
        v = version if version is not None else self.latest_version(key)
        if v is None:
            raise FileNotFoundError(f"no version of artifact {key!r} in {self.root}")
        return model.model_validate_json(self.path(key, v).read_text(encoding="utf-8"))

    def read_raw(self, key: str, version: int | None = None) -> dict:
        v = version if version is not None else self.latest_version(key)
        if v is None:
            raise FileNotFoundError(f"no version of artifact {key!r} in {self.root}")
        return json.loads(self.path(key, v).read_text(encoding="utf-8"))

    def exists(self, key: str) -> bool:
        return self.latest_version(key) is not None

    def sha(self, key: str, version: int | None = None) -> str:
        """The freeze hash: sha256 of the canonical JSON (sorted keys, no whitespace)."""
        raw = self.read_raw(key, version)
        canon = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def diff(self, key: str, v1: int, v2: int, rendered: tuple[str, str] | None = None) -> str:
        """A unified diff computed by code (rule 8): of the two rendered views when given,
        else of the two canonical JSON texts."""
        if rendered is not None:
            a, b = rendered
        else:
            a = json.dumps(self.read_raw(key, v1), indent=2, sort_keys=True, ensure_ascii=False)
            b = json.dumps(self.read_raw(key, v2), indent=2, sort_keys=True, ensure_ascii=False)
        lines = difflib.unified_diff(
            a.splitlines(),
            b.splitlines(),
            fromfile=f"{key} v{v1:03d}",
            tofile=f"{key} v{v2:03d}",
            lineterm="",
        )
        return "\n".join(lines)
