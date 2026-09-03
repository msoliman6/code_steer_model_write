"""Run the tests by code: the real run (n repeats, nondeterminism visible) and the null run
(every test must FAIL), property by property through the manifest -- a lookup, never a
substring match (rule 7)."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ..artifacts.results import PropertyResult, Results


def _pytest(tests_dir: Path, src_dir: Path, junit: Path, *, timeout: int = 300) -> dict[str, tuple[str, str]]:
    """node id -> (status, message). Runs pytest with `src_dir` first on the path."""
    env = {"PYTHONPATH": str(src_dir), "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit}",
        str(tests_dir),
    ]
    subprocess.run(cmd, cwd=tests_dir.parent, capture_output=True, text=True, env=env, timeout=timeout)
    out: dict[str, tuple[str, str]] = {}
    if not junit.exists():
        return out
    root = ET.parse(junit).getroot()
    for tc in root.iter("testcase"):
        cls = tc.get("classname", "")
        name = tc.get("name", "")
        file_part = cls.replace(".", "/") + ".py" if cls else ""
        nid = f"{file_part}::{name}" if file_part else name
        status, msg = "pass", ""
        for tag, st in (("failure", "fail"), ("error", "error"), ("skipped", "error")):
            el = tc.find(tag)
            if el is not None:
                status = st
                msg = (
                    (el.get("message") or (el.text or "")).strip().splitlines()[0][:300]
                    if (el.get("message") or el.text)
                    else ""
                )
                break
        out[nid] = (status, msg)
    return out


def _norm(node: str, tests_dir: Path) -> str:
    """Normalise a manifest node id to the junit form (tests/test_x.py::test_y -> test_x.py::test_y
    relative to the tests dir's parent)."""
    path, _, name = node.partition("::")
    p = Path(path)
    try:
        p = p.relative_to(tests_dir.parent)
    except ValueError:
        pass
    return f"{p.as_posix()}::{name}"


def run_all(
    tests_dir: Path,
    src_dir: Path,
    null_dir: Path,
    manifest: dict[str, str],
    out_dir: Path,
    *,
    repeats: int = 3,
) -> Results:
    out_dir.mkdir(parents=True, exist_ok=True)
    real_runs = [_pytest(tests_dir, src_dir, out_dir / f"real-{i + 1}.xml") for i in range(repeats)]
    null_run = _pytest(tests_dir, null_dir, out_dir / "null.xml")

    def lookup(run: dict[str, tuple[str, str]], node: str) -> tuple[str, str]:
        n = _norm(node, tests_dir)
        for k, v in run.items():
            if k == n or k.endswith("/" + n) or n.endswith("/" + k):
                return v
        return ("missing", "")

    props: list[PropertyResult] = []
    for pid, node in sorted(manifest.items()):
        rs = [lookup(r, node) for r in real_runs]
        statuses = [s for s, _ in rs]
        passes = statuses.count("pass")
        if all(s == "missing" for s in statuses):
            real = "missing"
        elif passes == repeats:
            real = "pass"
        elif passes == 0:
            real = "fail" if "fail" in statuses else "error"
        else:
            real = "nondeterministic"
        nstat, _ = lookup(null_run, node)
        msg = next((m for s, m in rs if s != "pass" and m), "")
        props.append(
            PropertyResult(
                property=pid, test=node, real=real, null=nstat, runs=repeats, passes=passes, assertion=msg
            )
        )
    return Results(properties=props)
