# Bug ledger

Every bug a run flushes out goes here, classified. **Before any fix: classify against the classes
below; fix the mechanism behind the class, never the instance** (CLAUDE.md). A second instance of a
once-only class promotes it to a heading of its own.

## Rows

| date | where | what happened | class | fix |
|---|---|---|---|---|
| 09-04 | live-3 / contract-arbitrate-r1 | the model nested its answer under an extra `artifact` key; `claude -p` validated it itself, re-prompted three times, hit `--max-turns` and reported `error_max_turns` with no answer; the run halted `backend` and the runtime's validator never saw the answer | a refusal with no re-ask (two validators: the CLI's ran first and dropped the answer); also a policy that cannot tell progress from repetition (the CLI's retries), a message that hides the reason (the halt said `max_turns`, not the schema problems) | the backend keeps every `StructuredOutput` input and, when the CLI ends in `error_max_turns` or `error_max_structured_output_retries`, returns the last one as the answer; the one validator refuses it with its own problems, the re-ask inlines them, and stops on repetition (`backends/cli.py`) |
| 09-04 | live-3 / the same call | the failed result line carried usage the parser dropped, so the halt's call had zero tokens | an accounting path skipped on one exit | the usage fact is emitted on every result line, `is_error` included (`backends/cli.py`) |
| 09-04 | live-4 / p4-verify-1 (and live-1, live-2 before it) | every property recorded `missing` though the tests pass by hand: pytest wrote its JUnit file to a *relative* path resolved against its own cwd (`build/`), the check looked for it against the process cwd, so the file was never found | a path compared by two conventions | every path the pytest tool is handed is resolved to one canonical, absolute form before it crosses the seam, and the check reads the same form (`layers/tools.py`, `checks/runtests.py`); section 4's added L7 invariant |
| 09-04 | live-4 / p3-implement attempt 1 | a schema-refused answer was re-asked correctly but recorded no `rail.verdict`, so the walk's layer assertion failed on the live record ("an answer had no verdict") | a fact with no owner (the schema refusal was a refusal the rail never recorded) | `Rails.schema_refused()` records the validator's refusal as an after_answer verdict; every answer now has one (`layers/rails.py`, `ask.py`) |
| 09-04 | live-5 / p4-verify-1 | every property `missing` again, with the JUnit files now in the right place: pytest discovered its rootdir at the coder repo's `pyproject.toml` and prefixed the class names `runs.live-5.build.tests…`, and Codex parametrized its tests so every name carried `[case]`; the manifest has neither, so nothing matched. Recomputed with canonical ids the run was 8/8 pass, 7/8 fail on the null, one vacuous property | a path compared by two conventions (a node id this time: rootdir-relative and parametrized vs build-relative and bare) | `--rootdir` stated to pytest, never discovered; `canonical_id()` reduces both sides to `tests/x.py::bare_name` and a property aggregates over its parameter cases (`checks/runtests.py`, `layers/tools.py`) |
| 09-04 | phase 5, the walk | with two steps in threads, the MLflow mirror's worker-thread writes opened new MLflow runs (three runs for one walk): `mlflow.log_metric` with no active run in that thread starts one | a second owner of a fact (the run id lived in thread-local state) | every mirror write names the run id through `MlflowClient` (`observability/mlflow_bridge.py`) |
| 09-04 | phase 5, the walk | the layer assertion paired `tool.called` with `tool.result` by position; parallel steps interleave them | a message parsed by position | paired by `gen_ai.tool.call.id` (`walk.py`) |
| 09-04 | phase 5, before any parallel run | the driver loaded `state.json`, mutated it, and only the write was under the lock; two steps finishing together would lose a record | a shared record written by parallel workers | `RunState.update()`: load, mutate, write under one lock; every writer uses it (`state/run.py`, `driver/driver.py`, `driver/runner.py`) |
| 09-04 | the page / closed tabs came back | the poll's refresh rebuilt the tab list without the hidden filter; `close_run` recorded the close and a tick later it was undone | a second owner of a fact | one `_visible_runs()` feeds both the page load and the poll (`dashboard/dashboard.py`) |
| 09-04 | the page / the rail on /new | the rail's view rows set a view tab that the /new page never rendered, so the page did not move | an effect with no owner | on any page but the run page the rows are links home and set the view (`dashboard/dashboard.py`) |
| 09-04 | live-8 / Prefect's page | the flow run showed no task runs: the served flow drove the run through the Runner's loop, while `drive_with_prefect` kept a second loop of its own that made task runs; the two had drifted (the served one had no per-step view, the older one no STOP check) | a second owner of a fact (the drive loop) | one loop in the Runner; a `round_executor` hook that Prefect fills so every ready step is a task run named after the step; both flow entry points use it (`driver/runner.py`, `workflow/flows.py`) |
| 09-04 | the page / layout, three rows | tabs wrapped to a second line; the elapsed time collided with "at API rates"; the step key overflowed into the pill; the pill column sized to content so tokens and status zigzagged | (layout, no class) a value not read from the widest thing it must hold | one-row tab strip that clips and scrolls; time beside the percentage; the key column fits the longest key with an ellipsis guard; the pill column one fixed width (`dashboard/dashboard.py`) |

## The classes, and the mechanism behind each
- **a second owner of a fact** — two places compute the same thing (a validator beside the spec, a
  glob beside the record, a field list beside the spec). Fix: one owner, the rest derive.
- **an exit code that lies** — 0/1/2 not meaning done/record/refusal. Fix: honest codes, one reader.
- **a message that hides the reason** — the halt carries a code, an info line, or nothing. Fix:
  the reason text travels to the halt and to the re-ask.
- **state left by an earlier run or step** — git worktrees, branches, files with the old shape.
  Fix: the step that needs the state clean makes it clean, and says so.
- **the model with more freedom than the answer needs** — tools, MCP, shell, paths. Fix: nothing
  but the answer, enforced by the harness, measured in the streams.
- **liveness from the wrong signal** — a retry or a heartbeat that is not the model. Fix: only
  the model's own facts count; a watchdog that does not depend on the message loop.
- **a check that contradicts the artifact's own rule** — the check encodes a guess, not the
  artifact's definition. Fix: the check reads the rule the guide states.
- **a step issued with nothing to do** — the empty set (zero findings, zero failing tests) reaches a
  step built for one or more. Fix: the generator asks "is there anything" before issuing; the schema
  allows the empty answer; the offline walk carries the empty case.
- **a shared record written by parallel workers** — two loops or threads read-modify-write one
  file. Fix: one writer at a time (a lock), never a smaller window.
- **a message parsed by position** — a stream read by "the first `[`" or "the last line".
  Fix: one channel for data (JSON on stdout), notes elsewhere, strict parse, raw text in the halt.
- **a path the walk cannot reach** — a branch only a live run enters (a refusal, a halt, a revise,
  a verdict route), so every fix on it ships unproven. Fix: a fake knob that steers into the branch,
  and a leg that asserts from the runner's log that the branch ran exactly as the rule says.
- **an effect before the acceptance** (also written: a check that runs after the effect it guards) — a
  file written, a decision recorded, an event fired from an answer not yet accepted; a refused answer
  then leaves its trace behind. Fix: stage, check, then `os.replace` into place; the recording is the
  LAST check and the first refusal short-circuits before it.
- **a fact / an effect with no owner** (also: a promise enforced only by prose) — a setting recorded and
  enforced nowhere, content computed and delivered nowhere, a rule stated in a doc no code reads. Fix:
  name the owner; the owner enforces or halts; prose derives from it.
- **a refusal with no re-ask** — a model call outside the author loop (a RUN step) whose bad answer is
  recorded, not re-asked. Fix: every model call is an author step with a schema; the ingest is its check.
- **a check that reads the pattern, not the record** (also: a check that reads the wrong record) — a
  check that greps a shape, consults the active run instead of the block's, or runs `git diff` in the
  wrong tree. Fix: the check takes the record's path explicitly; a missing record halts.
- **a policy that cannot tell progress from repetition** — a flat attempt cap, a retry that counts.
  Fix: stop when the problem set repeats, not at a number.
- **a path compared by two conventions** — absolute vs relative, symlinked vs real, `./x` vs `x`. Fix:
  one normaliser at the edge, every comparison on its output.
- **the guide not where the model reads it** (also: a check stricter than the artifact's rule) — a rule
  only a check knew, a template not in the prompt. Fix: the guide travels in the prompt; the check
  cites the guide's words.
- **a call site changed without its definition** (also: a step's contract not carried over by the new
  path; a flag assumed on both branches of a command; a reader assuming the old shape; state that
  exists only later, named as if always) — a rename or a new path the callers and readers did not
  follow. Fix: one owner of the shape; a selftest that runs every call site.
- **once-only classes** (one row each; a second instance promotes it to a heading of its own): a record
  overwritten; an accounting path skipped on one exit; an input not validated by its kind; a name
  shadowed inside a function; the re-ask carries the verdict, not the artifact it judged.


The class list is imported from freeze-and-swap's ledger (msoliman6, MIT), which grew it over
four hundred commits; a class that never fires here is still a class.
