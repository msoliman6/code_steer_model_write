"""Run the tests by code: the real run (n repeats, nondeterminism visible) and the null run
(every test must FAIL), property by property through the manifest -- a lookup, never a
substring match (rule 7)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..artifacts.results import PropertyResult, Results


def canonical_id(classname: str, name: str, root: Path | None = None) -> str:
    """One canonical node id (section 4, L7: a path enters the record in one form). The
    JUnit classname is a dotted module path pytest built from *its* rootdir; the manifest's id
    is `tests/test_x.py::test_y` from the build folder. Both reduce to the same form here: the
    file relative to the build folder, and the test's bare name with any `[parametrization]`
    stripped (ledger, live-5: a node id in two conventions -- the manifest never carries the
    parameter, the JUnit always does)."""
    file_part = classname.replace(".", "/") + ".py" if classname else ""
    if file_part:
        # pytest's rootdir may sit above the build folder; keep the path from `tests/` down
        idx = file_part.find("tests/")
        if idx > 0:
            file_part = file_part[idx:]
    bare = name.split("[", 1)[0]
    return f"{file_part}::{bare}" if file_part else bare


def _pytest(tests_dir: Path, src_dir: Path, junit: Path, *, timeout: int = 300) -> dict[str, tuple[str, str]]:
    """canonical node id -> (status, message), aggregated over a test's parameter cases:
    pass only if every case passed; fail if any failed; error otherwise. Runs pytest with
    `src_dir` first on the path, through the registry and the sandbox."""
    from ..layers import current

    junit = junit.resolve()  # one canonical form, the same the tool writes (section 4, L7)
    # L6 -> L5: the registered pytest tool runs in the sandbox with an explicit environment
    current().tools.invoke(
        "pytest", {"tests_dir": tests_dir, "src_dir": src_dir, "junit": junit, "timeout": timeout}
    )
    cases: dict[str, list[tuple[str, str]]] = {}
    if not junit.exists():
        return {}
    root = ET.parse(junit).getroot()
    for tc in root.iter("testcase"):
        nid = canonical_id(tc.get("classname", ""), tc.get("name", ""), tests_dir.parent)
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
        cases.setdefault(nid, []).append((status, msg))
    out: dict[str, tuple[str, str]] = {}
    for nid, results in cases.items():
        statuses = [s for s, _ in results]
        if all(s == "pass" for s in statuses):
            out[nid] = ("pass", "")
        elif "fail" in statuses:
            out[nid] = ("fail", next(m for s, m in results if s == "fail"))
        else:
            out[nid] = ("error", next((m for s, m in results if s == "error"), ""))
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
    return f"{p.as_posix()}::{name.split('[', 1)[0]}"


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
