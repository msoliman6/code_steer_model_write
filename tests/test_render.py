import pytest

from code_steer_model_write.artifacts.render import render, resolve_ids


def test_render_model_and_human(finding_models):
    Finding, Findings = finding_models
    a = Findings(
        findings=[
            Finding(
                severity="major",
                cites=["C-0001"],
                argument="the clause C-0001 says nothing about empties, " * 2,
            )
        ],
        verdict="REVISE",
    )
    md = render(a)
    assert md.startswith("## Findings\n") and "| severity | cites | argument |" in md and "C-0001" in md
    human = render(a, "human", glossary={"C-0001": "the input is a string"})
    assert "the input is a string (C-0001)" in human
    assert render(a) == render(a)  # pure


def test_render_refuses_raw(finding_models):
    with pytest.raises(TypeError):
        render({"a": 1})
    with pytest.raises(TypeError):
        render('{"a": 1}')


def test_drop_field_makes_a_view(finding_models):
    Finding, Findings = finding_models
    a = Findings(findings=[], verdict="APPROVED")
    assert "verdict" not in render(a, drop={"verdict"})


def test_resolve_ids_leaves_unknown():
    assert resolve_ids("C-0001 and Z-0002", {"C-0001": "x"}) == "x (C-0001) and Z-0002"
