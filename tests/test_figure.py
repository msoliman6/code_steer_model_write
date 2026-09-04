"""The workflow figure is generated from the recipe and pinned to the reference's geometry (§7b)."""

import re
from pathlib import Path

from code_steer_model_write.figure import figure_svg

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "docs" / "media" / "reference-pipeline-dark.svg"


def _rects(svg: str) -> set[tuple[str, ...]]:
    return set(re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg))


def _colours(svg: str) -> set[str]:
    return set(re.findall(r'(?:fill|stroke)="(#[0-9a-f]{6}|rgba\([^)]*\))"', svg))


def test_dark_figure_matches_reference_geometry():
    new = figure_svg("code_builder", "dark")
    ref = REF.read_text()
    assert _rects(new) == _rects(ref), sorted(_rects(new) ^ _rects(ref))
    assert new.count("<line") == ref.count("<line") and new.count("<text") == ref.count("<text")
    assert re.search(r'viewBox="0 0 1000 (\d+)"', new).group(1) == re.search(
        r'viewBox="0 0 1000 (\d+)"', ref
    ).group(1)
    assert _colours(new) <= _colours(ref), _colours(new) - _colours(ref)
    assert new.count("<image") == 9  # a mark in every actor box (2+2+3+2)
    for label in (
        "0 · PLAN",
        "1 · CONTRACTS",
        "2 · VERIFICATION DESIGN",
        "3 · BUILD — TWO ISOLATED AUTHORS",
        "4 · VERIFICATION RUN",
    ):
        assert label in new, label
    assert (
        "Freeze — the contract is hashed" in new
        and "You confirm the blocks" in new
        and "You confirm the verification" in new
    )
    assert "<!-- transparent canvas" in new


def test_light_figure_is_flat_and_both_themes_render():
    light = figure_svg("code_builder", "light")
    assert 'fill="#ffffff"' in light and "rgba(" not in light and "✳" not in light and "<image" in light
    assert _rects(light) == _rects(figure_svg("code_builder", "dark"))


def test_actor_names_are_parameters():
    svg = figure_svg("code_builder", "dark", names={"a": "Sonnet", "b": "GPT"})
    assert "Sonnet writes the plan" in svg and "GPT attacks it" in svg and "Claude" not in svg


def test_debate_figure_renders_from_its_spec():
    svg = figure_svg("debate", "dark")
    assert "<svg" in svg and "HYPOTHESES" in svg.upper()
