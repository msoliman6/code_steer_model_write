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
    cards = sf.form_model({})  # the default recipe's fields, in order
    shown = [f.key for f in sf.fields_for(sf.default_recipe())]
    assert [c["key"] for c in cards] == shown and all(
        c["value"] == sf.BY_KEY[c["key"]].default for c in cards
    )
    assert [c["key"] for c in cards if c["group"] == "stage:contracts"] == [
        "contracts_author_model",
        "contracts_author_effort",
        "contracts_author_thinking",
        "contracts_checker_model",
        "contracts_checker_effort",
        "contracts_checker_thinking",
    ]
    assert [c["func"] for c in cards if c["group"] == "stage:verification"] == [
        "Attacks properties",
        "Attacks properties",
        "Attacks properties",
        "Writes properties",
        "Writes properties",
        "Writes properties",
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
    assert sf.missing_required({}) == ["name", "request"] and sf.missing_required(values) == []
    t = sf.build_task(values)
    assert (
        t.task_id == "t"
        and t.inputs["brief"]["module"] == "t"
        and sf.module_of("My Slug-Lib") == "my_slug_lib"
    )
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


def test_fields_follow_the_recipe():
    from code_steer_model_write import settings_form as sf

    debate = {f.key for f in sf.fields_for("debate")}
    coder = {f.key for f in sf.fields_for("code_builder")}
    assert "recipe" in debate and "recipe" in coder
    assert "build_author_model" in coder and "build_author_model" not in debate
    assert any(k.startswith("hypotheses_") for k in debate)
    rows = sf.form_model({"recipe": "debate"})
    assert not any(r["key"].startswith("build_") for r in rows)
    task = sf.build_task({**sf.defaults(), "recipe": "debate", "run_name": "x", "request": "why"})
    assert task.recipe == "debate"
