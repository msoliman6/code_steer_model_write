"""The workflow figure, generated from a RecipeSpec (rule 4: one owner; the figure cannot drift
from the workflow). The style is freeze-and-swap's `pipeline-dark.svg`: glass boxes -- a
translucent fill with a tinted stroke and light text -- on a transparent canvas, so the host's
ground shows through; a flat light variant for light pages. Every colour, size and spacing here
is a token; docs/PLAN.md §7b lists them."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .recipes import registry
from .recipes.base import RecipeSpec

Theme = Literal["dark", "light"]

FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
W = 1000
CX = 500

# ---- tokens ------------------------------------------------------------------------------

ACTORS = {  # role side -> (rgb, glyph, glyph colour, legend label default)
    "a": ((219, 109, 40), "✳", "#db6d28"),
    "b": ((47, 163, 154), "☘", "#2fa39a"),
    "you": ((212, 167, 44), None, None),
    "both": ((163, 113, 247), None, None),
    "code": ((139, 148, 158), None, None),
}
LIGHT_FILL = {
    "a": "#fbe1cc",
    "b": "#d4efe8",
    "you": "#fbf0c4",
    "both": "#e6e2f5",
    "code": "#dbe3ee",
    "start": "#e9e9e9",
}
HUES = {  # stage hue -> (rgb, label colour)
    "blue": ((77, 143, 220), "#6ea6e8"),
    "gold": ((187, 128, 9), "#d69a26"),
    "violet": ((154, 110, 224), "#b28ae8"),
    "teal": ((47, 163, 154), "#43bdb2"),
    "red": ((208, 74, 69), "#e06661"),
    "slate": ((139, 148, 158), "#9aa4ae"),
}
TEXT = {"dark": "#e6edf3", "light": "#4b4b4b"}
MUTED = {"dark": "#9aa4ae", "light": "#8a8a8a"}
FOOT = {"dark": "#8b949e", "light": "#8a8a8a"}
ARROW = {"dark": "#c9d1d9", "light": "#9a9a9a"}
ARROW_W = {"dark": 2, "light": 2.5}
BAND_LIGHT = "#f2f4f7"
BOX_H, BOX_H2, BAND_H, BAND_H2, BAND_H3 = 58, 72, 118, 130, 214
GAP, ARROW_LEN = 36, 34
LABEL_DY, BOX_DY = 28, 40


def _data_uri(path: Path) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


_ASSETS = Path(__file__).resolve().parent.parent / "assets"
MARKS = {  # the two sides' marks, embedded so the figure shows what the page shows
    "a": _ASSETS / "claude-64.png",
    "b": _ASSETS / "codex-64.png",
}


def rgba(rgb: tuple[int, int, int], a: float) -> str:
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{a})"


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    kind: str  # a | b | you | both | code | start | freeze | output
    lines: list[str]
    weight: int = 600
    size: int = 19
    glyph: bool = True


@dataclass
class Band:
    y: float
    h: float
    hue: str
    label: str


@dataclass
class Figure:
    boxes: list[Box] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    arrows: list[tuple[float, float, float, float, bool, bool]] = field(
        default_factory=list
    )  # x1,y1,x2,y2,dashed,both_ends
    labels: list[tuple[float, float, str]] = field(default_factory=list)  # italic muted, centred
    footnote: list[str] = field(default_factory=list)
    height: float = 0


# ---- layout --------------------------------------------------------------------------------


def _kind_of(phrase: str) -> str:
    p = phrase.strip()
    if p.startswith("{A}"):
        return "a"
    if p.startswith("{B}"):
        return "b"
    if p.lower().startswith("you "):
        return "you"
    if p.lower().startswith("each failure") or p.lower().startswith("both"):
        return "both"
    return "code"


def _text(phrase: str, names: dict[str, str]) -> list[str]:
    return [ln.replace("{A}", names["a"]).replace("{B}", names["b"]) for ln in phrase.split("\n")]


def layout(spec: RecipeSpec, *, names: dict[str, str] | None = None) -> Figure:
    names = names or {"a": "Claude", "b": "Codex"}
    f = Figure()
    y = 34.0
    f.boxes.append(Box(CX - 110, y, 220, 50, "start", ["Your brief"]))
    y += 50

    def vconnect(y0: float) -> float:
        f.arrows.append((CX, y0, CX, y0 + ARROW_LEN, False, False))
        return y0 + GAP

    y = vconnect(y)
    gate_by_id = {g.id: g for g in spec.gates}
    for st in spec.stages:
        fig = st.figure
        label = f"{st.n} · {st.title.upper()}" + (f" — {st.qualifier}" if st.qualifier else "")
        top = y
        if fig.second_line and not fig.checker:  # one wide "both" box, two lines
            f.bands.append(Band(top, BAND_H2, st.hue, label))
            f.boxes.append(
                Box(
                    150,
                    top + BOX_DY,
                    700,
                    BOX_H2,
                    _kind_of(fig.author),
                    [*_text(fig.author, names), fig.second_line],
                )
            )
            y = top + BAND_H2
        elif fig.checker and fig.extra and "\n" in fig.author:  # two tall boxes, a merge box, fan-in
            f.bands.append(Band(top, BAND_H3, st.hue, label))
            f.boxes.append(
                Box(100, top + BOX_DY, 340, BOX_H2, _kind_of(fig.author), _text(fig.author, names))
            )
            f.boxes.append(
                Box(560, top + BOX_DY, 340, BOX_H2, _kind_of(fig.checker), _text(fig.checker, names))
            )
            my = top + BOX_DY + BOX_H2 + 36
            f.boxes.append(Box(330, my, 340, 54, "code", [fig.extra[0]]))
            f.arrows.append((270, top + BOX_DY + BOX_H2, 412, my - 4, False, False))
            f.arrows.append((730, top + BOX_DY + BOX_H2, 588, my - 4, False, False))
            y = top + BAND_H3
        elif fig.checker and fig.extra:  # three across, a sequence; the actor on its own line
            f.bands.append(Band(top, BAND_H2, st.hue, label))
            xs = (88, 371, 654)
            phrases = [fig.author, fig.checker, fig.extra[0]]
            for x, ph in zip(xs, phrases, strict=True):
                lines = _text(ph, names)
                if _kind_of(ph) in ("a", "b") and len(lines) == 1 and " " in lines[0]:
                    lines = list(lines[0].split(" ", 1))  # "Claude" / "writes the contract"
                f.boxes.append(Box(x, top + BOX_DY, 258, BOX_H2, _kind_of(ph), lines, size=18))
            cy = top + BOX_DY + BOX_H2 / 2 - 2
            f.arrows.append((350, cy, 367, cy, False, False))
            f.arrows.append((633, cy, 650, cy, False, False))
            y = top + BAND_H2
        elif fig.checker:  # author and checker, review rounds between them
            f.bands.append(Band(top, BAND_H, st.hue, label))
            f.boxes.append(Box(100, top + BOX_DY, 320, BOX_H, _kind_of(fig.author), _text(fig.author, names)))
            f.boxes.append(
                Box(580, top + BOX_DY, 320, BOX_H, _kind_of(fig.checker), _text(fig.checker, names))
            )
            cy = top + BOX_DY + BOX_H / 2
            f.arrows.append((430, cy, 570, cy, True, True))
            if fig.rounds:
                f.labels.append((CX, cy - 21, fig.rounds))
            y = top + BAND_H
        else:  # a single author box
            f.bands.append(Band(top, BAND_H, st.hue, label))
            f.boxes.append(
                Box(CX - 140, top + BOX_DY, 280, BOX_H, _kind_of(fig.author), _text(fig.author, names))
            )
            y = top + BAND_H
        for gid in st.gates_after:
            g = gate_by_id[gid]
            if g.trigger == "conditional":
                continue
            y = vconnect(y)
            w = 280 if len(g.figure_label) <= 24 else 320
            f.boxes.append(Box(CX - w / 2, y, w, 54, "you", [g.figure_label]))
            y += 54
        if st.freeze_label:
            y = vconnect(y)
            f.boxes.append(Box(CX - 200, y, 400, 54, "freeze", [st.freeze_label], weight=700))
            y += 54
        y = vconnect(y)
    f.boxes.append(Box(CX - 210, y, 420, 50, "output", [spec.output_label], weight=500))
    y += 50
    f.footnote = list(spec.footnote)
    f.height = y + 14 + 24 * (len(f.footnote) - 1) + 26 if f.footnote else y + 26
    return f


# ---- render --------------------------------------------------------------------------------


def _box_style(b: Box, theme: Theme) -> tuple[str, str, float]:
    if theme == "light":
        fill = LIGHT_FILL.get(b.kind, LIGHT_FILL["code"] if b.kind in ("freeze",) else "#e9e9e9")
        return fill, "none", 0
    if b.kind == "start" or b.kind == "output":
        return rgba(ACTORS["code"][0], 0.12), rgba(ACTORS["code"][0], 0.55), 1.5
    if b.kind == "freeze":
        return rgba(ACTORS["code"][0], 0.14), "rgba(201,209,217,0.8)", 1.8
    if b.kind == "code":
        return rgba(ACTORS["code"][0], 0.14), rgba(ACTORS["code"][0], 0.6), 1.5
    if b.kind == "both":
        return rgba(ACTORS["both"][0], 0.13), rgba(ACTORS["both"][0], 0.65), 1.5
    rgb = ACTORS[b.kind][0]
    return rgba(rgb, 0.14), rgba(rgb, 0.7), 1.5


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_svg(f: Figure, theme: Theme, *, names: dict[str, str] | None = None) -> str:
    names = names or {"a": "Claude", "b": "Codex"}
    arrow, aw = ARROW[theme], ARROW_W[theme]
    text, muted, foot = TEXT[theme], MUTED[theme], FOOT[theme]
    L: list[str] = []
    H = int(f.height)
    L.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}">'
    )
    L.append("<defs>")
    L.append(
        f'<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{arrow}"/></marker>'
    )
    L.append(
        f'<marker id="ah-rev" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="{arrow}"/></marker>'
    )
    L.append("</defs>")
    if theme == "light":
        L.append(f'<rect width="{W}" height="{H}" rx="22" fill="#ffffff"/>')
    else:
        L.append("<!-- transparent canvas: the host page's dark ground shows through -->")
    # legend
    legend = [
        ("a", names["a"], 650, 24),
        ("b", names["b"], 650, 50),
        ("you", "You", 650, 76),
        ("both", "Both", 770, 24),
        ("code", "Code — no model", 770, 50),
    ]
    for kind, label, x, y in legend:
        rgb = ACTORS[kind][0]
        if theme == "light":
            L.append(f'<rect x="{x}" y="{y}" width="26" height="18" rx="6" fill="{LIGHT_FILL[kind]}"/>')
        else:
            a_fill, a_stroke = (0.16, 0.6) if kind == "code" else (0.22, 0.75)
            L.append(
                f'<rect x="{x}" y="{y}" width="26" height="18" rx="6" fill="{rgba(rgb, a_fill)}" stroke="{rgba(rgb, a_stroke)}" stroke-width="1.2"/>'
            )
        L.append(
            f'<text x="{x + 36}" y="{y + 9}" dominant-baseline="central" font-size="15" fill="{muted}">{_esc(label)}</text>'
        )
    L.append(
        f'<line x1="770" y1="85" x2="804" y2="85" stroke="{arrow}" stroke-width="{aw}" stroke-linecap="round"/>'
    )
    L.append(f'<text x="814" y="85" dominant-baseline="central" font-size="15" fill="{muted}">a step</text>')
    L.append(
        f'<line x1="770" y1="111" x2="804" y2="111" stroke="{arrow}" stroke-width="{aw}" stroke-linecap="round" stroke-dasharray="7 6"/>'
    )
    L.append(
        f'<text x="814" y="111" dominant-baseline="central" font-size="15" fill="{muted}">review rounds</text>'
    )
    # bands first (under the boxes)
    for b in f.bands:
        rgb, lab = HUES[b.hue]
        if theme == "light":
            L.append(f'<rect x="60" y="{b.y:g}" width="880" height="{b.h:g}" rx="18" fill="{BAND_LIGHT}"/>')
            L.append(
                f'<text x="82" y="{b.y + LABEL_DY:g}" font-size="15" font-weight="600" letter-spacing="1.5" fill="{muted}">{_esc(b.label)}</text>'
            )
        else:
            a = 0.06 if b.h > BAND_H else 0.07
            L.append(f'<!-- {_esc(b.label)} — stage hue {b.hue} -->')
            L.append(
                f'<rect x="60" y="{b.y:g}" width="880" height="{b.h:g}" rx="18" fill="{rgba(rgb, a)}" stroke="{rgba(rgb, 0.5)}" stroke-width="1.5"/>'
            )
            L.append(
                f'<text x="82" y="{b.y + LABEL_DY:g}" font-size="15" font-weight="600" letter-spacing="1.5" fill="{lab}">{_esc(b.label)}</text>'
            )
    for b in f.boxes:
        fill, stroke, sw = _box_style(b, theme)
        stroke_attr = f' stroke="{stroke}" stroke-width="{sw}"' if stroke != "none" else ""
        L.append(
            f'<rect x="{b.x:g}" y="{b.y:g}" width="{b.w:g}" height="{b.h:g}" rx="14" fill="{fill}"{stroke_attr}/>'
        )
        n = len(b.lines)
        color = "#ffffff" if (b.kind == "freeze" and theme == "dark") else text
        for i, ln in enumerate(b.lines):
            cy = b.y + b.h / 2 + (i - (n - 1) / 2) * 24.8
            glyph = ""
            dx = 0.0
            if i == 0 and b.glyph and b.kind in ("a", "b"):
                mark = MARKS[b.kind]
                if mark.exists():  # the side's mark, as on the page
                    if n > 1:  # the actor's name alone on the line: the mark sits just before it
                        tw = len(ln) * 0.58 * b.size
                        mx = b.x + b.w / 2 - (28 + tw) / 2
                        dx = 14.0
                    else:
                        mx = b.x + 14
                        dx = 12.0
                    L.append(
                        f'<image href="{_data_uri(mark)}" x="{mx:g}" y="{cy - 11:.1f}" width="22" height="22"/>'
                    )
                elif theme == "dark":
                    g, gc = ACTORS[b.kind][1], ACTORS[b.kind][2]
                    glyph = f'<tspan fill="{gc}">{g} </tspan>'
            L.append(
                f'<text x="{b.x + b.w / 2 + dx:g}" y="{cy:.1f}" text-anchor="middle" dominant-baseline="central" font-size="{b.size}" font-weight="{b.weight}" fill="{color}">{glyph}{_esc(ln)}</text>'
            )
    for x1, y1, x2, y2, dashed, both in f.arrows:
        extra = ' marker-start="url(#ah-rev)"' if both else ""
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        L.append(
            f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{arrow}" stroke-width="{aw}" stroke-linecap="round" marker-end="url(#ah)"{extra}{dash}/>'
        )
    for x, y, t in f.labels:
        L.append(
            f'<text x="{x:g}" y="{y:g}" text-anchor="middle" dominant-baseline="central" font-size="15" font-style="italic" fill="{muted}">{_esc(t)}</text>'
        )
    fy = f.height - 26 - 24 * (len(f.footnote) - 1)
    for i, ln in enumerate(f.footnote):
        L.append(
            f'<text x="{CX}" y="{fy + 24 * i:g}" text-anchor="middle" dominant-baseline="central" font-size="16" font-style="italic" fill="{foot}">{_esc(ln)}</text>'
        )
    L.append("</svg>")
    return "\n".join(L) + "\n"


def figure_svg(recipe_name: str, theme: Theme = "dark", *, names: dict[str, str] | None = None) -> str:
    spec = registry.get(recipe_name).spec
    return render_svg(layout(spec, names=names), theme, names=names)


def write_figure(
    recipe_name: str, out: Path, *, theme: Theme = "dark", names: dict[str, str] | None = None
) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(figure_svg(recipe_name, theme, names=names), encoding="utf-8")
    return out
