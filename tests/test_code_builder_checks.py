import json
import subprocess

import pytest

from code_steer_model_write import worktree
from code_steer_model_write.artifacts.contract import Contract
from code_steer_model_write.artifacts.plan import Plan
from code_steer_model_write.artifacts.vspec import VerificationSpec
from code_steer_model_write.checks.nullimpl import null_module, zero_of
from code_steer_model_write.checks.ownership import ownership_problems
from code_steer_model_write.checks.pycheck import check_python
from code_steer_model_write.checks.runtests import run_all
from code_steer_model_write.spec.base import CheckContext

CONTRACT = {
    "block": "slug",
    "vocabulary": [
        {"key": "slug_term", "term": "slug", "definition": "lowercase ascii words joined by single hyphens"}
    ],
    "input": [{"key": "in_text", "name": "text", "type": "str", "tags": []}],
    "output": [{"key": "out_slug", "name": "slug", "type": "str", "tags": []}],
    "units": [
        {
            "key": "slugify",
            "name": "slugify",
            "kind": "function",
            "params": [{"name": "text", "type": "str", "default": None}],
            "returns": "str",
            "holds": "returns the slug of text as defined in the vocabulary",
        }
    ],
    "constants": [{"key": "max_len", "name": "MAX_LEN", "value": "80", "tag": "limit"}],
    "invariants": [
        {
            "key": "inv_charset",
            "claim": "every character of the result is a-z, 0-9 or '-'",
            "measurement": "",
        },
        {"key": "inv_len", "claim": "the result has at most MAX_LEN characters", "measurement": ""},
    ],
    "negative": [{"key": "neg_unicode", "must_not": "transliterate non-ascii letters"}],
    "failure": [
        {
            "key": "fail_none",
            "on": "text is None",
            "policy": "raise TypeError",
            "observable": "the exception type",
        }
    ],
    "tolerances": [],
    "algorithm": [
        {
            "unit": "slugify",
            "steps": [
                {"key": "s_lower", "text": "lowercase the text", "implements": ["inv_charset"], "uses": []},
                {
                    "key": "s_join",
                    "text": "replace runs of non-alphanumerics with one hyphen and trim to MAX_LEN",
                    "implements": ["inv_charset", "inv_len"],
                    "uses": ["max_len"],
                },
            ],
        }
    ],
}


def test_contract_ids_by_code_and_kept_by_key():
    c = Contract.model_validate(CONTRACT)
    assert c.semantic_problems(CheckContext()) == []
    v1 = c.with_ids(None)
    assert v1.version == 1 and v1.key_to_id()["slugify"] == "C-0004" and v1.key_to_id()["s_join"] == "A-0002"
    # re-emit: one clause dropped, one added -> the survivor keeps its id, the new one gets the next, the gone one retires
    d = json.loads(v1.model_dump_json())
    d["invariants"].pop(1)
    d["invariants"].append(
        {
            "key": "inv_nonempty",
            "claim": "a non-empty text with one letter gives a non-empty slug",
            "measurement": "",
        }
    )
    d["algorithm"][0]["steps"][1]["implements"] = ["inv_charset", "inv_nonempty"]
    v2 = Contract.model_validate({k: v for k, v in d.items() if k not in ("version", "retired")}).with_ids(v1)
    assert v2.version == 2 and v2.key_to_id()["slugify"] == "C-0004"
    assert v2.key_to_id()["inv_nonempty"] == "A-0003" or v2.key_to_id()["inv_nonempty"].startswith("C-")
    assert "C-0007" in v2.retired  # inv_len's id, never reused
    assert v2.key_to_id()["inv_nonempty"] not in v2.retired
    # two views, two hashes; the test-visible one has no algorithm
    assert v1.sha() != v1.test_visible().sha() and v1.test_visible().algorithm == []
    md = v1.render_md()
    assert "### 8. Algorithm" in md and "C-0004" in md
    assert "### 8. Algorithm" not in v1.render_md(drop={"algorithm"})


def test_contract_semantic_checks_catch_the_classes():
    d = json.loads(json.dumps(CONTRACT))
    d["invariants"][0]["claim"] = "Verify the output is handled gracefully"
    d["algorithm"][0]["steps"][0]["implements"] = ["nope"]
    d["units"].append(
        {
            "key": "slugify",
            "name": "x",
            "kind": "function",
            "params": [],
            "returns": "str",
            "holds": "duplicate key here",
        }
    )
    probs = {p.code for p in Contract.model_validate(d).semantic_problems(CheckContext())}
    assert {"clause_is_a_test", "banned_word", "implements_unresolved", "key_dup"} <= probs


def test_plan_one_owner_per_file():
    p = Plan(
        blocks=[
            {
                "name": "a",
                "boundary": "parses the input text",
                "inputs": ["s: str"],
                "outputs": ["t: list"],
                "writes": ["src/a.py"],
            },
            {
                "name": "b",
                "boundary": "joins the tokens again",
                "inputs": ["t: list"],
                "outputs": ["s: str"],
                "writes": ["src/a.py"],
            },
        ],
        decomposition="two blocks because parsing and joining differ",
        order=["a", "c"],
    )
    codes = [x.code for x in p.semantic_problems(CheckContext())]
    assert "file_two_owners" in codes and "order_unknown_block" in codes


def test_vspec_ids_and_input_quantifier():
    v = VerificationSpec(
        properties=[
            {
                "cites": ["C-0006"],
                "over": "output",
                "family": "ascii words",
                "observe": "the characters of the result",
                "falsifies": "a char outside [a-z0-9-]",
            }
        ]
    )
    probs = {p.code for p in v.semantic_problems(CheckContext(known_ids={"C-0006"}))}
    assert probs == {"all_over_output"}
    v2 = v.with_ids([])
    assert v2.properties[0].id == "P-0001"


def test_null_module_zero_values():
    assert (
        zero_of("str") == '""'
        and zero_of("list[str]") == "[]"
        and zero_of("int | None") == "0"
        and zero_of("Optional[int]") == "None"
        and zero_of("Foo") == "None"
    )
    c = Contract.model_validate(CONTRACT).with_ids(None)
    src = null_module(c)
    ns: dict = {}
    exec(compile(src, "null.py", "exec"), ns)
    assert ns["slugify"]("Hello World") == ""


@pytest.mark.parametrize("real_ok", [True, False])
def test_run_all_real_and_null(tmp_path, real_ok):
    src = tmp_path / "src"
    src.mkdir()
    null = tmp_path / "null"
    null.mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    body = "return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')" if real_ok else "return 'wrong'"
    (src / "slug.py").write_text(f"import re\n\ndef slugify(text: str) -> str:\n    {body}\n")
    (null / "slug.py").write_text(null_module(Contract.model_validate(CONTRACT)))
    (tests / "test_slug.py").write_text(
        "from slug import slugify\n\n"
        "def test_P_0001_charset():\n    assert set(slugify('Hello, World!')) <= set('abcdefghijklmnopqrstuvwxyz0123456789-')\n\n"
        "def test_P_0002_input_survives():\n    assert slugify('Hello World') == 'hello-world'\n\n"
        "def test_P_0003_vacuous():\n    assert all(ch != ' ' for ch in slugify('a b'))\n"
    )
    manifest = {
        "P-0001": "tests/test_slug.py::test_P_0001_charset",
        "P-0002": "tests/test_slug.py::test_P_0002_input_survives",
        "P-0003": "tests/test_slug.py::test_P_0003_vacuous",
        "P-0004": "tests/test_slug.py::test_missing",
    }
    res = run_all(tests, src, null, manifest, tmp_path / "out", repeats=2)
    by = {p.property: p for p in res.properties}
    assert by["P-0002"].real == ("pass" if real_ok else "fail") and by["P-0002"].null == "fail"
    assert by["P-0001"].null == "pass" and by["P-0003"].null == "pass"  # vacuous: pass against the null
    assert by["P-0004"].real == "missing"
    assert [p.property for p in res.vacuous] == ["P-0001", "P-0003"]
    if not real_ok:
        assert "wrong" in by["P-0002"].assertion or "assert" in by["P-0002"].assertion


def test_ownership_and_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / "tests" / "t.py").write_text("y = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "files"],
        check=True,
    )
    wt = worktree.add(repo, tmp_path / "wt" / "tests", branch="csmw/tests")
    assert worktree.strip(wt, ["src"]) == ["src"] and not (wt / "src").exists() and (wt / "tests").exists()
    (wt / "tests" / "test_new.py").write_text("z = 1\n")
    (wt / "stray.txt").write_text("!")
    probs = ownership_problems(wt, ["tests/test_new.py"])
    assert (
        len(probs) == 2
        and any("stray.txt" in p.message for p in probs)
        and any("src/a.py" in p.message for p in probs)
    )
    worktree.remove(repo, wt)
    assert not wt.exists()


def test_pycheck_compile_and_skips(tmp_path, monkeypatch):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n")
    r = check_python([bad], types=False)
    assert r.problems and r.problems[0].code == "compile"
    good = tmp_path / "good.py"
    good.write_text("import os\n\ndef f():\n    return 1\n")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no ruff, no pyright on this PATH
    r2 = check_python([good])
    assert r2.ok and set(r2.skipped) == {"ruff format", "ruff check", "pyright"}
