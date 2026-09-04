# Dashboard design language

From docs/PLAN.md §7a; the tokens live in `dashboard/theme.py`.

Taken from the freeze-and-swap rail design (spectrum theme, the screenshot the user likes).
Lives in `dashboard/theme.py` (every colour, size and spacing is a named token; no literal in
a component) and `docs/DASHBOARD-DESIGN.md` (this list). The Reflex components in §7 are built
only from these tokens.

**Surface and structure**
1. One dark surface (`#0d1117` class), single column, about 1140px wide. Hierarchy comes from
   1px borders, card padding and spacing, never from filled backgrounds.
2. Every card has the same skeleton: an eyebrow label (what this is), a one-line summary on
   the eyebrow's row (the answer), then the content (the evidence). Header, stage panel and
   evidence card all follow it.
3. The page reads top to bottom as: where are we → what is happening now → is anything wrong
   → the selected stage's answer → the evidence. Nothing above the fold is evidence.

**Typography**
4. Two faces. Monospace for everything machine: ids, model names, tokens, times, event kinds,
   chips, eyebrows, breadcrumbs. Sans for human sentences: stage titles, outcome headlines,
   descriptions, event messages.
5. Eyebrows are small uppercase letter-spaced mono in muted grey (`RESULTS —`, `EVIDENCE`,
   `WHERE THE TIME WENT`, `EVENT LOG · 66 EVENTS`).
6. A five-step scale only: eyebrow 11, body 13, stage title 15, outcome headline 18, page title
   28 (`CSMW_BASE` shifts all). Bold is reserved for stage names and outcome headlines.

**Colour as role, never decoration**
7. Every colour is a role token: a stage hue (one per stage, used on its box edge, its check
   glyph, its panel title, the panel's top border and its swimlane band), an actor hue (model A,
   model B, the human), a status colour (green ok, amber carried/warning, red failing/halt),
   and three greys (text, muted, border). Nothing else.
8. Status is never colour alone: a glyph and a word accompany it (`✓` in the box, `● COMPLETE`,
   `pass (0/3)`).
9. The actor and stage colours pass the dataviz palette validator against the dark surface
   before shipping (checked by a selftest, not by eye).

**The stage rail**
10. One box per stage, left to right. Above the box: `N · actor` and the tokens each side spent
    on it, with vendor glyphs. Inside: the glyph, the stage name, the duration or `Round k/N ·
    m:ss`. Below: one muted line saying what happened (`Frozen v1 · 7 clauses · sha bf31…`,
    `Cap reached (1 blocking, 3 major…)`), truncated with an ellipsis.
11. The selected stage has the strong border; the running stage carries the live pulse;
    unselected stages are dim. The start box is neutral grey and holds the brief and settings.

**Numbers and time**
12. Every number carries its unit and its denominator inline: `4/4 properties pass`,
    `63K tok`, `Round 1/1 · 1:12`, `pass (0/3)`.
13. Both model sides are always shown side by side, per stage and in the clock line, each with
    its vendor glyph. Tokens, never dollars.
14. Wall-clock times are `HH:MM`, durations `m:ss`; a stage panel shows `start → end · duration`.
15. The clock line is `Elapsed · Finished|Remaining · tokens A · tokens B`, with the live value
    underlined like a tab.

**Chips and disclosures**
16. Anything machine-ish and small is an outlined chip in mono with its count inside:
    settings (`detailed`, `Rounds 1`, a model + effort per role), wrong-ness (`Carried findings
    10`, amber), event-log filters (one per stage). Chips are outlined, never filled.
17. A wrong-ness chip is a link: clicking it selects the stage and scrolls to the evidence.
18. Disclosures are collapsed by default and carry their counts in the label (`▸ Outputs · 1`,
    `▸ stage 2 · Verification Design · swimlane · tokens`); a global `Detail: Glance | Full`
    switch opens or closes every disclosure at once.
19. An open gate form is never inside a disclosure.

**The now line**
20. A full-width status bar: a dot, the state word in uppercase mono, then one sentence with
    the numbers (`● COMPLETE  Run complete · 4/4 properties pass · 4 fail on the null · 7.2 min`).
    While running it names the live step and the actor; while gated it names the gate; while
    halted it names the reason. Stop and Resume sit on its right.

**The stage panel**
21. Top border in the stage's hue. Title `Stage N · Name · actors` in the hue. Then one
    paragraph, in plain words, of what the stage does and who checks it. Then `start → end ·
    duration`. Then the outcome headline in bold sans. Then the stage's own records as rows.
22. Result rows: id in muted mono, the property in plain sentence form, the verdict on the
    right with its count in the status colour. The sentence reads without the id.

**Evidence**
23. Charts are minimal: no gridlines, thin bars, a single axis with tick labels, a text legend
    with colour squares, a one-line caption (`The whole run · 7 min`, `Tokens, cumulative`).
24. The swimlane has one lane per actor (model A, model B, you); stage bands as a faint
    background tint in the stage hue; bars in the model's colour; human decisions as diamonds.
25. The cumulative tokens chart is a step line per side, ending in a dot with the total.
26. The event log is a dense mono table: `time · phase · kind (muted) · message`, filter chips
    per stage above it, and every message is a sentence naming the actor and the duration in
    parentheses (`Claude arbitrated the audit (14s)`).

**Behaviour**
27. The page never re-scrolls on a poll that changed nothing; picked stage, open disclosures
    and scroll position survive the reload. A pick on the running stage rides with the run; a
    pick elsewhere stays and a `jump to running` chip appears.
28. A finished run's timer stops at `completed_at`.
29. Everything on the page is proven by `csmw dash selfcheck` (§7), including that every
    disclosure has a stable id and that no component uses a colour outside the token table.

## The start page (run settings)

Taken from freeze-and-swap's settings form (the screenshot the user pointed at). It is the New
Task view of the dashboard: the brief and the run's settings on one page, then one button. The
form derives from **one settings schema** (`code_steer_model_write/settings_form.py`,
`FIELDS`), which also owns the defaults, the descriptions and the option lists; the page, the
CLI (`csmw run --set key=value`) and the saved preferences all read it (rule 4).

**Page**
1. A title line: bold sans `Run settings.` followed by one muted sentence saying what the page
   decides (`How much the run asks of you, and which models do the work.`).
2. One card per setting, full width, stacked with a small gap; card = warm charcoal fill, 1px
   border, 12px radius, generous padding. Nothing else on the card: no icons, no help buttons.
3. Bottom: the `Start the run ▸` button (blue, filled) with one muted sentence beside it saying
   what still blocks it (`The button activates once the run name and the request are filled.`),
   then a sticky footer: the button again (dashed border and a spinner while inactive) and a
   preview of the stage rail: one tile per stage, `N` in muted mono above the stage title in bold
   sans, in order.
4. A closing mono italic muted line: `This page follows the run and takes your choices directly.
   Times are local (PDT).`

**A setting card**
5. Left column, about 130px: the setting's name in bold sans (`plan effort`), under it the
   description in muted sans, clamped to about four lines (the clamp is deliberate: the sentence
   reads as a hint, the full text is the schema's `description`).
6. The description explains the default's reasoning, not the option: `the default: adversarial
   reading is the job, and a weak review looks exactly like convergence`; `fastest; the saving
   usually returns as review rounds — codex finds what claude skipped`.
7. Right: a single row of option chips, one row per setting, single-select. A chip is mono text
   in a small rounded rectangle (6px radius) with a dark fill and muted text; the selected chip
   has a 1.5px blue outline, blue text and a faint blue tint. No dropdowns, no free text except the
   brief and the run name: reacting to a chip beats authoring a value (RELIABILITY D5d).
8. Option values are the real values, in mono: model ids (`gpt-5.4-mini`, `sonnet-5`,
   `haiku-4-5`), effort words (`ultra xhigh high medium low` for the checker's CLI; `default max
   xhigh high medium low` for the author), counts (`1 2 3 4`).
9. The first chip of a per-stage row is the **inherit** option: `default` / `session default`
   (the backend's own choice), `as plan` (inherit the plan row), `as codex` (inherit the checker
   row). Inheritance is a fact the schema states, not a special case in the page.

**Rows and their order**
10. Global first: `running mode` (detailed · light · auto), `attack rounds` (1 · 2 · 3 · 4).
11. The checker side next: `checker model`, `checker effort`, `checker speed` (default · fast).
12. Then one pair per stage for the author side, named after the stage: `plan model`, `plan
    effort`, `contracts model`, `contracts effort`, `verification model`, `verification effort`,
    `build model`, `build effort` — each model row's first chip is `as plan`, each effort row's
    first chip is `as plan`.
13. Then the verification-run overrides for both sides: `verif. run claude` and its effort
    (`as plan`), `verif. run codex` and its effort (`as codex`).
14. The pre-selected setup is the one-round average task: the checker at high effort, the
    contract and verification rows carrying the judgment (sonnet, high), the build on the cheapest
    model at low effort, the verification run inheriting. Your picks are remembered for the next
    run (`prefs.json` beside the runs dir, written by the page, read by the schema).

**Colour and type** are the run page's tokens (§7a): the surface, the card, the border, muted
text, the live blue for the selected chip; mono for every value, sans for names and sentences.

**Verification** — `csmw dash selfcheck` also builds the start page's model: every field in
`FIELDS` renders exactly one card; every card's chips equal the field's options; the selected chip
equals the saved preference or the default; the Start button is inactive iff the run name or the
request is empty; the rail preview equals the recipe's stages in order.

## The run-status control (the bottom bar's right side)

One control: the pill is the button. Its label carries the state word and the one verb that
state allows, so a state never appears without its action and an action never without its
state. Reuse this table for every recipe and every new workflow.

| run state | the pill reads | click does |
|---|---|---|
| running, runner alive | RUNNING · STOP (green) | writes `STOP` in the run dir; the runner halts honestly at the next step boundary, reason "stopped from the page", resumable |
| stopping, requested but not yet halted | STOPPING… (green, disabled) | nothing; flips to HALTED when the runner writes the halt |
| waiting at a gate | GATE · ANSWER (amber) | jumps to the gate form; Proceed and Send back stay in the form |
| halted honestly, resumable | HALTED · RESUME (red) | detached `csmw resume`; continues at the halted step from disk |
| stale, record says running but the runner is gone | STALE · RESUME (red) | the same Resume |
| broke, not resumable | BROKE (red, disabled) | nothing; a "New run like this" link appears beside it |
| queued, created but never driven | QUEUED · START (grey) | the same detached resume, which begins the run |
| completed | DONE (grey; green ring when clean, amber ring when items were carried) | opens the report |

The state comes from one place, `dashboard/model.py::run_control(...)`, which reads state.json,
the runner record, the halt, the gates and the `STOP` file; the runner (`driver/runner.py`)
honours `STOP` between steps. The same rows drive the tab dots.
