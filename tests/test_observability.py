"""Step 10: MLflow mirrors the event log (a sink), Prefect
wraps the same loop. All local, zero tokens."""

import os


from code_steer_model_write import walk
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


def test_prefect_flow_runs_the_same_loop(tmp_path):
    from code_steer_model_write.workflow.flows import drive_with_prefect

    paths, recipe, task, runner = _happy_run(tmp_path)
    with walk.env(FAKE_MODELS="1"):
        assert drive_with_prefect(runner) is Outcome.COMPLETED
    assert RunState.load(paths).status.value == "COMPLETED"
