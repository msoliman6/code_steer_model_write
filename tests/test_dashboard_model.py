"""The view model and the self-check, on walk runs: a completed run, a halted run, a run waiting
at a gate. No browser."""

import json

from code_steer_model_write import walk
from code_steer_model_write.config import Mode
from code_steer_model_write.state.run import Outcome
from dashboard.model import build_view
from dashboard.selfcheck import check


def test_completed_run_view_and_selfcheck(tmp_path):
    with walk.env(FAKE_MODELS="1"):
        paths, recipe, task = walk.start("code_builder", tmp_path / "run")
        assert walk.make_runner(paths, recipe, task).drive() is Outcome.COMPLETED
    v = build_view(paths.run_dir)
    assert v.process == "completed" and v.now_word == "COMPLETE" and "5/5 properties pass" in v.now_text
    assert [s.state for s in v.stages] == ["done"] * 5 and v.current_stage == "verify"
    assert v.stages[1].note.startswith("Frozen v1") and v.stages[1].rounds == "Round 1/1"
    assert v.tokens["author"] > 0 and v.tokens["checker"] > 0
    assert v.stages[-1].rows and v.stages[-1].rows[0]["verdict"] == "pass"
    assert set(v.token_series) == {"author", "checker"}
    probs, warns = check(paths.run_dir)
    assert probs == [], probs
    # the hash changes when a live file changes
    h1 = v.refresh_hash
    with paths.events.open("a") as f:
        f.write("\n")  # a blank line: skipped by the reader, but a live file changed
    assert build_view(paths.run_dir).refresh_hash != h1


def test_halted_run_view(tmp_path):
    with walk.env(FAKE_MODELS="1", FAKE_REFUSE="author:same"):
        paths, recipe, task = walk.start("code_builder", tmp_path / "run")
        assert walk.make_runner(paths, recipe, task).drive() is Outcome.HALTED_HONESTLY
    v = build_view(paths.run_dir)
    assert (
        v.process == "halted honestly"
        and v.now_word == "HALT"
        and "p0-ledger" in v.now_text
        and "Resume" in v.now_text
    )
    assert v.stages[0].state == "halted" and [c.key for c in v.chips] == ["halts", "refused"]
    assert check(paths.run_dir)[0] == []


def test_gated_run_view(tmp_path):
    with walk.env(FAKE_MODELS="1"):
        paths, recipe, task = walk.start("code_builder", tmp_path / "run", mode=Mode.LIGHT)
        walk.make_runner(paths, recipe, task, gate_timeout=0.2).drive()
    v = build_view(paths.run_dir)
    assert v.now_word in ("GATE", "HALT")
    gated = [s for s in v.stages if s.gate]
    assert gated and gated[0].gate["id"] == "ledger.r1" and gated[0].gate["questions"]
    assert check(paths.run_dir)[0] == []


def test_view_serialises(tmp_path):
    with walk.env(FAKE_MODELS="1"):
        paths, recipe, task = walk.start("code_builder", tmp_path / "run")
        walk.make_runner(paths, recipe, task).drive()
    js = json.loads(json.dumps(build_view(paths.run_dir).model_dump(mode="json"), default=str))
    assert js["run_id"] == "walk" and len(js["stages"]) == 5
