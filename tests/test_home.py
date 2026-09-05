"""§7d: the home's rows, filters, sort, counters and trends, and the step timeline -- pure
functions on walk runs, no browser."""

from datetime import datetime, timezone

from code_steer_model_write import walk
from code_steer_model_write.events import EventLog
from code_steer_model_write.layers.registry import RunRegistry
from code_steer_model_write.state.run import Outcome, RunState
from dashboard import home, timeline
from dashboard.selfcheck import check


def _run(tmp_path, name, **env):
    with walk.env(FAKE_MODELS="1", **env):
        paths, recipe, task = walk.start("code_builder", tmp_path / name)
        out = walk.make_runner(paths, recipe, task).drive()
    return paths, out


def test_home_rows_filters_sort_counters_and_trends(tmp_path):
    ok, _ = _run(tmp_path / "runs", "one")
    halted, out = _run(tmp_path / "runs", "two", FAKE_REFUSE="author:same")
    assert out is Outcome.HALTED_HONESTLY
    reg = RunRegistry(tmp_path / "r.db")
    reg.add_dir(tmp_path / "runs")
    rows = home.rows(reg)
    assert {r.dir for r in rows} == {str(ok.run_dir), str(halted.run_dir)}
    by = {"one" if r.dir == str(ok.run_dir) else "two": r for r in rows}
    assert by["one"].bucket == "completed" and "properties pass" in by["one"].verdict
    assert by["one"].steps_done == by["one"].steps_total and by["one"].tokens > 0 and by["one"].dot == "done"
    assert set(by["one"].eval_values) >= {"pass_rate", "null_fail_rate"}
    assert by["two"].bucket == "halted" and by["two"].dot == "halted" and by["two"].halt
    c = home.counters(rows)
    assert c["all"] == 2 and c["completed"] == 1 and c["halted"] == 1
    assert [r.dir for r in home.filtered(rows, status="completed")] == [str(ok.run_dir)]
    assert [r.dir for r in home.filtered(rows, query="properties")] == [
        str(ok.run_dir)
    ]  # the verdict is searched
    assert [r.dir for r in home.sorted_rows(rows, "status", desc=False)] == [
        str(ok.run_dir),
        str(halted.run_dir),
    ]
    assert home.sorted_rows(rows, "tokens", desc=True)[0].tokens == max(r.tokens for r in rows)
    tr = home.trends(rows, "code_builder")
    assert len(tr) == 1 and tr[0]["pass_rate"] == 1.0  # the halted run has no evals, so no point
    # forget: the registry stops listing, the folder stays, a scan does not bring it back
    reg.forget(halted.run_dir)
    reg.scan()
    assert {r.dir for r in home.rows(reg)} == {str(ok.run_dir)} and halted.state.exists()
    reg.remember(halted.run_dir)
    assert len(home.rows(reg)) == 2
    # the cache: a second read of an unchanged run is the same object
    assert home.row_for(ok.run_dir) is home.row_for(ok.run_dir)


def test_timeline_rows_from_events(tmp_path):
    paths, _ = _run(tmp_path, "run")
    evs = EventLog(paths.events, RunState.load(paths).run_id).all()
    rs = timeline.rows(evs)
    st = RunState.load(paths)
    assert [r.step for r in rs] == sorted(
        (k for k, r in st.steps.items() if r.started_at), key=lambda k: (st.steps[k].started_at, k)
    )
    assert all(r.done and r.end >= r.start for r in rs)
    authored = [r for r in rs if r.kind == "author"]
    assert authored and all(r.call_start is not None and r.tokens > 0 for r in authored)
    assert all(r.call_start is None for r in rs if r.kind in ("code", "gate"))
    # a step still running ends at `now`
    open_evs = [e for e in evs if not (e.kind == "step.done" and e.step == rs[-1].step)]
    later = datetime.now(timezone.utc)
    last = timeline.rows(open_evs, now=later)[-1]
    assert not last.done and last.end > rs[-1].start
    assert check(paths.run_dir)[0] == []
