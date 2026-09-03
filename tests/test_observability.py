"""Step 10: MLflow mirrors the event log (a sink), monitor.db indexes runs (UI-only), Prefect
wraps the same loop. All local, zero tokens."""

import os

import pytest

from code_steer_model_write import walk
from code_steer_model_write.observability.monitor_db import MonitorDb
from code_steer_model_write.state.run import Outcome, RunState


def _happy_run(tmp_path):
    with walk.env(FAKE_MODELS="1"):
        paths, recipe, task = walk.start("code_builder", tmp_path / "run")
        runner = walk.make_runner(paths, recipe, task)
    return paths, recipe, task, runner


def test_mlflow_mirror_records_spans_metrics_and_artifacts(tmp_path):
    from code_steer_model_write.observability.mlflow_bridge import MlflowMirror

    paths, recipe, task, runner = _happy_run(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    os.environ["MLFLOW_TRACKING_URI"] = uri
    mirror = MlflowMirror(uri, "walk", "code_builder", paths.run_dir)
    mirror.attach(runner.events)
    with walk.env(FAKE_MODELS="1"):
        assert runner.drive() is Outcome.COMPLETED
    import mlflow

    mlflow.set_tracking_uri(uri)
    runs = mlflow.search_runs(experiment_names=["code_builder"])
    assert len(runs) == 1
    row = runs.iloc[0]
    assert row["tags.status"] == "COMPLETED" and row["metrics.calls"] > 5
    assert row["metrics.tokens_author_total"] > 0 and row["metrics.tokens_checker_total"] > 0
    exp = mlflow.get_experiment_by_name("code_builder")
    traces = mlflow.search_traces(locations=[exp.experiment_id])
    assert len(traces) >= 1
    arts = {a.path for a in mlflow.MlflowClient().list_artifacts(row["run_id"])}
    assert {"REPORT.md", "events.jsonl", "state.json"} <= arts


def test_monitor_db_indexes_runs_and_refreshes_from_state(tmp_path):
    paths, recipe, task, runner = _happy_run(tmp_path)
    db = MonitorDb(tmp_path / "monitor.db")
    db.register(paths)
    assert db.runs()[0]["status"] == "QUEUED"
    with walk.env(FAKE_MODELS="1"):
        runner.drive()
    rows = db.refresh()  # the owner is state.json; the index follows it
    assert rows[0]["status"] == "COMPLETED" and rows[0]["outcome"] == "completed"
    db.set_ui("selected_run", "walk")
    assert db.get_ui("selected_run") == "walk" and db.get_ui("nope", 1) == 1


@pytest.mark.skipif(
    os.environ.get("CSMW_TEST_PREFECT", "") == "",
    reason="set CSMW_TEST_PREFECT=1: starts Prefect's ephemeral API (slow)",
)
def test_prefect_flow_runs_the_same_loop(tmp_path):
    from code_steer_model_write.workflow.flows import drive_with_prefect

    paths, recipe, task, runner = _happy_run(tmp_path)
    with walk.env(FAKE_MODELS="1"):
        assert drive_with_prefect(runner) is Outcome.COMPLETED
    assert RunState.load(paths).status.value == "COMPLETED"
