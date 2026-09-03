# Plan: `code_steer_model_write` — a reusable template for agentic AI workflows

## The 14 universal rules

These open the plan, the template's `README.md` and its `CLAUDE.md`, verbatim. Every module
docstring, check and walk leg cites the rule number it enforces.

1. **Code controls the workflow end to end.** Sequencing, the next step, whether a step counts,
   every file write, every check run. Models only fill schemas.
2. **Agents read markdown rendered by code from JSON, and write only schema-constrained JSON.**
   No tools, files or shell unless the task needs them, and then only inside the folder the
   agent writes its output to (that folder is the sandbox root).
3. **No agent grades its own work.** The checker gets a frozen copy, and a different vendor
   where possible.
4. **One owner per fact, everything else derives.** The pydantic class owns the shape; JSON
   owns the content and markdown is a view; one gate record feeds every renderer.
5. **Every element has a code-assigned id, never renumbered.** Findings cite ids, so coverage
   is a set difference, not a judgment.
6. **Nothing is recorded from a refused answer.** Stage → check → atomic replace. A refusal is
   re-asked with the exact problems and the refused answer, bounded, stopping when the problem
   set repeats.
7. **The verification ladder.** Code checks first, an AI judge only where no field can answer,
   a human only for a value only they have or a judgment only they can make. Verdicts are
   graded severities, never booleans.
8. **Every loop is bounded by code and carries its full trajectory verbatim.** Convergence is
   computed, not asked. The unresolved is carried into the report, never hidden. The last
   revision always gets a closing read.
9. **No step is issued with nothing to do.** Zero findings → no arbitration; zero questions →
   no gate.
10. **One append-only event log, written as a side effect of the work.** Two signals side by
    side: did the process run, is the product right. Halts are reports, resume comes from disk,
    exit codes are honest (0 done, 1 record, 2 refusal).
11. **Human attention is the scarcest resource.** Batch questions, confirm by exception,
    pre-fill defaults, a mode dial whose auto-answers are flagged, never let waiting look like
    silence.
12. **Prove it offline first.** Fake models walk every branch with zero tokens before any live
    run. A check that never runs is not a check.
13. **Prompts are code-filled templates, not skills.** A missing key refuses before a token is
    spent. Tool denial is stated as fact in the prompt and enforced by the harness.
14. **Cost is a design axis.** No unused tools, thinking off where a check catches every
    mistake, calls batched, tokens as the honest measure.

Rule 2's tool clause in code: a step with `needs_tools=True` gets `scope_root = its output
folder`; `streams.py` kills the call on any write outside it; a tool-less step passes
`tools=()` by construction.

## Status (2026-09-03)

Steps 0–12 built and pushed; step 13 has the debate recipe (walked offline); the research and
tool-assistant recipes are deferred by the user's decision until the pipeline is proven. The
code-builder's live clean pass on `claude -p` + `codex exec` is the acceptance run for `proven`.

## Round two (the user's list, 2026-09-03)

- Logos: one per agent side (Claude, Codex) on the page and the figures; a logo for the coding
  agent itself, to be designed.
- README: badges; the coding agent's logo; both block diagrams are in (done).
- The status boxes' colours and shapes; the Start box back in the rail.
- The opened markdown tables' styling in the Outputs view.
- The verify step reported 0/8 while the tests pass 8/8 by hand (`checks/runtests.py`).
- Claude model discovery: the Anthropic Models API (`client.models.list()`, capabilities) for the
  API-backed sides once a valid key is present; Claude Code itself has no catalogue command, so
  `claude_cli` keeps the table. Codex is dynamic via `codex debug models` (done).
- The start page's settings as dropdowns (done) and the Start box in the rail showing what the run
  was given (done); the user is still listing what else the start page needs.
- The coding agent's logo: one glass ice cube (the frozen contract) with two curved arrows in the
  author's orange and the checker's teal chasing each other around it (the swap); a colour mark and
  a one-colour mark; 🧊🔁 as the placeholder. The agent-side logos: the user will paste them.
- An end-to-end progress bar under the rail, tqdm-like, left-aligned at about a third of the
  width: the stage hues as segments filling as stages complete, the running stage filling by its
  steps done, a percentage beside it, elapsed, and the remaining estimate once history exists.
- Settle where the coding agent lives: the reference recipe inside the template, or its own repo.

## Step zero: save this plan before any code

Before anything else is executed, this plan is copied verbatim to
`~/Documents/Agents_design/code_steer_model_write/docs/PLAN.md` (the new repo's first commit)
and to `~/Documents/Agents_design/agentic_workflow_recipe/PLAN-code_steer_model_write.md`
(next to the reference docs). The template's `README.md` opens with the 14 rules above, then
the thesis, then install and first run.

## Context

The user wants one template to clone for agentic-AI hackathons and for real agentic
workflows: versatile (many task types), reliable (does not break under demo pressure), and
time-saving. Two inputs shape it:

1. **freeze-and-swap** (msoliman6, v0.3.53; its 94 markdown docs are in this folder). A working
   Claude+Codex build loop with a hard-won reliability doctrine: `docs/RELIABILITY.md` (D1–D8,
   five design rules, the verification ladder, the build order), `docs/BUG-LEDGER.md` (21 bug
   classes), `references/` (artifact skeletons, profiles), `prompts/` (prompt patterns).
2. **The user's architecture doc** `python_agent_dashboard_architecture (2).md`: Prefect +
   MLflow + SQLite `monitor.db` + Reflex, a pydantic `TaskSpec`, one `workflow_run_id` joining
   every subsystem, a task lifecycle, a page list, a `workflow/ observability/ dashboard/` layout.

The template merges them: the user's stack is the runtime, freeze-and-swap's doctrine is the set
of rules the runtime enforces **by code**. The name says the thesis: code steers, models write.

## Decisions made by the user

| Topic | Decision |
|---|---|
| Form | Standalone Python repo at `~/Documents/Agents_design/code_steer_model_write/` (new git repo). Package `code_steer_model_write`, CLI `csmw` (alias of the long name) |
| Stack | Prefect (orchestration), MLflow local `sqlite:///mlflow.db` (traces, evals, experiments), SQLite `monitor.db` (UI-only state), Reflex (dashboard), Pydantic v2 |
| LLM access | Four backends behind one `ask()`: Anthropic SDK, Claude Agent SDK, LiteLLM, `claude -p` / `codex exec` CLI; plus a fake backend |
| Schemas | Pydantic v2 is the single owner of every LLM output shape |
| Code checks | ruff + pyright + pytest on agent-written code, returned to the author as refusals; SKIPPED and recorded when a tool is missing. Python only in v1 |
| Recipes | code-builder (built first, the "proven" one), then debate/eval, research/analysis, tool-using assistant |
| Scope | General agentic workflows, not only hackathons |

## 1. Backbone / workflow design

The backbone is a **coded driver** whose steps are **generated from state on disk**. Models fill
schemas; code decides what happens next, whether it counts, and writes every file. (RELIABILITY D2)

```
TaskSpec (recipe + params + roles + mode + rounds)
   │  csmw validate → DRAFT→VALIDATED (pydantic + profile gate + doctor)
   ▼
Driver.next()  ── derives pending Steps from runs/<id>/ files  ──►  Step
   │                                                              AUTHOR: ask(prompt, schema) → artifact JSON
   │                                                              RUN:    subprocess (tests, lint, null run)
   │                                                              CHECK:  code checks (cites, sets, words)
   │                                                              JUDGE:  ask(Findings) on a frozen view
   │                                                              GATE:   ask file → decision file (human or auto)
   ▼
Driver.done(key)  ── proven by a deliverable file, never by the record alone
   │  every step: events.jsonl (owner) → MLflow span (mirror) → dashboard (view)
   ▼
[] and no open gate = COMPLETED | HALTED_HONESTLY | BROKE   (process signal, D4)
verification verdicts per tier code/AI/human                 (product signal, D4)
```

Rules the backbone enforces (each is code, with a walk leg proving it):

- **Models read markdown, write JSON.** Every input to any model is markdown that code
  rendered from JSON artifacts and inlined into the prompt; every output from any model is one
  JSON object constrained by a pydantic schema. No model ever receives raw JSON, a file path
  to read, or another model's prose; no model ever writes a file. Passing model A's output to
  model B is always: A's JSON → validated → stored → `render_md()` by code → inlined into B's
  prompt. Detail in §2a. (RELIABILITY D1c "render, don't re-read"; D8)
- **One owner per fact** (BUG-LEDGER class 1). Owners table in §6.
- **Effect after acceptance**: `ask()` never writes an artifact; a step records only after every
  check passes; writes are stage → check → `os.replace`.
- **Re-ask loop**: schema or check refusal is re-asked with the exact problems AND the refused
  answer, max 6, stop early when a problem set repeats any earlier attempt. Nothing recorded from
  a refused answer.
- **Freeze-and-swap**: the author of an artifact never checks it; the checker gets a frozen,
  rendered view; `TaskSpec.swaps` pairs (author_role, checker_role) and a validator requires
  different vendors when `require_cross_vendor`.
- **Graded verdicts**: findings carry `severity` blocking/major/minor; routing is a threshold.
- **Review rounds**: cap set once; round N packet = current artifact + every prior round
  verbatim + code-computed diff; convergence computed by code; round cap+1 is a closing read
  nobody answers; unresolved findings are **carried** into the report, never hidden; a
  twice-rejected re-raise escalates to a scope question for the human.
- **Empty-set guard**: a step with nothing to do is never issued (zero findings → no arbitration;
  zero questions → no gate).
- **Mode dial** detailed/light/auto; unasked questions take the default and are recorded
  `answered_by=auto, flagged=True`; reviewers get flagged decisions under "attack these first".
- **Two-kinds gate test**: a gate exists only to gather a value only the human has (input, early)
  or a judgment only the human can make (exception-triggered). Everything else is a notification.
- **No tools unless the step declares `needs_tools`**; enforced by the backend call, not prose.
- **Honest exit codes** everywhere: 0 done, 1 record/warnings, 2 refusal/halt.
- **Halts are reports** (`halt.json`: step, command, reason, last 6 stream facts); Resume
  re-derives steps from disk and reopens any step whose deliverable is missing; `undo --key`
  forgets a half-done step.
- **Locking**: `state.json` written only under `flock`; parallel independent steps allowed.
- **Offline walk**: `FAKE_MODELS=1` plus knobs (`FAKE_REFUSE`, `FAKE_FINDINGS`, `FAKE_CLOSING`,
  `FAKE_REVISE`, `FAKE_VERDICT`, `FAKE_STALL`, `FAKE_SCOPE`, `FAKE_TOOLLESS_VIOLATION`) so every
  branch a live run can enter is walked in seconds with zero tokens.

Prefect's role: `@flow drive(run_dir)` loops `Driver.next()`; each step is a `@task` named by
its key; independent steps `.submit`; cancellation hook kills process groups and writes
CANCELLED. `csmw drive --no-prefect` runs the same loop in-process (the walk uses it).
`state.json` owns status; Prefect state is a pushed view, never the driver's input.

## 2. JSON schemas

`spec/base.py` — `Artifact(BaseModel, extra="forbid")` is the one owner of a shape and derives:

| derived | how | used by |
|---|---|---|
| `wire_schema()` | `model_json_schema()` + post-pass: all keys required, `additionalProperties: false`, `Optional` → type union, numeric ranges / string lengths **stripped** (kept in validators; grammar backends reject them inconsistently), `SkipJsonSchema` fields (code-assigned ids) removed | every backend |
| `template()` | empty skeleton | pasted into the prompt |
| `guide()` | field table from `Field(description=, examples=)` | pasted into the prompt |
| `model_validate` | pydantic, always run even on grammar backends | `ask()` |
| `semantic_problems(ctx)` | override per artifact: cites resolve, set differences, banned words | `ask()` checks |
| fake instance | from `Field(examples=)` + recipe fakers | fake backend |

Per-backend schema enforcement (from `docs/PLAN-constrained-decoding.md` and the 2026 SDKs):

| backend | mechanism | mode |
|---|---|---|
| Anthropic SDK | `output_config.format = {type: json_schema, schema}`; `tools=[]`; `stop_reason == refusal` → `no_output` with reason | grammar |
| Claude Agent SDK | `ClaudeAgentOptions(output_format=..., allowed_tools=[], mcp_servers={}, setting_sources=[], max_turns=3)`; result `structured_output` | tool boundary |
| LiteLLM | `response_format={type: json_schema, strict: true}`; provider may ignore → validation refusal + re-ask | validate only |
| `codex exec` | `--json --output-schema schema.json -o out.json`, shell tool disabled, `--ignore-user-config`, `-C <empty tmp dir>` | grammar |
| `claude -p` | `--output-format stream-json --json-schema '<wire>' --tools "" --max-turns 3 --mcp-config '{}' --setting-sources ""` | tool boundary |
| fake | schema-valid instance + knobs | grammar |

Design rules for shapes (RELIABILITY D-design-1/3): an element is its own JSON element iff
something downstream can cite it, check it, or accept/reject it alone; add a field
(`cites`, `implements`, `class`) wherever it turns a judgment into a set difference.
**Ids** (`ids.py`, decided once, globally): `C-` contract clause, `A-` algorithm step, `P-`
property, `F-` finding, `Q-` question, `D-` decision, `S-` step, `V-` version, `R-` ruling.
Ids are assigned by code on ingest, never by a model, never renumbered, and rendered to words
before a human reads them.

**Code is never wrapped in JSON.** For the code-builder: the *contract* is JSON (typed
`params`/`returns`, id'd clauses, algorithm steps with `implements[]`), the code is *files*,
the model's *envelope* claim (`files`, `units`, `steps_covered`) is JSON checked against the
ownership diff, id comments (`# A-003 -> C-023`) tie them together, and the test *manifest*
(`{P-005: tests/test_x.py::test_fit}`) makes property→test a lookup, not a substring match.

Belt-and-braces: `scripts/schema_check.py` re-validates a live answer with the `jsonschema`
library against the generated wire schema (optional dependency, SKIPPED when absent).

## 2a. JSON → markdown converters (the input side)

The output side is the schema; the input side is the renderer. `artifacts/render.py` is the
one place JSON becomes text a model reads.

| piece | what it does |
|---|---|
| `Artifact.render_md(audience="model" \| "human") -> str` | every artifact model implements it; the base class provides a generic renderer (scalars as `key: value`, lists of models as tables, nested models as `###` sections) and each artifact overrides only where a table reads better |
| `render.py: render(obj, audience) -> str` | dispatch on type; refuses an object that is not an `Artifact` (a dict or a raw JSON string never reaches a prompt) |
| views | a renderer can drop fields for a role: the contract's `algorithm` section is removed for the test author (the test-visible view); the freeze hashes both views |
| ids | `audience="model"`: ids kept, because the model must cite them; `audience="human"`: ids resolved to words plus the id in parentheses, so a raw `C-051` never reaches a gate form or a report on its own |
| packets | `ReviewLoop.packet()` renders the current artifact, then every prior round's findings and arbitrations verbatim, then the code-computed diff, each under its own heading |
| prompt keys | `prompts.fill()` accepts only strings; a key ending `_MD` must come from `render()`; `fill` refuses a value that parses as JSON or contains a `{"` run, so raw JSON cannot be pasted by mistake |
| no re-reads | no prompt contains a file path for the model to open; `dry_run` fails on a prompt with an unrendered `*_PATH` key |
| determinism | rendering is pure: same JSON → same markdown → same prompt hash; the walk asserts prompt hashes are stable across two runs |
| tests | one snapshot test per artifact renderer, both audiences, checked in under `tests/snapshots/` |

Walk assertions for this rule: every `call.started` event records the prompt's `template_hash`
and the artifact keys it rendered; the fake backend refuses a prompt whose inlined inputs
contain raw JSON; every `artifact.written` is preceded by a validated `call.final`.

## 3. Code and function verification

The verification ladder (RELIABILITY D-design-5): code checks first (cheapest, most reliable),
AI judges only where no field can answer, humans only at stakes. For agent-written code:

| check | tool | when | on failure |
|---|---|---|---|
| format | `ruff format` | at write, before hashing | author's problem, refusal |
| lint | `ruff check` (rule set owned by `config.py`, never the project's pyproject) | after every implementer / test-author / fixer call | findings → refusal with the exact lines |
| type check | `pyright` on `src/` | after implement | refusal |
| compile | `py_compile` | every file written | refusal |
| ownership | `git diff --name-only` in the worktree vs the task row's `writes[]` | after every author step | refusal (wrote outside its files) |
| envelope | `steps_covered == row.required_steps`; `files == diff` | after implement | refusal (set difference) |
| id comments | every step id in the row appears as a comment in the file | after implement | refusal |
| null run | generated zero-value stub from the contract's typed units; every test must **fail** against it | after test author | vacuous test → refusal to the test author |
| tests | `pytest` with `--json-report` (or `-p` plugin) → `results.json`, 3 repeats for nondeterminism, manifest lookup per property | verification run | failing property → triage, never a refusal |
| imports | tests import only from the contract's public surface | after test author | refusal |
| isolation | each author writes in its own **git worktree**; the test author's worktree has `src/` deleted and sees only the test-visible contract (algorithm section stripped) | build | walk leg asserts the worktree state |
| missing tool | ruff / pyright absent | doctor warns; the step records `SKIPPED` per step and the report says so | never a silent pass |

Triage after a failing property is two ordered questions ruled by fresh sessions with no write
access: Q1 "is the test wrong?" (the code's side), then Q2 "contract, algorithm or
implementation?" (the test's side). Verdicts are an enum; an ambiguity is carried as a result.

Deferred beyond v1: Docker sandboxing (worktree + tool-less models is the v1 isolation),
mutation testing, Hypothesis property tests, TypeScript check profile.

## 4. Package layout

```
code_steer_model_write/                 repo root (git)
├── code_steer_model_write/             the package (console scripts: csmw, code_steer_model_write)
│   ├── config.py                       Settings (pydantic-settings, .env): mode, rounds, RE_ASK_MAX=6,
│   │                                   MAX_TURNS=3, stall seconds, role→backend/model/effort, ruff rule set
│   ├── ids.py                          id namespaces, assigned by code
│   ├── spec/                           base.py (Artifact), findings.py, decisions.py, events.py, task.py (TaskSpec/AgentSpec/EvaluationSpec/RoleSpec)
│   ├── prompts.py                      load prompts/<recipe>/<stage>.md, fill {{KEY}}, refuse unfilled/unused key, banned-word scan
│   ├── backends/                       base.py (Backend protocol, CallSpec, CallResult, Usage, Capabilities),
│   │                                   anthropic_api.py, agent_sdk.py, litellm_backend.py, cli.py (claude/codex),
│   │                                   streams.py (facts, watchdog, scope kill), fake.py, registry.py
│   ├── ask.py                          ask(prompt, schema, role, checks, tools) → Accepted | Refused; re-ask loop; events + MLflow span from one call site
│   ├── artifacts/                      store.py (JSON truth, versions, atomic write, snapshot, diff), render.py (the one JSON→markdown
│   │                                   converter: per-artifact render_md, model/human audiences, role views, packet rendering),
│   │                                   brief.py ledger.py decisions.py plan.py contract.py vspec.py tasks.py findings.py rulings.py report.py
│   ├── events.py                       events.jsonl appender (locked) + MLflow bridge
│   ├── state/                          run.py (RunState, RunStatus, Outcome, RunPaths), lock.py
│   ├── driver/                         steps.py (Step, StepKind, StepGenerator), driver.py (next/done/undo/dry_run/resume),
│   │                                   runner.py (in-process loop, thread pool), halt.py
│   ├── checks/                         base.py (Check, Problem), code.py (cites_resolve, banned_words, set_difference, empty_set_guard,
│   │                                   length_rules), judge.py (AI judge → Verdict), pycheck.py (ruff/pyright/py_compile runners),
│   │                                   ownership.py, nullimpl.py, runtests.py (pytest → results.json + manifest)
│   ├── gates/gate.py                   Gate, Question, Decision; ask/decision files; mode dial; auto-answer flagged
│   ├── review/rounds.py                ReviewLoop: ingest, packet, converged, carried, closing read, escalation
│   ├── recipes/                        base.py (RecipeSpec, StageSpec, GateSpec, EvalSpec, CheckKind, Recipe protocol), registry.py,
│   │                                   code_builder/ debate/ research/ tool_assistant/ (each: spec.py steps.py checks.py evals.py)
│   ├── evals/                          MLflow scorer registry (code scorers + AI scorers)
│   ├── tools/                          allowlist, action log, typed tool functions, fake HTTP/search tools
│   ├── workflow/                       flows.py (Prefect wrapper), task_spec.py, lifecycle.py
│   ├── observability/                  mlflow_bridge.py, monitor_db.py
│   ├── figure.py                       the workflow figure: RecipeSpec → FigureSpec → SVG, dark and light (§7b)
│   ├── settings_form.py                FIELDS: the one settings schema the start page, the CLI and prefs.json derive from (§7c)
│   ├── worktree.py                     git worktree per author, cleanup, clean-tree gate
│   ├── doctor.py                       preflight; --fake skips vendor probes; --deep runs one walk leg; exit 0/1/2
│   ├── walk.py                         offline walk legs, asserts on events.jsonl
│   └── cli.py                          csmw doctor|validate|run|drive|next|done|undo|resume|dry-run|walk|dash|evals|new-recipe|gate
├── prompts/<recipe>/<stage>.md         code-filled templates
├── fixtures/<recipe>/<stage>[.<variant>].json   fake answers, one variant per branch
├── dashboard/                          app.py, theme.py (every colour/size/spacing token, §7a), state/, views/ (runs, run, new_task, evals), components/
├── examples/<recipe>/task.json         demo TaskSpecs (code-builder: the slug library)
├── docs/                               PLAN (this plan), QUICKSTART, HACKATHON-30MIN, ADD-A-RECIPE, DASHBOARD, DASHBOARD-DESIGN (§7a),
│                                       RELIABILITY (imported), BUG-LEDGER (classes only, empty rows)
├── scripts/                            run.sh (full offline suite), schema_check.py, smoke_live.py
├── tests/                              selftests per module
├── copier.yml  justfile  .env.example  pyproject.toml  requirements.txt  CLAUDE.md  README.md
└── runs/<run_id>/                      state.json events.jsonl halt.json decisions.json artifacts/<key>/vNNN.json
                                        review/<loop>/round-N.*.json gates/<id>.ask.json|.decision.json streams/ worktrees/
```

Key signatures (abridged; full shapes in the design agents' reports, reproduced in the module
docstrings when built):

```python
def ask(prompt: FilledPrompt, schema: type[A], *, role: str, ctx: CallContext,
        checks: Sequence[Check[A]] = (), tools: Sequence[ToolDef] = ()) -> Accepted[A] | Refused

class Backend(Protocol):
    name: str
    def capabilities(self) -> Capabilities: ...
    def complete(self, call: CallSpec, on_fact: Callable[[Fact], None]) -> CallResult: ...

class Step(BaseModel):
    key: str; kind: StepKind; phase: str; after: list[str] = []
    prompt: str | None; schema: str | None; role: str | None; sets: dict[str, str] = {}
    checks: list[str] = []; command: list[str] | None; gate: str | None
    writes: list[str] = []; needs_tools: bool = False

class Driver:
    def next(self) -> list[Step]; def done(self, key: str) -> None
    def undo(self, key: str) -> None; def dry_run(self) -> list[Step]

class RecipeSpec(BaseModel):
    name: str; version: str; status: Literal["proven", "unproven"]; assumes: list[str]
    params_model: type[BaseModel]; roles: list[AgentSpec]; stages: list[StageSpec]
    gates: list[GateSpec]; evals: list[EvalSpec]; required_checks: set[CheckKind]
    banned_words: dict[str, list[str]]; fixtures: Path; demo: DemoSpec
```

`TaskSpec` keeps the user's fields and adds `recipe`, `roles: dict[str, RoleSpec]`,
`swaps`, `mode`, `rounds`, `require_cross_vendor`. `max_cost_usd` is replaced by token
budgets (dollars are never stored, see §6).

## 5. Recipes

A recipe is a Python package: declarative parts are pydantic (validated at import), the step
generator is code deriving steps from files. Profiles from freeze-and-swap become
`required_checks`, enforced by a code gate at VALIDATED; each recipe carries an honest
`status: proven|unproven` header.

### 5.1 Code-builder — built first, the proven one (port of freeze-and-swap)

A = author model side, B = checker side (different vendor). C = code check, AI = judge, H = human.

| # | stage | author | checker | artifact | checks | gate |
|---|---|---|---|---|---|---|
| 1 | brief + assumptions ledger | code + human | — | Brief, AssumptionsLedger | C schema, ≤30 rows, every row has basis | **G1 input, always**: batch-confirm assumptions by exception, pre-filled |
| 2 | plan | A | B review rounds, A arbitrates | Plan (blocks, boundaries, rejected, risks, not-decided) | C blocks have in/out; AI review with anti-fatigue clause | — |
| 3 | contract | A | B rounds + fresh-session audit | Contract (vocabulary, interface with typed units, constants, invariants+measurement, negative scope, failure policy, tolerances, algorithm) | C profile clause kinds present, banned verbs, cites resolve, ids monotonic; AI review | **G2 judgment, always**: blocks confirmed from a generated render; freeze (hash full + test-visible view) runs by code after |
| 4 | tolerances | B generates questions, code renders | human | Decisions §risk | C a number is a number | G3 input, only if UNDECIDED slots exist |
| 5 | verification spec | B (test-visible view only) | A coverage review, B arbitrates | VerificationSpec (properties cite clauses, class 1–7, observe, falsifies) | C every clause cited or n/a; AI coverage; CONTRACT-GAP routes to human | G4 judgment, exception (carried findings) |
| 6 | tasks | code | — | Tasks (id, owner, writes, covers, depends, done_when) | C one owner per file | — |
| 7 | tests | B, worktree with `src/` deleted | code | files + manifest | C ruff, py_compile, imports, ownership, **null run must fail** | — |
| 8 | implement | A, one call per file | code | files + envelope | C ruff, pyright, py_compile, ownership, envelope set-difference, id comments | — |
| 9 | verify | code | — | results.json (3 repeats) | C | — |
| 10 | triage | A fresh (Q1 test wrong?) then B fresh (Q2) | code | Rulings (enum verdict, reproduction n/m) | C verdict enum, argument length | G5 judgment, exception: ambiguity |
| 11 | fix loop | ruled side | code | files | same as 7/8 | — |
| 12 | report | code | — | Report (carried + waste table) | C | notification |

Evals to MLflow: `pass_rate`, `null_fail_rate`, `carried_findings`, `rounds_to_converge`,
`refused_answers`, `tokens_per_side`. Demo: the slug library built by two models on small
models, tests that fail the null stub, the page showing the rail, gates and verdict.

### 5.2 The other three (built after, `status: unproven` until one clean live pass)

| recipe | stages (author → checker) | code checks that make it honest | gates |
|---|---|---|---|
| debate / evaluation | brief → hypotheses (A, B reviews) → support (A) → challenge (B) → arbitrate (A) → judge (B fresh, rubric) → report | every argument cites; hedge banned words; arbitration engages (12+ words); scores in range, every rubric row scored | G1 input always (rubric weights pre-filled); G2 judgment on unclear verdict or carried blocking |
| research / analysis | brief → search (tool, code) → read per source (A) → synthesize (A, B reviews) → critique (B) → revise (A) → report with bibliography | every quote found verbatim in the source; every claim → note → source; domain allowlist; dedupe | G1 input always; G2 judgment if a blocking finding survives |
| tool-using assistant | brief + tool allowlist → plan actions (A) → execute reads (code) → **confirm writes (H)** → execute writes (code, idempotency key) → answer (A, B reviews) → report + action log | tool ∈ allowlist, args validate against the tool schema, answer cites log rows, `writes_confirmed_ratio == 1.0` | G1 input always; G2 judgment always for writes, batched in one form |

Every recipe ships fixtures for the fake backend with one variant per branch, an example
TaskSpec, prompts, and evals.

## 6. Ownership of facts (no second owner)

| fact | owner | derived views |
|---|---|---|
| run status / outcome | `runs/<id>/state.json` | Prefect flow state (pushed), `monitor.db.runs` index, dashboard |
| step status | `state.json.steps` + deliverable files | Prefect task states, dashboard rail |
| tokens | `events.jsonl` `call.usage` | MLflow span attributes, dashboard clock |
| cost USD | **not stored**; `config.cost()` on read from a price table, blank when unknown | dashboard (tokens are the honest measure) |
| current activity / progress message | last `step.started` / `call.*` / `progress` event + heartbeat age | dashboard NOW line and agent cards (`agent_state` from the user's doc becomes a derived view, not a table the runtime writes) |
| decisions | `decisions.json` (gate decision files folded in by the driver) | reports, reviewer packets |
| findings + statuses | `review/<loop>/round-N.findings.json`, append-only | `finding.*` events, MLflow metrics, report |
| artifacts | `artifacts/<key>/vNNN.json` | markdown renders, MLflow artifacts copied at step done |
| shape of every model output | the pydantic class | template, guide, wire schema, validator, fake |
| gate content | `gates/<id>.ask.json` | page form, `csmw gate --tty`, auto-answerer (one record, all derive) |
| halt | `halt.json` | `halt` event, dashboard |
| budgets, mode semantics, re-ask cap | `config.py` | prompt sentences, docs, walk probes |
| UI-only state | `monitor.db`: `runs` index, `ui_layout`, selected run | dashboard only |

MLflow is a sink; nothing the driver needs is read back from it. Prefect is a scheduler,
cancel channel and view.

## 7. Dashboard (Reflex)

Four signals first (D-design-4): **where** (stage rail) · **healthy** (process badge
completed / halted honestly / broke, plus product badge code n/m · AI n/m · human n/m) ·
**time remaining** (elapsed, ETA once history exists, else "steps") · **cost** (tokens per side).

User's nine pages → four: **Runs** (list, a tab per live run), **Run** (the four-zone page),
**New Task** (recipe picker + auto-form from `params_model.model_json_schema()` + budgets +
mode + per-role model), **Evals** (Experiments + Evaluations merged, reads MLflow). Agents,
Traces, Artifacts, Costs become zones or disclosures of Run.

Run page zones: (1) constant header: identity line, stage rail, clock, NOW line with
Stop/Resume, wrong-ness chips (carried findings, failing checks, halts, refused-re-asked, API
retries; each jumps to evidence); (2) selected stage panel with the **gate form always
inline, never behind a disclosure**; (3) stage evidence: agent runs, arbitrations, artifacts as
markdown + raw JSON, accordions with stable ids; (4) run evidence: swimlane, cumulative tokens
chart, event log with stage filter, report.

Mechanics learned from the BUG-LEDGER: timer stops at `completed_at`; a background poller
recomputes `refresh_hash` over every live file in the run dir and updates state only on change;
picked stage and open accordion ids in `SessionStorage` keyed by run; only a click sets a pick
and a pick on the running stage rides with the run. Gate submit writes
`gates/<id>.decision.json` via temp + `os.replace`; the driver's wait watches that path; auto
mode writes the same file with `source=auto`.

`csmw dash selfcheck --run R` builds the page state from disk without a browser and asserts:
header fields non-empty, NOW line equals the last event, chip counts equal recounts from
events, gate form present iff an ask file has no decision, timer frozen when completed, every
accordion has an id, refresh hash covers every writable file in the run dir, the component tree
builds. Exit 0/1/2. Binds `127.0.0.1` only.

## 7a. Dashboard design language

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

## 7c. The start page (run settings)

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
7. (Revised 2026-09-03 by the user: a **dropdown** per setting, not a chip row; a model row's options are the provider's catalogue for the chosen backend, an effort row's options are the chosen model's supported efforts, discovered dynamically where the CLI can say — `codex debug models` — and from a maintained table where it cannot — Claude Code; the Anthropic Models API when an API key works. `code_steer_model_write/providers/`.) Original text: a single row of option chips, one row per setting, single-select. A chip is mono text
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

## 7b. The workflow figure (generated per project, first thing)

Every project gets a figure of how its workflow operates, in the style of freeze-and-swap's
`docs/media/pipeline-dark.svg` (the screenshot: the dark variant on a light ground, which is
what makes the boxes read as glass). It is **generated by code from the RecipeSpec**
(`csmw figure <recipe|task.json> --theme dark|light -o docs/media/workflow.svg`), so the
figure can never drift from the workflow (rule 4). It is produced at step 0 of a project,
embedded in the README with `<picture>` (dark for `prefers-color-scheme: dark`, light
otherwise), and shown on the dashboard's Start panel. Module: `code_steer_model_write/figure.py`;
tokens shared with `dashboard/theme.py`.

**Source of truth.** `StageSpec` gains `emoji`, `hue` and `figure: FigurePhrases` (the author
phrase, the checker phrase, the rounds label, an optional second line). `GateSpec` supplies the
human box text ("You confirm the blocks"). Freezes, merges, null runs and the output box come
from `CheckKind`/step kinds. A `FigureSpec` pydantic model is derived from the recipe and
rendered to SVG by a pure function; a snapshot test pins the code-builder recipe's output.

**Canvas.** `viewBox 0 0 1000 H`, H computed from the rows. Font stack
`Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif`. Dark: no background rect,
the host's ground shows through (comment in the SVG says so). Light: a white rect `rx 22`.
Everything is centred on x = 500.

**Legend, top right** (x 650 and 770, rows 26px apart from y 24): swatches 26×18 `rx 6` for
each actor role, then two line samples 34px long: solid = "a step", dashed `7 6` = "review
rounds". Legend text 15px, muted (`#9aa4ae` dark / `#8a8a8a` light).

**Colour tokens** (dark theme; light theme uses the flat fills in `pipeline.svg`: `#fbe1cc`,
`#d4efe8`, `#fbf0c4`, `#e6e2f5`, `#dbe3ee`, band `#f2f4f7`, text `#4b4b4b`):

| role | rgb | box fill α | box stroke α | glyph / text colour |
|---|---|---|---|---|
| model A (Claude) | 219,109,40 | 0.14 | 0.70 | `✳` in `#db6d28` |
| model B (Codex) | 47,163,154 | 0.14 | 0.70 | `☘` in `#2fa39a` |
| you (human) | 212,167,44 | 0.14 | 0.70 | no glyph |
| both | 163,113,247 | 0.13 | 0.65 | no glyph |
| code, no model | 139,148,158 | 0.12–0.14 | 0.55–0.60 | no glyph |
| freeze (emphasised code box) | 139,148,158 fill 0.14 | stroke `rgba(201,209,217,0.8)` 1.8px | text `#ffffff` weight 700 |

Stage hues, band fill α 0.07 (0.06 for tall bands), band stroke α 0.5, label text colour:

| n | hue rgb | label colour | emoji |
|---|---|---|---|
| 0 | 77,143,220 (blue) | `#6ea6e8` | 🗺 |
| 1 | 187,128,9 (gold) | `#d69a26` | 📜 |
| 2 | 154,110,224 (violet) | `#b28ae8` | 🧪 |
| 3 | 47,163,154 (teal) | `#43bdb2` | 🔨 |
| 4 | 208,74,69 (red) | `#e06661` | 🚑 |

Further stages cycle the palette module's hues; each recipe picks its emoji per stage.

**Geometry.**
- Start box "Your brief": 220×50 `rx 14`, slate glass (fill α 0.12, stroke α 0.55, 1.5px),
  text 19px weight 600 light (`#e6edf3`).
- Stage band: x 60, width 880, `rx 18`, stroke 1.5px. Height 118 for one row of boxes, 130 for a
  two-line box, 214 for two rows plus a merge box. Label at (82, top+28): 15px, weight 600,
  `letter-spacing 1.5`, uppercase, `<emoji> N · NAME`, optional ` — QUALIFIER` (`3 · BUILD — TWO
  ISOLATED WORKTREES`).
- Actor box: 280×58 `rx 14` when two across (x 130 and 590); 258×58 when three across (x 88,
  371, 654) with text 18px; 340×72 when two-line (x 100 and 560, lines at ±12.4px). Text 19px
  weight 600 `#e6edf3`, centred, `dominant-baseline central`, a `<tspan>` glyph in the actor
  colour before the phrase. Phrases are `<Actor> <verb phrase>`: "Claude writes the plan",
  "Codex attacks it", "Codex writes the tests / without the source".
- Human box: gold glass, 280×54 or 320×54, centred, "You confirm the <thing>".
- Freeze box: 400×54, bold white, "Freeze — the contract is hashed".
- Code box: slate, 340×54, "merge · null run · real run".
- Both box: violet, 700×72, two lines: "Each failure is ruled on by the side that did not write
  it" / "fix · re-run".
- Output box: 420×50, slate α 0.12/0.55, weight 500, "src · tests · REPORT.md · PAGE.html".
- Boxes inside a band start 40px below the band top.

**Arrows.** Stroke `#c9d1d9` dark (`#9a9a9a` light), 2px (2.5 light), round caps, arrowhead
marker 7×7 triangle (`refX 9`). Vertical connectors are 34px long with a 2px gap at each end,
so band-to-band spacing is 36px. Review rounds: a horizontal dashed `7 6` line between the
author and checker boxes with a marker at both ends and an italic 15px muted label centred
above it ("rounds", "rounds + a fresh audit"). Sequence within a band: short solid 17px arrows
between boxes. Fan-in: two diagonal lines from the two boxes' bottom centres to the merge box's
top edge.

**Footnote.** Five centred italic 16px lines in `#8b949e` (`#8a8a8a` light), 24px leading,
starting 14px under the output box. The text is the charter in prose; the template's default
lines: "Every model box is a fresh agent — a new, independent context given only the files the
toolchain hands it; / a box's later review rounds are the one thing that continues its own
thread. / Slate boxes and every arrow are code: the driver sequences the run — a workflow
enforced by code, not by agents. / An agent's only power is filling in a JSON schema, enforced
at generation by constrained decoding — / no file reads, no shell, no edits, no tools: the agent
answers; code writes every file and decides every step." (Line two changes to "every round is
handed the full trajectory by code" since v1 has no thread resume.)

**Verification.** `tests/test_figure.py`: the code-builder recipe renders to an SVG structurally
equal to the reference (same element count, texts, colours, positions within 1px); every colour
in the output is a token; both themes render; the README embed references both files.

## 8. Developer experience

- **Scaffold**: `copier copy gh:<user>/code_steer_model_write my-project` (copier over
  cookiecutter so `copier update` pulls template fixes into a live project). Questions: project
  name, first recipe, default backend, model A / model B. Post-hook runs `just doctor`.
- **Settings**: `.env` via pydantic-settings: `CSMW_BACKEND`, `CSMW_MODEL_A/B`,
  `ANTHROPIC_API_KEY`, LiteLLM vars, `CSMW_MODE`, `CSMW_ROUNDS`, `FAKE_MODELS`,
  `MLFLOW_TRACKING_URI=sqlite:///mlflow.db`, `CSMW_RUNS_DIR`.
- **justfile**: `doctor` · `walk [recipe|all]` · `run task.json` · `resume id` · `dash` ·
  `selfcheck id` · `test` (pytest + walk all + selfcheck on the walk's run) · `smoke <backend>` ·
  `new-recipe name` · `evals id` · `dry-run task.json`.
- **CLAUDE.md**: the 14 universal rules from §0 verbatim, then the working rules Claude Code
  follows when extending the template: `just walk` before any live run; never edit the package
  while a run lives; classify a bug against the BUG-LEDGER classes before fixing, fix the
  class; raw ids never reach a human; add a recipe by `spec.py` → fixtures → prompts →
  `just walk <name>` green before any prompt tuning; when a check fails live, first ask whether
  the guide could have produced anything else; never add a dashboard signal that does not
  answer where / healthy / remaining / cost.
- **docs/HACKATHON-30MIN.md**: 0–3 min scaffold + one key; 3–5 doctor + walk; 5–8 dash and
  click the chips; 8–15 edit the example TaskSpec, run light mode on cheap models; 15–25
  answer G1 on the page, watch the rail; 25–30 evals, decide what to change (params, prompts,
  or a copied recipe).
- **docs/ADD-A-RECIPE.md**: the eight steps from `just new-recipe` to flipping
  `status: proven` after one clean live pass.
- **Prompt conventions** (`prompts/`): role + output contract in the first three lines; tool
  denial stated as fact; a "what you do not have" section justifying absences; reviewer
  criteria checklist embedded; anti-fatigue clause; test author told a test passing against the
  null is vacuous; a code-written "how to answer" block appended from the template and guide.

## 9. Build order (code-builder first)

Follows RELIABILITY "Build order": workflow as data → checks → prompts → tools → streams →
dashboard. Every stage ends with the offline walk green.

0. **Save the plan, init the repo** — `git init` the new folder; write `docs/PLAN.md` (this
   plan verbatim), `README.md` opening with the 14 rules, `CLAUDE.md` with the 14 rules plus
   the working rules, `pyproject.toml`, `requirements.txt`, `.env.example`; first commit. No
   package code yet.
1. **Spec + store + render + events + lock** — `spec/base` (schema post-pass), `ids`,
   `config`, `events.py`, `artifacts/store`, `artifacts/render` (JSON→markdown, both
   audiences, role views), `state/lock`. Unit tests: post-pass dict-identical, atomic write
   survives a crash between stage and replace, snapshot/restore, diff, renderer snapshots per
   artifact, `fill` refuses raw JSON.
2. **Prompts + fake backend + ask()** — re-ask loop offline: recover at n+1, no-progress stop,
   cap 6, nothing written on refusal, unfilled/unused key refusal.
3. **Driver** — `state/run`, `driver/*`, `cli` start/next/done/undo/dry-run/resume on a two-step
   toy recipe; resume and undo tests; missing deliverable reopens a step.
4. **Checks, gates, decisions, mode dial** — walk legs: gate answered by file, light, auto
   (flagged), empty-set guard.
5. **Review rounds** — legs: approve at once, findings → arbitration, refused arbitration, cap
   carry, closing read converged vs carried, twice-rejected escalation.
6. **Code-builder artifacts and code checks** — contract/vspec/tasks models, `pycheck`,
   `ownership`, `nullimpl`, `runtests` + manifest, `worktree.py`. Legs: null run rejects a
   vacuous test, ownership refuses an out-of-scope write, SKIPPED recorded without ruff.
7. **Code-builder recipe end to end offline** — all 12 stages with fixtures; every branch
   (refuse, revise, each verdict, ambiguity carried, halt → resume) walked; `scripts/run.sh` is
   the suite. `figure.py` renders the recipe to `docs/media/workflow.svg` (dark and light) and
   the snapshot test pins it; `csmw new-project` runs `csmw figure` as its first output.
8. **Streams + CLI backends** — `streams.py`, watchdog, `claude -p`, `codex exec`; stall/scope/
   error halts proven with the fake writing stream files.
9. **API backends** — Anthropic SDK, Agent SDK, LiteLLM; `smoke_live.py` one real call each,
   asserts conformance, no model-typed ids, tokens in events and MLflow.
10. **Observability + Prefect** — MLflow bridge (spans mirror events), `prefect_flow` with
    cancel hook, `monitor_db` (runs index, layout).
11. **Dashboard** — Runs, Run (four zones), New Task as the start page of §7c (settings_form.FIELDS, prefs.json), Evals; `selfcheck` covers both pages.
12. **Doctor, copier, justfile, docs, CLAUDE.md** — then one **live clean pass** of the
    code-builder on small models → flip `status: proven`.
13. **Debate, research, tool-assistant recipes** — each: spec → fixtures → prompts → walk green
    → live pass.

## 10. Verification

| layer | proof |
|---|---|
| offline walk | `just walk all`: each recipe through every knob branch, asserts on `events.jsonl` (one `finding.decided` per finding per round; no `artifact.written` after a refused attempt; every `call.started` has `tools: []` unless `needs_tools`; every halt carries facts; worktree state at test-author time); zero tokens; SKIPPED is loud |
| selftests | `pytest tests/`: spec post-pass, prompts, store atomicity, driver undo/reopen, rounds convergence table, profile gate refuses a recipe missing a required check, null-impl generation from typed units, manifest lookup |
| dry run | every generated step's prompt fills, schema resolves, argv validates, before any token |
| doctor | python, git, packages, per-role CLI on PATH + version floor + login, API keys, ruff/pyright presence, MLflow db writable; `--fake` skips vendors; `--deep` one leg; exit 0/1/2 |
| dashboard | `csmw dash selfcheck` after every walk; optional Playwright smoke submitting a gate |
| live | `just smoke <backend>` per backend; one end-to-end code-builder run whose traces are read against the acceptance checklist (13 items, adapted from RELIABILITY) |
| evals | scorers run on fixture outputs with known scores in `tests/test_evals.py`; `just evals id` after any run |

## 11. Left out of v1 (and why)

- Stored dollar cost (one backend reports none; a stored total lies). Token budgets instead.
- Docker sandboxing, mutation testing, Hypothesis, TypeScript checks (worktrees + tool-less
  models are the v1 isolation; the rest after a proven pass).
- MCP servers and file-editing agents (tool-bearing Agent SDK runs); tools in v1 are typed code
  functions behind an allowlist.
- Remote Prefect / MLflow servers, Prefect deployments and scheduling (local sqlite covers
  hackathon and single-box use; the id join is the same later).
- Parallel stages inside a recipe beyond independent steps under the lock.
- Codex thread resume (the packet is the record).
- Auto-ETA from history (shows steps until several runs exist).
- Multi-user auth on the dashboard (binds localhost; tunnel for remote).
- Prompt optimisation / DSPy-style tuning (after evals produce curves).

## Reference files (read while building)

- `docs/RELIABILITY.md` — D1–D8, design rules, ladder, build order, smells, acceptance checklist
- `docs/BUG-LEDGER.md` — the 21 classes the walk legs and checks must cover
- `docs/PLAN-constrained-decoding.md` — per-backend schema conformance
- `references/contract-template.md`, `verification-reference.md`, `ledger-reference.md`,
  `triage-reference.md`, `arbitration-reference.md`, `profiles/pipeline-stage.md`
- `prompts/*.md` — prompt patterns to port (`test-author.md`, `arbitrate.md`, `review.md`)
- `python_agent_dashboard_architecture (2).md` — TaskSpec, lifecycle, page list being extended
