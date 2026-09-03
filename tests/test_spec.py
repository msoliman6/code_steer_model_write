import json

import jsonschema
import pytest
from pydantic import ValidationError

from code_steer_model_write.spec.base import CheckContext


def test_wire_schema_is_strict_and_stripped(finding_models):
    _, Findings = finding_models
    s = Findings.wire_schema()
    assert s["additionalProperties"] is False
    assert s["required"] == ["findings", "verdict"]
    f = s["$defs"]["Finding"]
    assert f["required"] == ["severity", "cites", "argument"]
    txt = json.dumps(s)
    for kw in ("minLength", "minItems", "examples", "default", '"title": "Finding"'):
        assert kw not in txt, kw
    assert "description" in txt


def test_wire_schema_stable_across_calls(finding_models):
    _, Findings = finding_models
    assert Findings.wire_schema() == Findings.wire_schema()


def test_validator_keeps_the_stripped_rules(finding_models):
    _, Findings = finding_models
    with pytest.raises(ValidationError):
        Findings.model_validate(
            {"findings": [{"severity": "minor", "cites": [], "argument": "x" * 50}], "verdict": "REVISE"}
        )
    with pytest.raises(ValidationError):
        Findings.model_validate({"findings": [], "verdict": "REVISE", "extra": 1})


def test_template_and_guide(finding_models):
    _, Findings = finding_models
    t = json.loads(Findings.template())
    assert set(t) == {"findings", "verdict"}
    assert t["verdict"].startswith("<one of:")
    g = Findings.guide()
    assert "`findings[].cites`" in g and '`["C-0001"]`' in g


def test_wire_schema_validates_a_real_answer_with_jsonschema(finding_models):
    _, Findings = finding_models
    ans = {
        "findings": [{"severity": "major", "cites": ["C-0001"], "argument": "a" * 50}],
        "verdict": "REVISE",
    }
    jsonschema.validate(ans, Findings.wire_schema())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"findings": [], "verdict": "REVISE", "x": 1}, Findings.wire_schema())


def test_semantic_problems_and_cites(finding_models):
    _, Findings = finding_models
    a = Findings.model_validate(
        {
            "findings": [{"severity": "major", "cites": ["C-0009"], "argument": "a" * 50}],
            "verdict": "APPROVED",
        }
    )
    probs = a.semantic_problems(CheckContext(known_ids={"C-0001"}))
    assert [p.code for p in probs] == ["cite_unresolved", "verdict_contradicts"]
    assert a.cited_ids() == ["C-0009"]
