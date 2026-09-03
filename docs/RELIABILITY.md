> Imported verbatim from freeze-and-swap (msoliman6, MIT). The template cites its dimensions D1–D8; the plan maps them onto the 14 rules.

# Building reliable agent systems — eight dimensions

A methodology for designing an agent/plugin whose output you can trust. Written
from what worked and what broke while building **freeze-and-swap** (a
contract-first, cross-model build loop). Hand this to anyone about to design a
similar system: it says *what* makes these systems reliable and *how* to
engineer each part, not the specifics of one plugin.

The thesis in one line: **reliability comes from structure. Every place a
choice can be made by code instead of by a model, or expressed as a filled
template instead of free text, is a place a whole class of failure disappears.**

Concrete evidence it is not theory. First live runs: **10 of 12 bugs were a
model choosing a script, a flag, an order, or a loop-exit from prose it had to
remember; 2 were markdown-parsing bugs.** Second round (2026-08-28, ~25 fixes
across a dozen runs), four classes: **template under-specification** (a field
the guide never named, an id prefix the check never pinned, a guide that said
"n/m runs" while the check demanded "n/m", rows written as strings); **signal
taken from exit instead of the stream** (a contract written to the wrong path
exited 0; a stalled review caught only by a hard clock); **cap off-by-one**
(the first check counted as a review round, so the review never ran);
**scope and path drift** (a seed file at the project root, `src.module`
imports). Across both rounds, **no coded check that existed gave a wrong
verdict on what it checked; every escaped defect was a check that did not
exist yet** -- a rule the guide implied but nothing enforced. (Two words are
used for two things here: a *gate* is one of the three decisions the human
takes on the page; a *check* is code refusing an artifact or a step.) Every
dimension below is a response to a failure that actually happened.

---

## The short version

If you read nothing else, this is the whole document in a page.

**Thesis:** reliability comes from structure. Every choice a model makes from
memory, and every free-text handover a program has to parse, is a class of
failure. Remove them by moving choices into code and outputs into templates.

**The eight dimensions**, each a constrained optimization (push to the
constraint, no further):

1. **JSON for every LLM output** — anything a model emits, code included, is a
   predefined template it fills under **constrained decoding at generation**: the
   backend enforces a schema generated from one source (`fs/spec.py`); code writes
   every file from the answer; markdown is a code-rendered view, never the
   source. *Maximize structure.*
2. **A coded driver** — a program decides what happens next and whether it
   counts; the model only writes what a program cannot. *Minimize model
   authority.*
3. **Freeze-and-swap** — whoever makes a thing never checks it; a different
   agent checks a frozen, withheld copy, and grades findings by severity so only
   the fatal ones reach a human. *Minimize judges (shape the schema so code
   catches the rest for free).*
4. **Traces and a minimum-complete dashboard** — every step logs a structured
   event; one screen answers where / healthy / when-done / cost, and separates
   *did the flow run* from *is the output right*. *Minimize what is shown.*
5. **Human-in-the-loop** — the human's attention is the scarcest resource; ask
   only for what only they can decide, batched, at definite points. *Minimize
   interruptions and review volume.*
6. **Convergence** — every multi-round loop (human↔model and model↔model) carries
   the exact prior trajectory (each earlier round's input verbatim + a
   code-computed diff of what changed), never a model summary; refinement builds on
   what actually happened, not an interpretation of it. *Never summarize a round.*
7. **Streams are the signal** — a running model process is read while it runs;
   stall, scope, error and final are facts the loop acts on; exit is the backstop.
   *Never wait for an exit to learn what a stream already said.*
8. **Unstructured tool behaviour is waste** — a model with tools it does not need
   spends them: it orients, re-reads, verifies, writes elsewhere. Every second and
   every token must serve the goal; least randomness, most control; the model is
   free — inventive, even — *inside* the schema, and nowhere else. *Minimize the
   actions a model can take that are not the answer.*

**The three deciders, in order of preference:** code (cheapest and most
reliable, for anything mechanical) → human (for what is irreducibly theirs:
goal, priority, sign-off) → model (for authorship and delegated judgment).

**The ids are the joints.** Every element carries a namespaced id (`C-` clause,
`P-` property, `F-` finding); ids let any step cite one element of another,
across files, and let a leak be a `grep`. Decide the id scheme once, globally,
before any schema.

**Build order:** the workflow (steps + JSON schemas + where the judges go)
first; then skills; then external tools; the dashboard against the trace
throughout.

---

## The eight dimensions of reliability

They are not independent — they reinforce each other, and the interlock section
shows how. But each solves a distinct failure mode, so design each deliberately.

**These are not yet ordered by importance** — the numbering is only for
reference. Ranking them for a given plugin is itself a design act: for a
high-stakes, low-volume tool the human-in-the-loop dimension (D5) may dominate;
for an unattended batch pipeline the coded driver (D2) and traces (D4) do. Order
them against *your* plugin's goal before you spend effort.

Every dimension is a **constrained optimization**, not a binary. The designer's
job is to push hard in one direction *up to* a constraint the plugin's goal
sets — and the whole skill is knowing where that constraint is. Each dimension
below names its objective explicitly; that is the sentence to keep in your head
while designing it.

### D1 — JSON for every LLM output

> **Optimize:** *maximize* the fraction of LLM output that is a filled template,
> pushing toward "everything, even the envelope around code" — **subject to**
> not forcing structure onto genuinely free-form authorship (the prose *inside*
> a field). The direction is always *more structure*; the constraint is that a
> claim, an argument, a line of reasoning stays a string. When in doubt,
> structure it.

**Rule:** anything an LLM emits that is not executable code is a **predefined
JSON template it fills**. The model never invents the shape; it receives a
skeleton and returns it filled. Free text survives only *inside* a field.

**Why:** free text has no validator. A markdown table, a prose paragraph, a
"here is the plan" — nothing can check it, so an error passes silently to the
next stage and compounds. A filled template has required keys, enum fields, and
id references that resolve; a wrong output is rejected *at the boundary*, with
the offending item and key named, before it poisons anything downstream.

**How the shape is enforced: schema-enforced at generation, two mechanisms.**
The schema is handed to the backend with the request and no other shape can be
accepted as the answer. *Codex* (`--output-schema`) and the *Claude API*
(`output_config.format`, every current model, Haiku 4.5 included) constrain the
sampler with a grammar: an invalid token sequence is unreachable. The *Claude
Code harness* — the Agent SDK's `output_format`, what a Claude Code subscription
runs — is **validate-and-refuse at the tool boundary**: the answer is a
`StructuredOutput` tool call, the harness validates its input against the
schema, an invalid call is refused with the reason and the model tries again in
the same call; only a valid call is ever accepted (measured 2026-08-29: the same
holds for a custom SDK tool's `input_schema`; the harness exposes no `strict`
for user schemas). A violation can therefore surface only as *no output* or a
refused turn, never as invalid data — the guarantee is the same on both
mechanisms; the difference is the turns a weak model spends, which the waste
table counts as *refused answers*. Grammar-constrained Claude means the API
path (API billing), kept as a lever if those counts justify it.
Fill-then-validate is gone: there is no author that writes a file and gets
checked afterwards. Every schema is *generated* from `fs/spec.py` — the one
definition of every artifact's shape — and from it alone come the template and
guide the model reads, the strict schema the backend enforces, the validator for
stored files, and the readers' field lists. A composite (an author's whole
answer: `plan_author`, `contract_author`, `arbitrated_*`, `files_author`) is
built by *referencing* the artifact specs; pinning a contract to the plan's
blocks or a file author to its paths is a parameter of the generator, not a
second schema. Code writes every file from the answer, then checks only what a
schema cannot say (a cite resolves, `py_compile`, the null and real runs, the
reason rules, the freeze hash) and re-asks with the exact problems, at most
six times (`fs/config.py RE_ASK_MAX`, the one owner), stopping earlier when a re-ask repeats a
problem set.

**Conformance, measured** (2026-08-29, gpt-5.4-mini / Haiku 4.5; `fs/conformance.py`
re-runs it on a version bump):

| backend | enum | pattern | minItems / maxItems | items.enum | nested required + no extras | type union | minLength |
|---|---|---|---|---|---|---|---|
| Codex `--output-schema` | enforced | enforced | enforced | enforced | enforced | enforced | enforced |
| Claude SDK `output_format` | fail-closed | enforced | enforced | enforced | enforced | enforced | enforced |
| Claude CLI `--json-schema` | fail-closed | enforced | fail-closed | fail-closed | enforced | enforced | fail-closed |

Every keyword the specs use is safe on every backend; the SDK is the Claude
backend of choice. What "fail-closed" buys is the whole point: a wrong shape
cannot reach a file.

**Passing output to the next model is a render step, not a re-read.** When
model A's output feeds model B, the pipeline stores A's JSON as the source of
truth and **renders it to markdown by code** for B to read — because models read
prose better than JSON. JSON is the truth; markdown is a disposable view. The
render is deterministic code, never another model in the middle.

**One idea per element** (see D-design-1 for how to pick the size). If a model
would write five sentences about five things, the schema asks for five keyed
elements, each about one thing — never one string holding all five. A field is a
paragraph only when the paragraph is about exactly one thing.

**Every element carries an id, and the ids form a namespace.** An id lets any
later step point at *one* element an earlier step produced, instead of at the
whole document. A failure ruled at the last step says "ambiguity on `C-060`" and
the report carries *one clause* for the human, with both readings — not "the
contract is unclear." A review
finding cites `C-023`; a property cites `C-023`; the trace draws
`C-023 → P-005 → test → ruling` purely by matching ids across files. Ids are the
**joints between every JSON file in the system**, which is why they are decided
once, globally, before any schema is cut (see Build order).

A *namespace* means each kind of element gets a lettered prefix — `C-` clauses,
`A-` algorithm steps, `P-` properties, `F-` findings, `Q-` decisions — for three
reasons. It is **self-describing** (`A-001` announces it is an algorithm step,
no lookup). It **cannot collide** (clause 1 and property 1 are `C-001` and
`P-001`, never both "1"). And — the reason it is worth doing deliberately — the
**namespace boundary can be a visibility boundary**: here the `A-` ids are
stripped from the checker's view, so the rule "the strip worked" becomes "no
property cites an `A-` id," which is a `grep`. The naming scheme itself makes a
leak detectable. Ids are also **append-only and never reused**, so `C-023` means
the same clause forever, and a citation written early still resolves late.

**Ids are machine-facing only; the human never sees a raw id.** The same ids
that are the joints between files are meaningless to a human — `C-051` is a
pointer, not a thing. So the rule that text crossing to a new reader is a render
step (above) has a sharp corollary for the *human* reader: the render must
**resolve every id to what it names** before the human sees it. A question that
asks "is `C-051` acceptable?" is a leak of the machine tier into the human tier;
rendered correctly it reads "is the width-stability tolerance (§7) acceptable?".
Code does the resolution deterministically — you cannot rely on the
question-authoring model to remember, because it will slip back into ids; the
model may be *told* to phrase for a human, but the render is the guarantee. In
the JSON world this is automatic: the decision's template carries both the
machine `cites: ["C-051"]` and a human gloss, and the human-facing view shows the
gloss. Treat a raw id in anything a human reads as the same class of bug as a raw
stack trace in a user-facing error.

**The template and the validator are the same object.** One schema definition
per artifact does both jobs: it *generates the empty skeleton pasted into the
prompt* and it *validates the reply*. They cannot drift, because they are one
thing. This is what guarantees the model fills a shape it did not invent.

**Ground the model in the schema at decode time, not just at the boundary.** A
validator that rejects a bad reply *after* it is written is the safety net, not
the first line. Modern model CLIs constrain the output to a JSON Schema *as it is
generated* — the model cannot emit a non-conforming shape — and both sides of a
cross-model pipeline take the **same code-generated schema**:

- **the second model (structured output, hard):** `codex exec --output-schema
  <file>` and `claude -p --json-schema <inline>` are the same feature under two
  flags. Hand either the schema `schema.json_schema(artifact)` produced and its
  final message is forced to conform. One generator serves both vendors.
- **the interactive author (seed + fill + check, soft):** an author working with
  file tools has no decode-time hook, so it is handed the *generated skeleton* to
  fill and a `check` step rejects-and-retries. Same schema, enforced at the
  boundary instead of the decoder — the right choice when the artifact is large
  and authored incrementally (a 60-clause contract), where one constrained
  one-shot call is more fragile than fill-then-validate.

Either way the split is the same: **the schema enforces shape, the validator
enforces content.** Bounds a structured-output API will not accept — numeric
ranges, string lengths, "at least one" — stay in `validate()`, not the wire
schema; and a vendor's *strict* mode may demand every key appear in `required`
(optionality expressed as a nullable type), so the generated schema is written to
that subset. **The model never types an id**: ids are assigned by code on ingest,
so an `id` field never appears in an output schema.

**Prove the grounding with a real call — a dry-run cannot see it.** Validating
your argv, or checking the schema is valid JSON Schema, does *not* tell you the
live structured-output API will accept it: a vendor rejects an unsupported
keyword or a non-strict `required` only on a real request. So the boundary
between a model and its schema gets a first-class check that *makes the call* —
`scripts/schema_check.py` sends one real request to each model with the generated
schema and asserts the reply (1) conforms, (2) carries no id, (3) ingests to a
valid artifact. It is the only test that catches the schema drifting from what the
API will honor; it earned its place by catching exactly that on the first run.

**Learned on the second round — the guide is the spec.** Every key a model
fills is named in the template with its exact form and an example, and the
check enforces *exactly* what the guide says. Each template bug found live had
the same shape: a field the guide left implicit (`algorithm` steps without
their field names → `description` instead of `text`), a form the guide stated
differently from the check ("n/m runs" vs `n/m`), or a shape the check never
pinned (a `U-0001` unit id where the section's prefix is `C-`; a row written as
a string). When a model's output fails a check, first ask whether the guide
could have produced anything else. And the model reads the guide, not the
code: an author that `grep`s the plugin's scripts to learn a rule is a guide
that failed.

### D2 — A coded driver; least control to the orchestrator

> **Optimize:** *minimize* the authority handed to any LLM — *maximize* the
> tasks owned by code — **subject to** the plugin's goal still being reachable.
> Every task is code until you can name the specific judgment a model must make;
> the constraint is only the irreducible core of authorship and judgment. The
> direction is always *less to the model*; you stop only when removing more
> would break what the plugin is *for*.

**Rule:** a deterministic driver decides *what happens next and whether it
counts*. Models decide only *what gets written*. Give the orchestrating LLM the
least authority the plugin's goal permits, and the driver the most.

**Why:** sequencing is the largest bug source and the one models are worst at,
because it depends on remembering state across a long context. The driver
emits **one instruction at a time** — run this exact command, author this
artifact, ask the human, dispatch this subagent — generated from the run's own
files. The orchestrator executes; it does not choose.

**The test for "code or model":** *can code decide this correctly every time?*
If yes, code decides it — always, no exceptions. A model is used only where it
cannot be replaced: authorship (writing the plan, the code, the clauses) and
judgment (accept/reject with a reason, rule a failure). Everything between —
which script, which flag, which order, whether a loop continues, whether a
phase is done, which id comes next — is code.

**Generate steps from state, don't script them.** The driver does not hold a
fixed list of steps; it *derives* the next step from what is on disk. Round 2
exists only once round 1's reply exists. This makes the run **resumable** (the
state is the files, not a counter in a model's head) and makes every loop
bound **a property of the data**, not of the model's discipline.

**Dry-run is the payoff.** Because the sequence is code over data, it can be
walked with no model at all — every generated command validated against its
script's interface in about a second. The flag/order/loop-exit bug class is
caught before a single token is spent, instead of at the last phase after an
hour.

**Resumability is a distinct guarantee — name it and design for it.** A long
agent run *will* be interrupted: the context window fills, a tool crashes, the
model wanders, the human stops it. A reliable system survives that without
redoing work, and the coded-driver-over-state design gives it for free — because
the next step is derived from what is on disk, a resumed run picks up exactly
where it stopped, not from the beginning. The test to hold: *if this run died
right now and I restarted it, would it redo anything already done, or lose track
of where it was?* If the answer is anything but "no," your state lives in a
model's context instead of on disk, and an interruption is a catastrophe instead
of a pause. Two consequences to build in: a step must be **idempotent** (safe to
re-run — its "done" is provable from a file or a recorded fact, not assumed), and
completion must be **recorded as it happens**, not inferred at the end.

The first live run (2026-08-28) confirmed both consequences and added a third: a step that *half* happened -- a review round that reviewed the wrong artifact, a `done` reported with the wrong exit -- has no clean resume unless the driver can **forget** it. That is a verb (`driver.py undo --key K`: drop the record, move the step's output aside, let `next` re-issue it), not a state edit. Without it, a resume degrades into hand-surgery on `state.json`, which is where the guarantee quietly dies.

**Second round — the orchestrator is now zero.** The optimum above turned
out to be reachable literally: there is no orchestrating model at all. A Python
loop (`runner.py drive`, a detached process) asks the driver for the next
step and does it -- a subprocess for a RUN step, a wait on a decision file for
a gate, a *fresh* headless model process for an AUTHOR step, spawned on a
prompt template code filled from the rendered inputs and the template's
guides. What a model-in-the-loop had cost was measurable: ~5 s of "deciding"
per step, 1.7 min over a 21-step build phase, and a class of bugs (a step
marked done without its deliverable, a halt narrated instead of recorded).
Skills went with it: a skill is prose a model must read and remember; a prompt
template is code-filled text a fresh process is handed once.

**The exit-code convention is a contract, and every script keeps it.** `0`: done.
`1`: a record for the human (findings ingested, a gate ahead) — the step is done.
`2`: a refusal — the step is not done; for an author's check the problems go back
to the author, for a run step the loop halts there. A script that reports an
artifact's problems as `1` (measured 2026-08-29: `contract.py check`, `plan.py
check`, `assumptions.py check`, `freeze --check`) turns a refusal into a note
nobody acts on; a loop that treats `1` as a refusal re-asks an author whose answer
was accepted. Both happened in one night; both were fixed by making the codes
honest, never by special-casing a script in the loop.

### D3 — Freeze-and-swap: whoever makes a thing never checks it

> **Optimize:** *minimize* the number of LLM judges — *maximize* the reliability
> they buy — **subject to** every failure that matters still being caught. This
> is the two-sided one: fewer judges is cheaper and faster, but a missed check
> is a silent wrong answer. You win it not by dropping checks but by *shaping
> the templates (D1) so code catches everything mechanical for free*, leaving
> the judge only the questions no field can answer. A well-shaped pipeline needs
> two or three judges; a badly-shaped one needs ten for the same coverage. The
> direction is *fewer, better-placed judges*; the lever is the schema, not the
> check list.

**Rule:** one agent produces an artifact; a **different** agent (ideally a
different model or vendor) checks and judges it; they communicate only through
code and JSON, never directly. The producer's material is **frozen** and
**withheld** from the checker so the check is independent.

**Why:** a model grading its own work is not a check — it rationalises. The only
way to get an adversarial read is to seat a party that has an interest in
finding the fault and no access to the producer's reasoning. "No access" must be
**structural, not requested**: read restrictions are unenforceable by asking, so
the producer's material is made *absent* (deleted from the checker's workspace)
or *stripped* (removed from the document handed over), never merely "please
don't look."

**Do it intelligently — not at every step.** A judge at every boundary is
correct and unaffordable. The design skill is to place the minimum number of
checks that still catch the failures that matter, and to **shape the templates
so few checks are needed** (see D-design-3). A check earns its place when: the
artifact it guards is cited by everything downstream (a wrong one is expensive
and silent), the producer had an incentive or blind spot the checker lacks, or
green would otherwise be indistinguishable from correct.

**The judge returns a graded verdict, not a boolean.** A checker that says only
pass/fail discards how *fatal* each finding is — which is the information that
decides whether it can be carried, whether the AI resolves it, or whether it
must reach the human. So every judge emits per-finding **severity** (three or
four tiers) **and its reasoning**, and the severity routes the finding up the
verification ladder (D-design-5). A binary verdict cannot route; a graded one
turns "who handles this?" into a threshold.

**The AI may design and write a check, but code should run it.** In a
cross-model setup the checker often *authors* the verification — here Codex
designs the verification spec and then writes the test code from the frozen
contract. But the checker running its own tests reopens the leak D3 exists to
close: to run them it must read the implementation, and a checker that can see
the implementation can fit its tests to it. So keep authoring isolated and hand
*execution* to code — a plain runner in the main workspace, driven by the
orchestrator, reporting failures back as text. Better still, put a second code
check under it: run every test against a mechanically generated null
implementation and require each to *fail*, so a vacuous test that would pass
anything is caught by code, not trusted from the author. Designing and coding a
check is authorship (a model's job); *running* it is mechanical (code's job, and
the more trustworthy for it).

**The freeze is the hinge.** Before authorship swaps, the artifact is hashed and
signed off; everything downstream cites a frozen version. Freezing is what lets
the check be adversarial without being chaotic — the thing under review cannot
move while it is reviewed, and a later change is a new version, not a silent
edit.

**Save tokens by checking JSON, not prose.** Because D1 made every output
structured, a check is often a *set difference or a schema assertion in code* —
free. Reserve the expensive LLM judge for the genuinely judgmental question
("is this property non-trivial?"), and let code catch everything mechanical
("this clause has no property", "this id does not resolve") for nothing.

**Second round — what the swap needs to be real.** The null stub's surface
must include everything a test may import (the contract's constants, not only
its units); a test suite that does not *import* is a halt, never a failing
test (it proves nothing); a vacuous test is a halt, not a gate; the import
convention is stated to the test author and to any later fixer, and a fixed
suite is checked against the null before it merges. And the caps: `rounds`
bounds the review loops *after* the first check -- both the coverage loop and
the triage passes had counted the first check as a round, so at `rounds = 1`
the reviewer never ran.

### D4 — Traces as JSON; the minimum-complete dashboard

> **Optimize:** *minimize* what is shown — *maximize* the completeness of the
> human's picture — **subject to** the human always being able to answer where /
> healthy / when-done / cost, and to pinpoint a failure. This is a *minimal
> sufficient* problem, not a maximal one: every signal that does not help answer
> those questions is noise that hides the ones that do. And it has a second
> constraint the others don't — *legibility*: the surviving signals must be laid
> out so the eye catches them fast, never crammed. The direction is *less shown,
> more understood*.

**Rule:** every agent and every step appends a structured event to one
append-only log. A dashboard reads that log and shows the **smallest view that
still lets a human answer: where are we, is it healthy, when will it finish,
what has it cost — and if it failed, exactly where.**

**Why:** a long agent run is opaque. Without a trace the human cannot tell a
run that is working from one that is stuck, and cannot locate a failure when
one happens. The trace must be *structured* (JSON events, one writer, appended
as a side effect of work the code had to do anyway — never a step a model is
asked to perform, or it will be skipped or lied about) so the dashboard is a
*read*, not a reconstruction.

**The dashboard answers two orthogonal questions, and must keep them separate.**
There are two entirely different meanings of "is the run OK," and conflating
them into one green light is a real failure:

- **Did the flow run to completion?** — the *process* question. Every step
  executed, every handoff completed, nothing was skipped, and the run reached its
  end. This is about the **machine**, and the driver plus the trace answer it
  (D2 + D4).
- **Is the output correct?** — the *product* question. The tests pass, the AI
  judges accepted, the human signed. This is about the **work product**, and the
  verification ladder answers it (code / AI / human, D-design-5). A product
  failure means the *built thing* is wrong even though the machine ran
  perfectly.

**A stopped flow is not one thing, and "bug" is only one of its causes.** When a
run does not reach the end, the dashboard's job is to say *why*, because the
causes span a spectrum with very different responses — and some are not failures
at all:

- a **plugin bug** — a wrong flag, a broken handoff → fix the plugin;
- **stuck** — a loop could not converge and hit its cap → raise the cap, accept
  what was carried, or conclude the artifact will not converge as framed;
- a **nonsensical or malformed model output** the next step could not use →
  retry, or the model/prompt is inadequate for the task;
- the **problem is not solvable as specified** → nothing in the plugin is wrong;
  the human rethinks the task.

That last case is the crucial one: a run that stops because the goal cannot be
met is the system **succeeding** — it told you the truth early instead of
manufacturing a false green. (This project's second run did exactly that: the
checker falsified the premise at phase 2 and the run stopped; that was the point
working, not a bug.) So the process signal has three states, not two —
**completed**, **halted honestly** (it hit a real wall and said so — a valid
outcome), and **broke** (a genuine malfunction) — and the dashboard must
distinguish the last two, because "the task can't be done as asked" and "the
machine is broken" look identical as "it stopped" and demand opposite responses.

A run can pass one axis and fail the other, and a single "healthy" light cannot
tell them apart. So the dashboard carries **two distinct signals**: a process
signal from the trace (advancing / halted-honestly / broke, and if stopped,
*why*) and a product signal from the ladder (do the verdicts say the output is
right?). The product one is the easy one to forget — the tests and judges run
"off to the side," so their verdicts must be deliberately surfaced onto the same
screen as the progress, not left in a results file.

**The dashboard shows verification outcomes, not just progress.** Progress
(what stage, how long, how much) tells the human *where* the run is; it does not
tell them whether the run is *right*. For that, the dashboard must surface the
verdict of every verification tier as a first-class signal: which code checks
passed or gated, what each AI judge in the freeze-and-swap returned
(accepted / revise / a graded finding), and which human gates are signed versus
pending. That is what lets the human answer the question they actually care
about — *did it reach the goal, and if not, exactly where and at whose check did
it fail* — from one screen instead of reading every artifact. Failure
localization is precise because each verdict is tied to a step and a tier:
"phase 7, coverage check, three clauses uncovered" is a pointer, not a hunt.
(Which checks belong to which tier is D-design-5, and it is designed *with* this
dashboard, not after it.)

**Minimum-complete, not maximal.** Showing everything is as useless as showing
nothing — the signal drowns. Pick the few quantities that answer the four
questions above and lay them out for the human eye to catch fast: what stage,
healthy-or-not per stage, elapsed and estimated-remaining, token cost, and on
failure a pointer to the exact step and its output. Everything else is one
command away, not on the default screen. Cluttering a complete picture into a
cramped space is worse than an incomplete one; give it room and rank by
importance.

**The trace is also how you debug the system itself.** When the plugin
misbehaves, the JSON log is the record of what each agent actually returned —
which is how you tell a model bug from a wiring bug.

**Second round.** The dashboard became the launcher and the live snapshot of a
run: the brief is filled on it, the runner is a card on it (alive / exited /
halted, what it is doing from its stream, Stop / Resume), the tools, skills
and MCP tools each stage used are chips read from the streams, and completion
writes `REPORT.md`, a self-contained `PAGE.html`, and a `snapshot.json` that
rebuilds the page later. The page follows the driver's stream: its refresh
hash covers the event log, the state, every live stream file and the gate
files -- a page that reloads on the wrong cue reads as a bug.

### D5 — Human-in-the-loop: the human's attention is the scarcest resource

> **Optimize:** *minimize* the number of times you interrupt the human, and
> *minimize* the volume they must read to decide — **subject to** every decision
> that is genuinely theirs still reaching them, legibly and in time to matter.
> This one has an internal split the others don't. Interruptions: *few*, and
> heavily batched — one popup carrying ten questions beats ten popups, because
> the cost to the human is the context-switch, not the answering. Questions per
> batch: *moderate*, not minimal — don't artificially split what belongs
> together, don't cram forty either. Review burden: *minimal* — at every point
> where the human checks the system's work, surface only what genuinely needs
> their judgment, never the whole artifact. Their time is the budget.

**Rule:** the human is a third decider alongside code and models, and the *only*
one for a specific class of choice: taste, priority, ground truth, and the
sign-off that puts their authority behind a frozen result. D2 minimizes what
*models* decide; D5 is about extracting what only the *human* can decide at the
lowest possible cost to them. The three-way allocation is: **code** owns
everything mechanical, the **human** owns what is irreducibly theirs, the
**model** owns authorship and the judgment the human delegates.

**Two different costs, two different optimizations — this is the crux.**
- *Interruption cost* is paid per popup, not per question. So **batch
  aggressively**: gather every decision a stage needs into one popup with
  several questions, each with concrete options and a recommendation. One
  ten-question popup at the start beats ten one-question popups through the run.
- *Review cost* is paid per thing the human must read and judge. So at every
  checkpoint — an interview, a sign-off, an approval — **minimize what reaches
  them**. Show a summary of what changed, not the forty-page document. Confirm
  **by exception** ("here are thirty assumptions; correct the wrong ones") not
  by enumeration ("approve each of thirty"). Give them the decision, pre-loaded
  with the system's recommendation, not the raw material to derive it from.

**Give the human a dial, not a fixed burden.** The same run can want heavy human
involvement (a critical contract) or none (an overnight batch). A *mode* setting
lets the human choose how much reaches them — ask every decision, ask only the
risky ones, or ask none and record every auto-answer as a flagged assumption to
review at a single gate. What is not asked is never silently decided: it is
answered by the model, marked, and made cheap to audit in one place. That is how
you honor "minimize my review time" without ever hiding a decision.

**Never let waiting look like silence.** Any moment the run cannot proceed
without the human must surface as an explicit, actionable prompt — options and a
recommendation — not a paragraph that trails off. A run that stops and explains
in prose that it is waiting reads, from the other side, as a run that died. The
handoff is a first-class output, not an afterthought. *(This was a real failure
here: eleven of twenty turns on one run ended in prose while blocked, and from
the human's side the working run looked frozen.)*

**Match the form of the ask to how the human reads.** Minimizing the human's
cost (D5) is not only about *how often* and *how much* you ask — it is also about
the *shape* of each ask. The same decision can cost the human ten seconds or two
minutes depending on presentation, and the difference is pure waste. Present
every human-facing prompt in the form that lets *this* human decide fastest:
lead with the decision, not the context; give concrete options with a
recommendation marked first; say what each option costs in a line, not a
paragraph; keep it scannable, one idea per line, no wall of prose. Some humans
need it chunked hard — one clear decision at a time, or a batch where every
question is self-contained and quick — and a system that respects a stated
cognitive style (attention, dyslexia, language) is one whose human tier actually
gets used instead of skimmed. The presentation is not cosmetic; a poorly-formed
ask is answered carelessly, and a careless answer on a judgment gate is worse
than no gate at all. Make the human's decision cheap to make *correctly*, not
just cheap to reach.

**Which gates are justified — the two-kinds test.** Every place you might stop
for the human, apply one test:

> A human gate is justified only if it **gathers a value only the human has**, or
> **makes a judgment only the human can make**. If it does neither — if it is
> "look at what happened" with nothing to decide — it is not a gate, it is a
> notification. Present it; do not ask it.

The two kinds behave differently in time, and that difference tells you *where*
each belongs:

- **Input gates** gather something only the human holds — the goal, a priority, a
  tolerance, the ground truth a check compares against. They must come *before*
  the work that needs the value, and they **cannot** be replaced by presenting
  results, because without the value there is nothing to do the work against.
- **Judgment gates** make a call only the human can make — accept this gap for my
  goal, sign this off, this decomposition is right. These **can** be
  *exception-triggered*: present by default, and pull the human in only when
  something crosses a threshold (a fatal finding, an unmet tolerance).

Worked through the interviews of a build pipeline, the test is decisive and it
prunes hard:

| candidate gate | kind | verdict |
|---|---|---|
| align on the goal (what to build, what "done" means, what is out of scope) | input — the goal itself | essential, up front; nothing downstream means anything without it |
| confirm the decomposition (how many blocks, what each does — "are these the right blocks?") | judgment — is this the right split | **keep, and make it the real gate.** The AI *proposes* with rationale, the human answers "right / wrong"; if right, the pipeline continues. The decomposition is where the human's structural judgment actually lives |
| elicit tolerances and ground truth ("how close is close enough," "what is the correct answer") | **input** — numbers only the human has | **essential *when it applies*, and generated from state — not a fixed phase.** Where the spec has open tolerance slots (a fuzzy match, a numeric bound, a timing budget) those numbers are the human's and verification cannot run without them. But an exact spec (most straightforward code) has *zero* open slots, and then this gate has nothing to ask and must not fire. Generate the questions from the open slots (D2): zero slots → no interview, the pipeline flows through; slots present → one question each. The ground-truth half is domain-dependent too — for deterministic code the oracle *is* the spec; a separate ground-truth ask matters only for fuzzy/ML work. **Do not make this an unconditional phase; a fixed "tolerance interview" every run is the habit-stop D5 warns against.** |
| confirm the verification set ("does this test what you expect?") | judgment — does the plan verify what matters *to me* | **keep — this is a real gate, and an underrated one.** The verification set defines what "correct" will mean, so if it tests the wrong things a green result is meaningless. The AI catches *missing* clauses (a fatal-gap escalation); only the human catches *misaligned emphasis* — "you tested the easy things, not the one that would actually break." Confirm the plan *before* the expensive build |
| sign off the frozen spec (a separate "approve before freezing" stop) | judgment, but a redundant one | **collapse it.** Do not stop again just to sign the freeze. The human's real judgment was already spent on the decomposition and the verification set; the fatal findings already reach them by escalation; the AI review and audit already checked every clause. So the freeze *mechanism* still runs (hash, commit, swap) but as an **automatic** step once the blocks are confirmed — not a scheduled human stop. Pull the human in here only by exception (a fatal gap) |
| "review the build / vspec / test *results*" | **neither, when the run passed** | **cut it.** If everything passed, present the result — do not ask. A fatal finding carried, a tolerance unmet, or an honest halt is an *escalation* (exception-triggered), not a scheduled interview. Note the distinction from the row above: reviewing the verification *plan* (before build) gates trust and is kept; reviewing passed *results* (after) is redundant and is cut |

Two consequences worth stating, because they are the common mistakes:

- **You cannot defer an input gate to "just present results."** The gate that
  elicits ground truth *is* what makes results checkable; there is nothing to
  present without it. Input gates are early and mandatory by nature.
- **A scheduled "review what happened" interview is almost always the wrong
  shape.** Replace it with a presentation plus an exception-triggered
  escalation. The human should be pulled in when something needs *their*
  judgment — a fatal gap, an unmet tolerance, an unsolvable situation — not
  because the calendar of phases reached a review step. Completeness-of-coverage
  splits the same way: "does the spec cover the contract?" is a **code** check;
  "does the contract cover what I actually care about?" is the human's, delivered
  as a fatal-gap escalation with the judge's reasoning, never as a standing
  meeting.

**Second round.** Gates live on the page, inside the panel of the stage they
decide, with the carried items above the rows; the human never types into a
terminal. Every decision and every comment is recorded verbatim and appears in
the final report. A halt is a report code writes -- the step, the command, its
own GATE/HALT line, the last six stream facts -- and Resume continues at that
step; the human reads, fixes, presses one button.

### D6 — Convergence: carry the trajectory, never summarize it

*(2026-08-29: the same rule governs a re-ask — the author gets the exact problems AND its own
refused answer, never the verdict alone; two attempts oscillated for want of it. And a loop's
"no progress" is a problem set seen in any earlier attempt, not only the previous one.)*

> **Optimize:** feed round *N* of any refinement loop the **exact** prior context
> — every earlier round's input *verbatim*, plus a *code-computed* diff of what
> changed — **subject to** never letting a model summarize a prior round into the
> next. Orthogonal to the others: it governs not *who* decides or *how* control
> flows, but how an iterative loop carries its own history so it **converges**
> instead of drifting.

Every loop in the pipeline runs more than once — the gate comment loop
(human↔model), the review loops (Codex attacks, Claude arbitrates and revises),
the coverage loop, triage. Each round's job is to build on the last. The failure
this dimension prevents is the one D5 names for a single human answer, generalized
to a loop's whole history: **a summary of a prior round is a model interpreting
what was said — a human comment, or a finding and the ruling on it — and handing
that interpretation to the next round as if it were the original.** Interpretation
wearing the original's authority. Drop a nuance in round 3's summary and round 4
optimizes against the wrong target while *looking* converged — the worst failure
mode, because nothing flags it.

So the packet at round *N* carries three things, and a summary is none of them:

1. the **current state**, exact (the accumulation of prior rounds — it *is* what
   the model revises);
2. **every prior round's input, verbatim** — the human's comments, or Codex's
   findings plus Claude's exact arbitrations (accept/reject *and* the reason);
3. the **exact diff of what changed each round**, *computed by code* from the kept
   version snapshots — not narrated by a model.

This is lossless yet compact — verbatim inputs and computed diffs, not raw copies
of every past artifact, which dilute the signal and invite re-litigating settled
points. It is also D1 and D2 applied to *history*: the inputs are carried exactly
(D1's structured record), "what changed" is computed by code (D2), and only the
*writing* of the next revision is left to the model. Two consequences follow.
**Version snapshots are a reliability requirement, not mere provenance** — an exact
diff is impossible unless each version was kept. And **a model's own thread memory
is not the source of truth**: `--resume-last` and its kin are opaque — you cannot
inspect or verify what the model "remembers," so the trajectory lives in the
packet, on disk, auditable; thread memory may stay as a belt, never the record.

The tell that this dimension is missing: a loop that oscillates or re-opens
resolved points across rounds, or a revision that quietly undoes an earlier fix —
the model never saw, exactly, what the earlier round decided.

---

**Second round.** Two rules the trajectory principle needed in practice: a
finding re-raised after a rejection and rejected again *escalates* to the
human (two informed parties disagreeing twice will not be settled by a third
exchange); and a resume replays the *fixed* loop against the files -- so a
resumed run can legitimately land new files after a phase's commit, and the
driver generates a second commit instead of refusing forever.

### D7 — Streams are the signal; exit is the backstop

*(2026-08-29: an `api_retry` line is the harness retrying an unavailable API, not the model —
it is a `retry` fact, counted and shown, never liveness; the stall/scope/timeout watchdog is an
independent task that interrupts, then closes the transport. One call had sat 21 minutes on
retries that kept resetting the stall clock.)*

> **Optimize:** *minimize* the time between something going wrong inside a
> model process and code knowing it — *maximize* what every consumer (the
> loop, the trace, the page, the halt report) learns while the process is still
> running — **subject to** the process's own exit and the checks on its files
> remaining the final proof. The direction is *pull the stream, never wait for
> the end*.

**Rule:** every model process writes its event stream as it works
(`claude -p --output-format stream-json --verbose`, `codex exec --json`), to a
file under the run. ONE reader (`fs/streams.py`) turns each line into
normalized **facts** — `turn`, `tool`, `write` (a path), `usage` (tokens so
far), `final`, `error`, `thread`, and a `heartbeat` on every line — and every
part of the system that is *flow-dependent* takes its signal from those facts,
pulled continuously, never from waiting for the output file at the end.

**Why:** a process that has gone wrong keeps running. On this project's live
runs: a contract author wrote its file to the wrong directory, exited 0, and
the loop marched on to a review of nothing; a Codex review that stalled was
caught only by a hard timeout (a 20-second timeout fired after 920 seconds,
because the wait re-checked its clock only when the child next wrote); the
page learned that a runner had exited only when an unrelated file changed; the
runner's tokens appeared as one lump at exit, unattributable to any stage.
Each of those is the same failure: the signal existed in the stream the whole
time, and nothing was reading it.

**What each consumer takes from the stream, and what it replaces:**

| consumer | takes | replaces |
|---|---|---|
| the loop — every process wait (`streams.wait_process`) | `heartbeat` → an **inactivity watchdog** (`--stall`, default 300 s; the hard `--timeout` stays as a backstop) · `write` outside the step's scope → kill and halt at once, naming the path · `error` → the error text in the halt · `final` + the expected files present → the deliverable is done | fixed clocks; trusting exit 0; discovering a wrong path at the next step |
| the trace (`state.event`) | `usage` → tokens **as they accrue**, with the phase and stage (flushed every 20k tokens; the exit total contributes only the remainder) · the last six facts on every `agent` / `codex` event | one lump at exit; guessing cost from `--out` |
| the page | the runner card's "what it is doing" for Claude and Codex alike · "last signal N s ago" · tokens rising during a call · a `/status` hash that follows every live stream file, the event log, the state and the gates | a card that goes blank during a call; a page that reloads on the wrong cue |
| the halt report | the failing process's last six facts, verbatim | a bare exit code and a tail of stdout |
| `done` (D2) | unchanged: the files are the proof — but the loop reaches `done` with the facts already checked, so a missing deliverable is refused before `done`, not after | — |

**The test for "stream or exit":** *would a human watching the terminal have
known before the process ended?* If yes, the stream carries that signal and
code must read it there. What the stream cannot tell you — whether the file
the process claims to have written is valid — is what the checks and freezes
(D1, D3) are for, and they still run after exit.

**Engineering notes.** Tail by byte offset with a partial-line buffer (the file
is mid-write). Parse defensively — a malformed line is a heartbeat and nothing
else. Keep the watch's memory bounded (the last six facts). Kill the whole
process group, not the pid. Treat stall, scope and timeout as three distinct
reasons in the event and the report; they point at three different bugs.

**Backends.** The same facts come from two backends: `claude -p
--output-format stream-json` as a subprocess, or the Claude Agent SDK
in-process (the stream arrives as objects; each is written as the same
stream-json line, so every consumer is unchanged). The SDK is the default when
installed; the CLI is the fallback. Codex is always `codex exec --json`.

### D8 — Unstructured tool behaviour is waste

> **Optimize:** *minimize* the actions a model can take that are not the answer —
> **subject to** the answer still being the model's: it is free, inventive even,
> *inside* the schema. The direction is always *fewer degrees of freedom outside
> the schema*; the constraint is that judgment and authorship stay with the model.

**Rule:** a model call has no tools, no files and no shell unless a specific
step needs one — and after the constrained-decoding change, no step does. Every
input is inlined by code, file by file; every output is the structured answer;
every execution (checks, compile, the null and real runs, merges, commits) is a
code step the driver runs and records.

**Why:** a model with tools it does not need spends them. Measured on the
authors before the change: 10–20 turns per call re-reading inputs that were
already in the prompt, 87 turns of a contract author exploring the repository,
writes to the wrong path, edit loops against its own checks — ~75 % of a run's
wall clock in *turns × (latency + thinking)*, almost none of it in the answer.
Tool I/O itself was ~1 %; the waste is the *turns*. Every second and every token
has to serve the goal, not what the model thinks serves the goal. The result is
the least randomness and the most control a pipeline of free models can have:
one turn of thinking, one answer, code does the rest.

**How it is enforced (in code, not in the prompt):** Claude authors run with
`tools = []`, every built-in tool disallowed, no MCP servers (strict), no user or
project settings, no plugin — the harness still *registers* its bundled skills,
agents and slash commands (the stream's `init` line lists them), but with no
`Skill` or `Task` tool they are unreachable; `max_turns` ≤ 3 — one answer, and
the re-ask is the loop's, not the model's. Codex runs with its **shell tool
disabled** (`--disable shell_tool`, plus browser, computer, apps, plugins, skills
and hooks off; `--ignore-user-config --ignore-rules`, so no MCP server or rule
from `~/.codex` reaches a call), in a temporary directory outside the project,
handed no path:
measured 2026-08-29, a read-only sandbox with a shell still reads the whole
disk — the verification author read the contract's section 8 from the run
state with one `rg ..`; without the shell it answers "this environment does
not provide a shell command execution tool" and returns the schema. The prompt's "you have no tools" line is information so the
model does not waste a turn trying; the streams are the proof (the first run
after the change caught an MCP server from the user's global config still
reachable — the fix was in the code, and it is why the prompt is never the
enforcement). The per-file path-policy hook stays as the guard for any future
tool-bearing agent; nothing in the pipeline uses tools.

**Measured, per call, in the report:** `REPORT.md`'s waste table — mode
(structured / tools), turns, tool calls, denied calls, waste turns (turns beyond
the one answer, or every tool call when tools were on), seconds, tokens. The
comparison runs (tools-on vs tools-off, the same brief) report that table as the
number.

## The classes the runs taught (2026-08-29)

Twenty-seven bugs were flushed by the runs in one night, each classified before it was fixed and
fixed at the mechanism, never the instance — `docs/BUG-LEDGER.md` carries every row. The ten
classes, because the next bug will belong to one of them: *a second owner of a fact* (a glob, a
rendered view or a hand-written list standing in for the record); *an exit code that lies*; *a
message that hides the reason*; *state left by an earlier run or step*; *the model with more
freedom than the answer needs*; *liveness from the wrong signal*; *a check that contradicts the
artifact's own rule*; *a step issued with nothing to do* (the empty set); *a message parsed by
position*; *a shared record written by parallel workers*; *a fact with no owner* (the file
layout, a constant named by clauses, the package surface, which file a ruling's fix belongs to);
*the re-ask carrying the verdict but not the artifact it judged*. Read the ledger before touching
anything.

## The acceptance checklist

What "implemented as intended" means for this plugin, item by item. An
independent reviewer (a fresh model with the code and one run's traces, never
the author) walks it end to end; a run is not accepted while any item fails.

1. **Constrained decoding at generation for every model output.** Claude by the SDK's `output_format`, Codex by `--output-schema`; the schema is *generated* from `fs/spec.py` — one source, no hand-written schema anywhere, no drift.
2. **No model has tools, files or a shell.** Claude authors and the ruler: `tools=[]`, every tool disallowed, no MCP servers, no user or project settings. Codex: a read-only sandbox in an *empty* working directory. "Per file" is done by inlining, never by permission.
3. **Code writes every file** (`files.py`, `runner.apply_structured`, `round.py apply`) and **code checks only what a schema cannot say** — a cite resolves, `py_compile`, the null run, the real run, the reason rules, the freeze hash.
4. **Every model input is JSON rendered to markdown by code and inlined** — no paths to read, no re-reads, no summaries.
5. **Every loop carries the full trajectory verbatim** — the findings files with their statuses, the Codex thread — never a model's summary.
6. **The loop is code.** `driver.py next / done` owns sequencing; `runner.py drive` runs it; exit codes are the discipline; a missing deliverable reopens its step; a refused answer is re-asked with the exact problems at most six times (`config.RE_ASK_MAX`), stopping earlier when a problem set repeats, then the run halts with the last stream facts.
7. **Streams are the signal** — stall, scope, error, final; tokens attributed per stage as they accrue; exit is the backstop.
8. **Granularity and length.** Typed lists everywhere (ledger `recon` / `note`, the six plan sections, units `params` / `returns` / `input_schema` / `output_schema`, scalar values); length rules only the listed ones — minimums on judgment text, 400 characters per clause, ≤ 30 ledger rows, none on code.
9. **Nothing a model reads is a skill**; anything code can do is never a model's job.
10. **The page and the report.** Agent rows read `tools: none · structured`; `REPORT.md` carries the waste table (Claude and Codex rows); the page's behaviours are unchanged — live without refresh, local times, gates inside their stage panel, the snapshot rebuilds it — and `serve.py selfcheck` proves them by code.
11. **The docs match the code** — this checklist, the D1 conformance table, D8, the README.
12. **The traces agree.** After one end-to-end run, every step's trace — `events.jsonl`, the agent and Codex live streams, `runner.log`, `report.json` — is read, and nothing in it contradicts items 1–11: no tool call that is not `StructuredOutput`, no file written by a model, no re-read of an inlined input, no step outside the driver, no summary in a round.
13. **What was loaded is what was allowed.** In every Claude stream's `system init` line and every Codex stream's header: the tools, the MCP servers, the skills / slash commands, the agents, the model and the API — nothing loaded beyond `StructuredOutput` for a Claude author, no shell and no capability at all for Codex (`shell_tool` and the rest disabled), no MCP server, no skill, no agent, no API call outside the two backends.

## The design decisions each dimension forces

The dimensions above are *what*. These are the *how* — the choices you must make
deliberately, and how to make them. Get these wrong and the dimensions become
overhead instead of reliability.

### D-design-1 — Granularity of JSON templates: the cite-or-check rule

The single most important schema decision, and the one with a clean test:

> **An element is its own JSON element if, and only if, something downstream can
> cite it, check it, or accept/reject it on its own.**

- **Too big hides inconsistency from checks.** A rationale blob covering five
  decisions can be internally contradictory and still "valid" — nothing can
  point at the broken part. (Real case here: a plan's decomposition rationale
  drifted from its own decision, and no id could reference the wrong half.)
- **Too small adds keys nothing reads** — pure failure surface, tool-call
  overhead, and a model padding fields to fill them.

So: one clause, one algorithm step, one property (with its facets as *separate*
keys, because separate gates read each facet), one plan argument, one decision
(with options as elements), one assumption. A string value is allowed only when
it is about exactly one thing. The cheap half of this is enforceable: refuse a
string over ~400 characters or holding multiple paragraph breaks with "split
this into elements."

Two different sizes, both real: **transport size** (how much per model call —
one section, capped item count, so an error names the item) and **element
shape** (cite-or-check). Do not confuse them.

### D-design-2 — How much goes to code: the replaceability sweep

Walk the whole pipeline and, for each step, ask the D2 test: *can code do this
correctly every time?* Push everything that can be to code. What remains is a
short list — and it is always authorship and judgment, nothing else.

A useful discipline: assume a step is code until you can name the specific
judgment a model must make. "The model decides which file to write" is not a
judgment — the ledger's `writes` column decides it. "The model decides whether
this failing test is the test's fault or the code's fault" *is* a judgment. The
first moves to code; the second stays, and gets a template (D1) and a check
(D3).

### D-design-3 — Where the judges go: co-design the template with the check

This is the subtle one, and it is why D1 and D3 are designed *together*. **The
shape of your JSON decides how many judges you need.** A template that carries a
`class` field turns a "which categories are missing?" judgment into a set
difference — no judge. A template that carries `implements: [clause-ids]` on
each algorithm step turns "does the code cover the contract?" into a set
difference — no judge. A template that leaves those as prose forces a judge at
every such question.

So the method is: **first make every mechanical check free by adding the field
that lets code do it; then count the genuinely judgmental questions that
remain, and place an LLM judge only there.** In a well-shaped pipeline that is
two or three judges, not ten. The judges you keep are the ones asking questions
no field can answer: *is this argument sound? is this property non-trivial? is
this the right decomposition?*

Place each surviving judge where three things coincide: the artifact is cited
widely downstream, the producer had a blind spot the judge does not, and a
mechanical check cannot substitute. Freeze the artifact, hand the judge only the
withheld view, record the ruling as JSON.

### D-design-4 — The dashboard: pick the four signals, then lay them out

Design the dashboard by first answering "what must the human know?" — where in
the workflow, healthy per stage, time remaining, cost — and *only then* choosing
what to draw. Everything not answering one of those questions is off the default
view. Then spend real effort on the layout: fixed columns, one signal per
column, ranked by importance, room to breathe, the eye able to find the current
stage and its health in one glance. A complete picture crammed into a cramped
grid is a failure; so is a beautiful screen that omits the one number that says
it is stuck.

### D-design-5 — The verification ladder: who verifies what

Verification is not one thing done in one place. It is a **three-tier ladder**,
and which tier owns each check is a single design decision that spans D3, D4 and
D5 — decide it once, for every verification question in the pipeline, and decide
it *when you design the templates*, because the template shape is what makes a
tier possible.

| tier | verifies | reliability | cost | example questions |
|---|---|---|---|---|
| **code** | anything mechanical — schema conformance, id references resolve, set differences, exit codes, the null run, the tests | highest (deterministic) | cheapest (free, every artifact, every time) | "does every clause have a property?" · "did the implementation cover every algorithm step?" · "does this id resolve?" · "do the tests pass?" |
| **AI** (the freeze-and-swap judge) | the judgmental questions no field can answer, at the few points D-design-3 identifies | lowest (probabilistic) | middle (one model call) | "is this argument sound?" · "is this property non-trivial?" · "is this the right decomposition?" · "is this failure the test's fault or the code's?" |
| **human** | what is irreducibly theirs — goal, priority, ground truth, sign-off | middle (good but variable) | most expensive (their attention, the scarcest budget — D5) | "is this the right thing to build?" · "is this tolerance acceptable?" · "is this the ground truth?" · "do I put my name on this frozen contract?" |

**Two axes, pointing opposite ways — this is what drives the whole rule.**
Reliability runs **code > human > AI**; cost runs the other way, **code < AI <
human** (code cheapest, AI middle, human most expensive). **Code wins on both
axes** — most reliable *and* cheapest — so there is no tradeoff: push everything
it can do onto code, always. The only genuine tradeoff is between **AI and
human** for the judgmental questions code cannot touch: the human is more
reliable but most expensive, the AI cheaper but weakest. The deciding variable
is *stakes*. Spend the expensive, reliable human only on the highest-stakes
judgments — the sign-off, the ground truth, the goal itself — and let the cheap,
weak AI (strengthened by structure and a code backstop) carry the many
lower-stakes judgments a human has no time for. Cost is why you cannot simply
"use the human everywhere," and reliability is why you cannot "use the AI
everywhere"; the ladder is how you spend each where it pays.

**Strength versus scope — do not mistake the ladder for a single ranking.** On
the *reliability of a verdict*, the order is **code > human > AI**: code is
deterministic (same input, same correct answer), the human is a good judge but
variable (skims, tires, rubber-stamps), the AI is the least trustworthy
(probabilistic, rationalizes, gameable). But the tiers **do not compete for the
same question** — each is the only or best tool for its *class*, and useless
outside it. Code is strongest, yet cannot judge whether an argument is sound.
The human judges best, yet has finite attention. The AI is the weakest verdict,
yet is the only affordable judge for the many judgmental questions no human has
time for. So "the AI is the weakest tier" is not a reason to distrust the
system; it is the reason for three moves: **minimize** reliance on it (D3),
**strengthen** it with structure (freeze the input, withhold the producer's
view, frame it adversarially, and where it matters take a majority of several
judges — a weak judge under strong structure beats a strong judge with none),
and **backstop** it with code wherever a mechanical check can sit *under* the
judgment. In this project the null-implementation run (code) measures whether a
property is trivial, directly, underneath the AI's judgment of the same thing —
the ladder covering its own weakest rung.

**The allocation rule, top-down:** every verification question starts as a
candidate for **code**. If a field can be added that lets code answer it
(D-design-3), it belongs to code — free, and it removes an AI judge. What code
cannot answer is a candidate for the **AI** judge, placed only where D3 says it
earns its seat — and given code underneath it wherever one fits. What is not a
matter of correctness at all but of *judgment the human owns* — what is right,
what is acceptable, what is true — goes to the **human**, batched and minimized
per D5. Push every question as far up the ladder (toward code) as it will go,
and put a code check under every AI judgment you cannot push all the way up; a
question one tier too low is either wasted tokens (an AI judge doing a set
difference) or wasted human time (a human confirming what code already proved).

**Graded verdicts route; a binary verdict cannot.** An AI judge that returns
only pass/fail throws away the one piece of information that decides *who should
handle the finding*: how fatal it is. So the judge emits a **severity** (three
or four tiers — e.g. fatal / serious / minor) **and its reasoning**, never a
boolean. The severity is then the router up the ladder: minor findings are
recorded and carried (or accepted automatically), and only findings above a
threshold are escalated to the human — each arriving pre-loaded with the judge's
reasoning, so the human sees the few that might matter, not the many the judge
found. Severity is what keeps the human's review minimal (D5) *and* what
guarantees a fatal finding is never silently carried.

**The threshold is the top tier, the checking agent owns the grade, and it is
the same at every swap.** Fix the escalation threshold at *fatal / blocking* —
the highest severity — and nothing below it ever interrupts the human. This
holds **uniformly at every check point in the pipeline**, not selectively: a
cross-model pipeline swaps authorship several times (one agent designs the
contract and the other attacks it; then they swap so the second designs the
verification and the first checks its coverage; a failure at the end is ruled by
whoever did not write the thing that failed), and *each* of those checks follows
the identical rule — agents settle minor and major between themselves in the
arbitration loop, and only what the checker graded fatal reaches the human. A minor or a serious finding is
resolved between the agents in the arbitration loop; only what the checker
itself graded fatal becomes a human interview. This makes the human's attention
budget *deterministic and small*: they are asked about exactly the findings the
checking agent flagged fatal, no more, and never with a vague "what do you
think?" — always a definite question about one graded finding ("Codex marked
this fatal, here is why — accept for your goal, or redesign?"). The checker
decides what is fatal precisely so the human does not have to triage the pile to
find the ones worth their time; that triage is the checker's job, and grading it
is what earns the checker its seat (D-design-3).

**An escalated finding asks the human a scope question, not a correctness
question.** The judge already established the finding is real; whether it
*matters* depends on what the work is for — which the AI does not know and the
human does. So the escalation is not "this failed, fix it." It is: *"the judge
flags that X is not covered, for this reason — is that acceptable for your goal,
or does it need redesign?"* The human accepts-and-scopes-out, or sends back.
This is D5's "the human owns the goal" applied to verification: the human is not
re-checking the AI's correctness, they are ruling acceptability against a goal
only they hold. It is also why the escalation carries the judge's *reasoning*,
not just its verdict — the human is deciding on the argument, not the label.

(This project already grades findings `blocking / major / minor` and carries
unresolved ones; the refinement is to *route the fatal ones to the human with
their reasoning* for an accept-vs-redesign ruling, rather than carrying them
silently. Severity was a sort key; it should be a routing key.)

**All three tiers report to the same dashboard.** This is why D-design-5 and the
dashboard (D-design-4) are one design: the human's "full idea of what was done"
is the *union* of the three tiers' verdicts on one screen — green/gated per code
check, accepted/revised per AI judge, signed/pending per human gate — each tied
to the step and phase it belongs to. The AI verifications especially must be
visible: a freeze-and-swap where Codex reviewed the contract, an audit re-read
it fresh, and a triage judged a failure are *verification events the human did
not perform and must still be able to see the outcome of*. Progress tells the
human where the run is; the ladder's verdicts tell them whether it is right, and
where it is not.

**Reaching the goal is a verification result, not a progress result.** "Phase 9
of 9" is progress. "Every property passes, no clause carried, the human signed
the freeze" is the goal, and it is the conjunction of the three tiers' final
verdicts. The dashboard's top-line answer to "did we make it?" is that
conjunction — and when it is false, it names the tier and step that made it
false.

---

## JSON templates for code (the case most plugins will hit)

Most plugins built this way will produce **code**. Code is the one LLM output
that does *not* become a filled JSON template — but everything around it does.
Here is the full pattern, because it is where the abstract rules get concrete.

### Why code stays code

The interpreter, then the type checker, then the tests, then a "null
implementation" run are **stricter validators than any JSON schema you could
write**. Wrapping a 200-line file in `{"content": "..."}` adds nothing a checker
can use — it is still an opaque string — and it fails on the escaping (quotes,
newlines) rather than the logic, which is the worst possible failure. Code is a
file; files are what git diff, ownership checks, worktree isolation and the
human's editor all operate on.

### What *does* become JSON: the specification and the envelope

**1. The specification the code is built from — a contract.** This is a JSON
document the producing model fills, one element per checkable thing. For a code
block it looks like:

```json
{ "block": "textcell",
  "input":      [ {"id":"C-011","name":"s","type":"str","tags":[]} ],
  "output":     [ {"id":"C-013","name":"result","type":"str"} ],
  "units":      [ {"id":"C-015","name":"fit","kind":"function",
                   "params":  [ {"name":"s","type":"str"},
                                {"name":"n","type":"int"},
                                {"name":"align","type":"str","default":"'<'"} ],
                   "returns": {"type":"str"},
                   "holds":   "returns s fitted to exactly n display cells" } ],
  "invariants": [ {"id":"C-021","claim":"width(fit(s,n)) == n for all s, n>=0","measurement":null} ],
  "failure":    [ {"id":"C-040","on":"n < 0","policy":"raise ValueError","observable":"message contains 'n'"} ],
  "algorithm":  [ {"unit":"C-015",
                   "steps":[ {"id":"A-001","text":"measure the display width of s","implements":["C-021"]},
                             {"id":"A-002","text":"pad or truncate to n cells","implements":["C-021"],"uses":["C-055"]} ]} ] }
```

Notice what the shape buys, following D-design-3:
- **Typed `params`/`returns`** — the null implementation and the signature are
  *generated* from these fields; nothing parses a signature string (which broke
  the moment a union type `int | None` appeared in one).
- **`algorithm.steps[].implements`** — the link from code to spec is *data*.
  "Does the code cover the contract?" is `set(steps.implements) vs set(clauses)`
  — a check, not a judge.
- **Ids on every element** — a reviewer's finding, a test, a failure ruling all
  *cite* an id. The joint between every file in the system is the id namespace.
- **The two views fall out for free** — the checker (D3) gets this document with
  the `algorithm` key deleted, so it must derive tests from the *specification*,
  not from the author's intended implementation. No regex, no stripping logic.

**2. The envelope around the produced code — the claim about it.** The code is a
file; the model's *claim* about what it did is JSON the driver checks:

```json
{ "row":  "B-textcell-C015",
  "files": ["src/textcell.py"],
  "units": ["C-015"],
  "steps_covered": ["A-001","A-002"],
  "notes": [ {"about":"the align default","text":"kept '<' to match the contract's stated default"} ] }
```

Checked mechanically: `files` must equal the ownership diff (did it write only
what it owns?); `steps_covered` must equal the row's required steps (is the
implementation complete?). An incomplete or out-of-bounds implementation is a
**set difference, not a guess**.

**3. Code + comment on the code — the idea we used here.** The producing model
writes the code *and* annotates each unit with the spec id it implements
(`# A-003 -> C-023`). That is not decoration: a check can require every step id
in the row's coverage to appear as a comment in the file, tying the artifact to
the specification a second way, and giving the human and the failure-judge a map
from a line of code to the clause it is supposed to satisfy.

**4. The test manifest — kill the last substring match.** The party writing the
tests emits `{ "P-005": "tests/test_textcell.py::test_fit_width" }`. Without it,
the runner matches tests to properties by *substring on the test name* — the
same silent-failure class as parsing markdown. A manifest makes it a lookup.

**The general shape for any code plugin:** a JSON *contract* the code is built
from (typed, id'd, with the implementation plan as structured steps), the code
itself as *files* (validated by execution, not schema), a JSON *envelope*
claiming what was produced (checked against reality), and *id comments* tying
the two together. Every reliability property comes from the JSON around the
code, never from putting the code inside JSON.

---

## How the eight dimensions interlock

They are one system, not five features:

- **D1 makes D3 cheap.** Because every output is structured, most checks are
  code (set differences, schema assertions) and cost nothing. You spend an LLM
  judge only where a field genuinely cannot answer the question.
- **D1 makes D2 possible.** The driver can *generate* the next step from files
  only because the files have a known shape. Prose artifacts would force the
  driver to guess.
- **D2 makes D4 honest.** Because the driver runs every step, it can emit a
  structured trace event as a side effect — the dashboard reads facts the code
  had to record anyway, never a model's self-report.
- **D3 shapes D1.** Where you decide to place a judge determines which fields the
  template must carry (the judge needs exactly its withheld view). Template and
  judge are co-designed (D-design-3).
- **D4 closes the loop on all of them.** The trace is how you see whether the
  driver sequenced right, whether a judge fired, whether an output validated —
  and how you debug the system when it does not.
- **D5 is the counterweight to D2.** D2 pushes authority off the model; some of
  it lands on code, but the irreducible remainder — taste, priority, sign-off —
  must land on the human, not be forced onto a model that will fake a
  confident answer. D5 is how that remainder is collected without burning the
  human's time. Read D2 and D5 together: they partition every decision into
  code / human / model, in that order of preference.
- **D6 threads through D3 and D5.** The review loops (D3) and the gate loops (D5)
  both run for rounds; D6 is the rule that each round carries the exact prior
  trajectory — verbatim inputs, code-computed diffs — so the loop converges instead
  of drifting. It reuses D1 (the inputs are the structured record) and D2 (the diff
  is computed by code), which is why version snapshots are kept: an exact diff needs
  them, and a model's opaque thread memory is never the record.

The unifying instruction: **make the instrumented, checkable, coded path the
only path.** Never leave a second way to do a thing that bypasses the structure,
because that is the way that will be taken on the run that matters.

And the objectives rhyme: **maximize** structure (D1), **minimize** model
authority (D2), **minimize** judges (D3), **minimize** what the dashboard shows
(D4), **minimize** how often and how much you ask the human (D5), **never
summarize** a round (D6) — each
*subject to* still meeting the plugin's goal, and D5 subject to every decision
that is truly the human's still reaching them. Reliability is what you get by
pushing every one of these to its constraint and no further. Pushing
past the constraint is how you get a rigid system that cannot do its job; not
pushing to it is how you get the unreliable one you started with.

---

- **D7 feeds D2 and D4.** The driver's authority (D2) is only as good as its
  signal: a loop that trusts exit codes hands authority back to whatever
  happened inside the process. The trace (D4) is only as timely as its inputs:
  tokens, tool calls and files written arrive per turn from the stream, not
  per process at exit.

## Cost is a design axis, not an afterthought

**Measured (2026-08-29, the ladder).** Three briefs at `rounds` 1, 2, 3, in parallel, Haiku 4.5
`low` / `gpt-5.4-mini` `low`, one clean pass each:

| rounds | demo (1 fn) | slug (1 module) | paths (2 modules, tolerance, phase 4) |
|---|---|---|---|
| 1 | 128k Claude · 55k Codex · 7 min · $0.22 | 166k · 135k · 16 min · $0.43 | 223k · 237k · 13 min · $0.52 |
| 2 | 169k · 158k · 8 min · $0.29 | 397k · 371k · 25 min · $0.78 | 699k · 401k · 27 min · $1.02 |
| 3 | 305k · 123k · 14 min · $0.39 | 481k · 294k · 26 min · $0.69 | 663k · 389k · 34 min · $1.37 |

The unit of cost is a review round that is actually spent: one Codex review plus one Claude
arbitration that re-emits the whole artifact. `rounds` caps it; APPROVED ends it early, which is
why a 3 can come in under a 2. The waste table in every `REPORT.md` shows the refused answers
(the tool-boundary refusals a weak model pays for) per call.

For a real plugin, tokens and wall-clock are a hard budget, and several
dimensions above are also *cost* mechanisms — worth seeing as one concern rather
than a happy accident:

- **Render, don't re-read (D1).** Passing one model's output to the next as a
  code-rendered view costs nothing; having a model re-read and re-summarize costs
  a call and risks drift. Every JSON-to-markdown render is a call you did not
  make.
- **Cheap checks before expensive ones (D3 / the verification ladder).** Code
  checks are free and deterministic; AI judges cost a call and are the least
  reliable. Run every mechanical check first and let it gate; only pay for a
  judge on the questions no field can answer. A schema that lets code catch a
  failure for free is a judge you never spend.
- **Bounded loops (D2).** Every review, coverage, and fix loop has a cap, and at
  the cap it *carries* rather than spinning — so a pathological run cannot burn
  an unbounded number of calls. The cap is a cost ceiling as much as a
  convergence rule.
- **Fewer, batched human touches (D5).** The human's time is the most expensive
  budget of all; batching and exception-only escalation spend it deliberately.
- **The dry-run (D2).** Validating the whole sequence with no model at all turns
  a class of bug that used to cost a full multi-phase run into a one-second check.

Make the model's tier — the expensive, least-reliable one — do the least work
that only it can do. That single instruction serves cost and reliability at once,
which is why they are the same design and not a tradeoff.

- **The three speed levers (2026-08-29), and why none is a knob.** Measured on
  the streams: tool I/O is ~1 % of a call, code ~0 %; a call is *turns ×
  (latency + thinking)* -- 3.4 s per turn, 61 % of it thinking-only turns, 26 %
  writing the artifact, 35-75 turns per author. So: (1) **inline the inputs** --
  the prompt carries the rendered content, not paths, and the author never
  spends a turn reading (always on; no setting could make paths better);
  (2) **thinking per kind of author** -- off where every mistake is caught by a
  check (plan, contract, implementer, arbitrations), "low" where the agent's
  value is judgment (the ruler, the coverage reviewer); a constant in
  `config.THINKING`, shown on every agent row; (3) **one turn budget**
  (`config.MAX_TURNS = 3`: an author with no tools answers once, the room is
  for the structured call's own retry) -- a runaway guard, not a performance
  dial: hitting it halts with the last facts, it never truncates quietly. Tuned wrong, (2) shows up as check refusals and retries in the
  trace and (3) as a visible halt -- neither can degrade a run silently, which
  is the property that lets them be constants.
- **Measured, not estimated (2026-08-28).** A one-function block end to end
  with Haiku 4.5 (low) as every author and gpt-5.4-mini (low, fast) as every
  reviewer: ~$0.70 and ~40 min of model work. The single largest cost before
  the loop became code was the orchestrating model itself (Opus deciding each
  step: ~$7 of a $12 run). Tokens are dominated by *turns*, not text -- an
  author re-reads its context on every tool call -- so fewer tool calls per
  author (the rules in the template, no exploring) is the first lever; smaller
  artifacts (a clause budget tied to the surface) is the second.

## Smells — quick reliability tells
- **A step whose only signal is its exit code.** A process that has gone wrong
  keeps running and exits 0; if code cannot tell before the end, the stream is
  not being read.

Scan your own system for these. Each is a specific dimension being violated, and
each was a real bug on this project before it was a rule:

| smell | the fix, and which dimension |
|---|---|
| a **model deciding when a loop stops**, or which script runs next, or which flag to pass | move it to the coded driver (D2). A model choosing sequencing from memory was 10 of this project's 12 bugs |
| a **markdown (or free-text) artifact that a script parses** with a regex | make it JSON; render markdown only as a view (D1). Two bugs here: profile sections invisible, a `\|` truncating a signature |
| a **raw id (`C-051`) in anything a human reads** | resolve it to plain words in the render (D1). A human should never see the machine's pointers |
| a **binary pass/fail from an AI checker** | grade it by severity with reasoning; route by the grade (D-design-5). A boolean cannot tell you who should handle the finding |
| a **scheduled "review the results" gate** that stops every run | present by default; escalate only on a fatal finding (D5). A gate with nothing to decide is a notification, not a gate |
| an **AI running its own tests** / checking its own work | code runs the tests; a different agent checks a frozen, withheld copy (D3). Self-checking rationalizes |
| a **fixed phase that fires even when it has nothing to do** (e.g. asking for tolerances an exact spec has none of) | generate it from state; emit no step when there is nothing (D2 + D5) |
| **state that lives in the model's context** (a round counter, "where we are") | put it on disk; derive the next step from files (D2). Otherwise an interruption loses everything |
| a **run that ends with a report explaining why it stopped, but nothing built** | bound every loop to carry, not halt; a stop should be an honest "can't be done," not a giving-up (D2 + D4) |
| **waiting on the human as a prose paragraph** with no popup | a definite question with options and a recommendation (D5). Prose waiting reads as a dead run |
| a **verdict shown as one "healthy" light** | split *did the flow run* (process) from *is the output right* (product) (D4). They fail independently and need opposite fixes |

If none of these appear in your system, you have probably internalized the eight
dimensions. If several do, start with the coded driver (D2) and JSON outputs
(D1) — they remove the largest classes at once.

---

- **A guide and a check that disagree.** The model did what the template
  said; the check refused it. The template is the bug.
- **A step whose only signal is its exit code.** A process that has gone
  wrong keeps running and exits 0.
- **A cap that fires before the first review.** Count the loops, not the
  checks.
- **A "fresh run" that `git clean` cannot produce.** Runs commit into the
  repository; fresh means reset to the commit before the run.
- **An author reading the plugin's scripts.** It is looking for a rule the
  guide should have stated.

## Build order

You cannot design everything at once, and the dependencies are real. Recommended
order, with the reason each precedes the next:

1. **The workflow as data first** — the phase/step sequence (D2) and the JSON
   schemas (D1), designed together with judge placement (D3/D-design-3). This is
   the skeleton; everything else attaches to it. Prove it with a dry-run before
   any model is involved.
2. **The checks and freezes** — once the schemas exist, the mechanical checks
   are code you can write and test immediately, and the judge points are now
   visible (they are the questions no field answers).
3. **The prompt templates and their guides** — a template exists to produce a
   specific JSON template at a specific step, filled by code from the rendered
   inputs and handed to a fresh process. You cannot write one until you know
   what step it serves and what JSON it must return; they follow the workflow.
   (Skills -- prose a model must read and remember -- are what this replaced.)
4. **The MCPs / external tools** — an MCP exists to give the driver a capability
   local code lacks. You add one only when a `RUN` step needs
   something code cannot do locally. MCPs follow the skills. *(Also a separate
   document.)*
5. **The stream reader (D7)** — comes with the driver, before the dashboard:
   every process wait in the driver pulls its stream (liveness, scope, tokens,
   the last facts), and the dashboard then reads facts that already exist.
6. **The dashboard (D4)** — build it against the trace the driver already emits.
   It can come early for your own debugging, but its *final* shape depends on
   knowing which stages and signals matter, which you only know once the
   workflow is real.

**Direct answer to "design everything together, or in order?":** in order.
Workflow → checks → skills → MCPs → dashboard. Designing them together fails
because skills and MCPs are *shaped by* the workflow's needs — a skill is "fill
this template at this step," an MCP is "provide this capability to this step."
Design those needs first (the workflow and its JSON), and the skills and MCPs
fall out of them almost mechanically. The one thing worth sketching up front,
across all of it, is the **id namespace** — the ids are the joints between every
JSON file, so decide them once, globally, before writing any schema.

---

## Companion documents (to be written)

- **Prompt templates and guides** — how to write the template a fresh process
  is handed so that it can only produce its JSON: the guide as the spec, the
  example per field, the checks co-designed with it, the failure modes seen.
- **Backends** — the CLI and the Agent SDK as interchangeable ways to run an
  author, and what the stream reader needs from each.
- **MCPs** — when a capability justifies an external tool over local code, and
  how to keep an MCP from becoming an unchecked side channel that violates the
  "instrumented path is the only path" rule.

---

*Source project: freeze-and-swap. Every claim here traces to a failure or a fix
on its live runs; see `docs/ROADMAP.md` for the concrete migration this
methodology is driving, and `DESIGN.md` for the freeze-and-swap rationale in
full.*
