from code_steer_model_write import settings_form as sf
from code_steer_model_write.config import Mode
from code_steer_model_write.recipes.code_builder.recipe import CodeBuilder
from code_steer_model_write.state.run import RunPaths, RunState
from code_steer_model_write.artifacts.store import Store


def test_fields_are_one_owner_and_render_as_cards():
    keys = [f.key for f in sf.FIELDS]
    assert len(keys) == len(set(keys))
    for f in sf.FIELDS:
        if f.kind == "chips":
            assert f.default in f.options, f.key
            assert f.description
    cards = sf.form_model({})
    assert [c["key"] for c in cards] == keys and all(c["value"] == sf.BY_KEY[c["key"]].default for c in cards)


def test_inherit_and_defaults_resolve(monkeypatch):
    monkeypatch.setenv("CSMW_MODEL_A", "claude-sonnet-5")
    monkeypatch.setenv("CSMW_MODEL_B", "gpt-5.4-mini")
    v = sf.resolve(
        {
            "plan_model": "claude-opus-5",
            "contracts_model": "as plan",
            "verify_checker_model": "as checker",
            "checker_model": "default",
        }
    )
    assert (
        v["contracts_model"] == "claude-opus-5"
        and v["verify_checker_model"] == "gpt-5.4-mini"
        and v["verify_author_effort"] == v["plan_effort"]
    )


def test_build_task_and_stage_roles(tmp_path):
    values = {
        "run_name": "t",
        "request": "build a slug library that is small",
        "must_be_true": "a\nb",
        "mode": "auto",
        "rounds": "2",
        "author_backend": "fake",
        "checker_backend": "fake",
        "plan_model": "claude-sonnet-5",
        "build_model": "claude-haiku-4-5",
        "build_effort": "low",
        "contracts_effort": "high",
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
    # the recipe stamps the override on the stage's author steps
    paths = RunPaths(run_dir=tmp_path / "run")
    st = RunState.create(paths, t)
    steps = CodeBuilder().steps(st, paths, Store(paths.run_dir))
    ledger = (
        next(s for s in steps if s.key == "p0-ledger") if any(s.key == "p0-ledger" for s in steps) else None
    )
    assert ledger is None or ledger.model == "claude-sonnet-5"
    sf.save_prefs(tmp_path / "runs", values)
    assert sf.load_prefs(tmp_path / "runs")[
        "build_model"
    ] == "claude-haiku-4-5" and "request" not in sf.load_prefs(tmp_path / "runs")
