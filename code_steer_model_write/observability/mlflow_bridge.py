"""MLflow as a sink (rule 4, 10): spans mirror the event log, one span per step and per call,
metrics per role; nothing the driver needs is read back. A mirror failing never stops the run.
Local tracking: `sqlite:///mlflow.db`, no server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..events import EventLog
from ..spec.events import Event


class MlflowMirror:
    def __init__(self, tracking_uri: str, run_id: str, recipe: str, run_dir: Path) -> None:
        import mlflow

        self.mlflow = mlflow
        mlflow.set_tracking_uri(tracking_uri)
        exp = mlflow.set_experiment(recipe)
        self._exp_id = exp.experiment_id
        # every write names the run: a worker thread with no "active run" of its own would
        # otherwise make MLflow start a second run for it (ledger: a second owner of a fact)
        self._client = mlflow.MlflowClient(tracking_uri=tracking_uri)
        self._rid: str = ""
        self.run_id = run_id
        self.run_dir = run_dir
        self._run = None
        self._root = None
        self._spans: dict[str, Any] = {}
        self._tokens: dict[str, int] = {}
        self._calls = 0

    def attach(self, log: EventLog) -> None:
        log.subscribe(self.on_event)

    # ---- one listener ----------------------------------------------------------------------

    def on_event(self, e: Event) -> None:
        m = self.mlflow
        try:
            if e.kind == "run.status" and e.data.get("status") in ("RUNNING",) and self._run is None:
                self._run = self._client.create_run(
                    experiment_id=self._exp_id,
                    run_name=self.run_id,
                    tags={"workflow_run_id": self.run_id, "recipe": self.run_dir.name},
                )
                self._rid = self._run.info.run_id
                self._root = m.start_span_no_context(
                    name=f"run:{self.run_id}", attributes={"workflow_run_id": self.run_id}
                )
            elif e.kind == "step.started" and e.step:
                self._spans[e.step] = m.start_span_no_context(
                    name=e.step, parent_span=self._root, attributes={"step": e.step}
                )
            elif e.kind == "call.started" and e.step:
                key = f"{e.step}:call:{e.attempt}"
                self._spans[key] = m.start_span_no_context(
                    name=f"{e.step} call {e.attempt}",
                    parent_span=self._spans.get(e.step),
                    attributes={  # str values only: the span API's contract
                        # the OpenTelemetry GenAI names (ARCHITECTURE.md 7.9), so any OTLP backend
                        # reads these spans the same way MLflow does
                        "gen_ai.operation.name": "chat",
                        "gen_ai.request.model": str(e.data.get("model", "")),
                        "gen_ai.agent.name": e.role or "",
                        "csmw.schema": str(e.data.get("schema", "")),
                        "csmw.attempt": str(e.attempt or 1),
                    },
                )
                self._calls += 1
            elif e.kind == "call.usage" and e.role:
                sp = self._spans.get(f"{e.step}:call:{e.attempt}")
                if sp is not None:
                    sp.set_attributes(
                        {
                            "gen_ai.usage.input_tokens": int(e.data.get("input_tokens", 0)),
                            "gen_ai.usage.output_tokens": int(e.data.get("output_tokens", 0)),
                            "gen_ai.usage.cache_read_tokens": int(e.data.get("cache_read_tokens", 0)),
                        }
                    )
                self._tokens[e.role] = (
                    self._tokens.get(e.role, 0)
                    + int(e.data.get("input_tokens", 0))
                    + int(e.data.get("output_tokens", 0))
                )
                if self._run is not None:
                    self._client.log_metric(self._rid, f"tokens_{e.role}", self._tokens[e.role], step=e.seq)
            elif e.kind in ("call.final", "call.error") and e.step:
                sp = self._spans.pop(f"{e.step}:call:{e.attempt}", None)
                if sp is not None:
                    sp.set_attributes({k: str(v)[:200] for k, v in e.data.items()})
                    sp.end(status="OK" if e.kind == "call.final" else "ERROR")
            elif e.kind in ("step.done", "step.refused") and e.step:
                sp = self._spans.pop(e.step, None) if e.kind == "step.done" else self._spans.get(e.step)
                if sp is not None and e.kind == "step.done":
                    sp.end(status="OK")
            elif e.kind == "halt":
                if self._run is not None:
                    self._client.set_tag(self._rid, "halt", f"{e.step}: {e.data.get('reason')}")
            elif e.kind == "run.status" and e.data.get("status") in (
                "COMPLETED",
                "PAUSED",
                "FAILED",
                "CANCELLED",
            ):
                self.finish(e.data.get("status", ""), e.data.get("outcome"))
        except Exception as ex:  # noqa: BLE001 -- a mirror never stops the run
            print(f"[mlflow] mirror error on {e.kind}: {ex}")

    def finish(self, status: str, outcome: str | None) -> None:
        for sp in list(self._spans.values()):
            try:
                sp.end(status="ERROR")
            except Exception:  # noqa: BLE001
                pass
        self._spans.clear()
        if self._root is not None:
            self._root.set_attributes({"status": status, "outcome": outcome or ""})
            self._root.end(status="OK" if status == "COMPLETED" else "ERROR")
            self._root = None
        if self._run is not None:
            self._client.set_tag(self._rid, "status", status)
            self._client.set_tag(self._rid, "outcome", outcome or "")
            self._client.log_metric(self._rid, "calls", self._calls)
            for role, n in self._tokens.items():
                self._client.log_metric(self._rid, f"tokens_{role}_total", n)
            # the evals (7.9): the record is evals.json; MLflow holds its metrics as a mirror
            ev = self.run_dir / "evals.json"
            if ev.exists():
                try:
                    import json as _json

                    for r in _json.loads(ev.read_text()).get("results", []):
                        if r.get("value") is not None:
                            self._client.log_metric(self._rid, f"eval_{r['metric']}", float(r["value"]))
                        if r.get("passed") is not None:
                            self._client.set_tag(
                                self._rid, f"eval_{r['metric']}_passed", str(r["passed"]).lower()
                            )
                except Exception as ex:  # noqa: BLE001
                    print(f"[mlflow] evals not mirrored: {ex}")
            if (self.run_dir / "evals.json").exists():
                self._client.log_artifact(self._rid, str(self.run_dir / "evals.json"))
            for name in ("report.json", "REPORT.md", "events.jsonl", "state.json"):
                p = (
                    self.run_dir / name
                    if name != "report.json"
                    else self.run_dir / "artifacts" / "report" / "v001.json"
                )
                if p.exists():
                    self._client.log_artifact(self._rid, str(p))
            self._client.set_terminated(self._rid)
            self._run = None
