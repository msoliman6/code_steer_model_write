import os
import threading

import pytest
from pydantic import ValidationError

from code_steer_model_write.artifacts.store import Store
from code_steer_model_write.events import EventLog
from code_steer_model_write.state.lock import atomic_write_text


def test_store_versions_and_sha(tmp_path, finding_models):
    _, Findings = finding_models
    s = Store(tmp_path)
    a = Findings(findings=[], verdict="APPROVED")
    assert s.write("findings", a) == 1
    assert s.write("findings", a) == 2
    assert s.versions("findings") == [1, 2]
    assert s.read("findings", Findings).verdict == "APPROVED"
    assert s.sha("findings", 1) == s.sha("findings", 2)
    b = Findings(findings=[], verdict="REVISE")
    s.write("findings", b)
    d = s.diff("findings", 2, 3)
    assert '-  "verdict": "APPROVED"' in d and '+  "verdict": "REVISE"' in d


def test_atomic_write_leaves_old_file_on_crash(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    atomic_write_text(p, "old")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    try:
        atomic_write_text(p, "new")
    except OSError:
        pass
    assert p.read_text() == "old"


def test_events_append_read_and_parallel_seq(tmp_path):
    log = EventLog(tmp_path / "events.jsonl", "run1")
    seen = []
    log.subscribe(seen.append)
    log.append("run.status", status="RUNNING")

    def work(i):
        for _ in range(20):
            log.append("call.usage", step=f"s{i}", input_tokens=1)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    evs = log.all()
    assert [e.seq for e in evs] == list(range(1, 82))
    assert evs[0].data == {"status": "RUNNING"} and len(seen) == 81
    assert log.last("run.status").seq == 1
    # strict parse: a corrupt line halts, never "the last line"
    (tmp_path / "events.jsonl").open("a").write("not json\n")
    with pytest.raises(ValidationError):
        log.all()
