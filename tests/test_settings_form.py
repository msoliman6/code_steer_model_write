from code_steer_model_write import settings_form as sf
from code_steer_model_write.artifacts.store import Store
from code_steer_model_write.config import Mode
from code_steer_model_write.recipes.code_builder.recipe import CodeBuilder
from code_steer_model_write.state.run import RunPaths, RunState


def test_fields_are_one_owner_and_render_as_cards():
    keys = [f.key for f in sf.FIELDS]
    assert len(keys) == len(set(keys))
    for f in sf.FIELDS:
        if f.kind == "chips":
            assert f.default in f.options, f.key
            assert f.description
    cards = sf.form_model({})
    assert [c["key"] for c in cards] == keys and all(c["value"] == sf.BY_KEY[c["key"]].default for c in cards)
    assert [c["key"] for c in cards if c["group"] == "stage:contracts"] == [
        "contracts_author_model",
        "contracts_author_effort",
        "contracts_checker_model",
        "contracts_checker_effort",
    ]
    assert [c["func"] for c in cards if c["group"] == "stage:verification"] == [
        "Attacks the properties",
        "Attacks the properties",
        "Writes the properties",
        "Writes the properties",
    ]
    by = {c["key"]: c for c in cards}
    assert by["checker_model"]["discovery"] in ("dynamic", "configured") and by["checker_effort"]["options"][
        0
    ] in ("low", "xhigh")


def test_inherit_and_defaults_resolve(monkeypatch):
    monkeypatch.setenv("CSMW_MODEL_A", "claude-sonnet-5")
    monkeypatch.setenv("CSMW_MODEL_B", "gpt-5.4-mini")
    v = sf.resolve(
        {
            "author_model": "claude-opus-5",
            "contracts_author_model": "as author",
            "verify_checker_model": "as checker",
            "checker_model": "default",
        }
    )
    assert (
        v["contracts_author_model"] == "claude-opus-5"
        and v["verify_checker_model"] == "gpt-5.4-mini"
        and v["verify_author_effort"] == v["author_effort"]
    )
    w = sf.resolve({"author_model": "claude-haiku-4-5", "author_effort": "max"})
    assert w["author_effort"] == "low"  # an effort the model lacks falls back to its default


def test_build_task_and_stage_roles(tmp_path):
    values = {
        "run_name": "t",
        "request": "build a slug library that is small",
        "must_be_true": "a\nb",
        "mode": "auto",
        "rounds": "2",
        "author_backend": "fake",
        "checker_backend": "fake",
        "author_model": "claude-sonnet-5",
        "build_author_model": "claude-haiku-4-5",
        "build_author_effort": "low",
        "contracts_author_effort": "high",
    }
    assert sf.missing_required({}) == ["run name", "request"] and sf.missing_required(values) == []
    t = sf.build_task(values)
    assert t.mode is Mode.AUTO and t.rounds == 2 and t.inputs["brief"]["must_be_true"] == ["a", "b"]
    assert (
        sf.stage_role(t, "build", "author").model == "claude-haiku-4-5"
        and sf.stage_role(t, "contracts", "author").effort == "high"
    )
    assert (
        sf.stage_role(t, "plan", "author").model == "claude-sonnet-5"
        and sf.stage_role(t, "verify", "checker").model == t.roles["checker"].model
    )
    paths = RunPaths(run_dir=tmp_path / "run")
    st = RunState.create(paths, t)
    steps = CodeBuilder().steps(st, paths, Store(paths.run_dir))
    ledger = next((s for s in steps if s.key == "p0-ledger"), None)
    assert ledger is None or ledger.model == "claude-sonnet-5"
    sf.save_prefs(tmp_path / "runs", values)
    assert sf.load_prefs(tmp_path / "runs")[
        "build_author_model"
    ] == "claude-haiku-4-5" and "request" not in sf.load_prefs(tmp_path / "runs")
