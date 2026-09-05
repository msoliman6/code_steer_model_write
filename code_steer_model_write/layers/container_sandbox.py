"""L5's second tier (ARCHITECTURE.md 7.6, phase 8): a container per execution through the
Docker SDK. Network off unless the execution says otherwise, the execution's root the only
mount (at the same absolute path, so every path in a command stays valid), CPU, memory and
wall-clock limits, the host user's uid so what the command writes is the user's, and gVisor
(`runsc`) as the runtime when the engine offers it. The engine is Colima on macOS or Docker on
Linux; either answers the same socket, and the tier says which in words.

The image is the runtime's own (`data/sandbox.Dockerfile`: python, pytest, ruff, pyright and
git), built once by `csmw sandbox build`. Nothing enters this tier except through L6."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .sandbox import Execution, ExecutionResult, _snapshot

if TYPE_CHECKING:
    from ..events import EventLog

IMAGE = "csmw-sandbox:1"
DOCKERFILE = Path(__file__).resolve().parent.parent / "data" / "sandbox.Dockerfile"


def _client() -> Any:
    import docker  # the SDK; the engine is a packaged process started with one command (7.1)

    return docker.from_env()


def available(*, image: str = IMAGE) -> tuple[bool, str]:
    """Is an engine answering, and is the image there? Said in words, never assumed."""
    try:
        c = _client()
        c.ping()
        info = c.info()
        runtimes = sorted((info.get("Runtimes") or {}).keys())
        name = info.get("Name", "")
        try:
            c.images.get(image)
        except Exception:  # noqa: BLE001 -- the SDK's ImageNotFound and friends
            return False, f"engine {name} up, image {image} missing: run `csmw sandbox build`"
        gv = "gvisor" if "runsc" in runtimes else "no gvisor"
        return True, f"engine {name} · image {image} · {gv}"
    except Exception as e:  # noqa: BLE001 -- no engine is a fact, not a crash
        return False, f"no engine: {type(e).__name__}: {str(e)[:120]}"


def build(*, image: str = IMAGE, quiet: bool = False) -> str:
    """Build the sandbox image from the runtime's Dockerfile. Returns the image id."""
    c = _client()
    img, logs = c.images.build(path=str(DOCKERFILE.parent), dockerfile=DOCKERFILE.name, tag=image, rm=True)
    if not quiet:
        for line in logs:
            text = str((line or {}).get("stream", "")) if isinstance(line, dict) else ""
            if text.strip():
                print(text.rstrip())
    return str(img.id)


class ContainerSandbox:
    tier = "container"

    def __init__(
        self,
        events: EventLog | None = None,
        *,
        mount_root: Path | None = None,
        image: str = IMAGE,
        gvisor: bool | None = None,
        default_cpus: float = 2.0,
        default_memory: str = "1g",
    ) -> None:
        self.events = events
        self.mount_root = Path(mount_root).resolve() if mount_root else None  # the run folder
        self.image = image
        self.default_cpus = default_cpus
        self.default_memory = default_memory
        self._c = _client()
        runtimes = (self._c.info().get("Runtimes") or {}).keys()
        self.runtime = "runsc" if (gvisor is not False and "runsc" in runtimes) else None
        if gvisor and self.runtime is None:
            raise RuntimeError("gVisor asked for, but the engine has no `runsc` runtime")

    def run(self, ex: Execution) -> ExecutionResult:
        cwd = ex.cwd or ex.root
        root = Path(ex.root).resolve()
        before = _snapshot(root)
        env = dict(ex.env) if ex.env is not None else {}
        # the container's own tools on PATH; the host's PATH is meaningless inside
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env.setdefault("HOME", "/tmp")
        env.setdefault("LANG", "C.UTF-8")
        # git under the host's uid on a mounted tree: every directory is the user's own
        env.setdefault("GIT_CONFIG_COUNT", "1")
        env.setdefault("GIT_CONFIG_KEY_0", "safe.directory")
        env.setdefault("GIT_CONFIG_VALUE_0", "*")
        # the run folder is the mount (a junit file, a src dir and a tests dir all live under it);
        # a root outside it is mounted beside, at its own path. Nothing else of the host is visible.
        mounts = (
            {str(self.mount_root): {"bind": str(self.mount_root), "mode": "rw"}} if self.mount_root else {}
        )
        if not self.mount_root or not root.is_relative_to(self.mount_root):
            mounts[str(root)] = {"bind": str(root), "mode": "rw"}
        cmd = list(ex.command)
        if cmd and cmd[0] == sys.executable:  # the host's interpreter means "python" inside
            cmd[0] = "python"
        kw: dict[str, Any] = dict(
            command=cmd,  # argv, never a shell string
            working_dir=str(cwd),
            volumes=mounts,
            network_disabled=not ex.network,
            environment=env,
            user=f"{os.getuid()}:{os.getgid()}",
            mem_limit=ex.memory_bytes or self.default_memory,
            nano_cpus=int(self.default_cpus * 1e9),
            detach=True,
            stdin_open=False,
            tty=False,
        )
        if ex.cpu_seconds is not None:  # the same CPU-time ceiling the subprocess tier sets
            from docker.types import Ulimit

            kw["ulimits"] = [Ulimit(name="cpu", soft=ex.cpu_seconds, hard=ex.cpu_seconds)]
        if self.runtime:
            kw["runtime"] = self.runtime
        t0 = time.time()
        timed_out = False
        container = self._c.containers.run(self.image, **kw)
        try:
            try:
                res = container.wait(timeout=ex.timeout)
                code = int(res.get("StatusCode", 1))
            except Exception:  # noqa: BLE001 -- the SDK raises a ReadTimeout / ConnectionError past the deadline
                timed_out = True
                code = 124
                try:
                    container.kill()
                except Exception:  # noqa: BLE001
                    pass
            out = container.logs(stdout=True, stderr=False).decode(errors="replace")
            err = container.logs(stdout=False, stderr=True).decode(errors="replace")
        finally:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
        seconds = round(time.time() - t0, 3)
        after = _snapshot(root)
        touched = sorted(k for k in after if before.get(k) != after[k]) + sorted(
            k for k in before if k not in after
        )
        r = ExecutionResult(
            exit_code=code,
            stdout=out,
            stderr=err,
            seconds=seconds,
            touched=touched,
            timed_out=timed_out,
            tier=self.tier,
        )
        if self.events is not None:
            self.events.append(
                "sandbox.run",
                step=ex.step,
                tool=ex.tool,
                tier=self.tier,
                command=ex.command[:3],
                exit_code=code,
                seconds=seconds,
                touched=len(touched),
                timed_out=timed_out,
                network=ex.network,
                runtime=self.runtime or "runc",
            )
        return r
