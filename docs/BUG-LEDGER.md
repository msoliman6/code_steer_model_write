# Bug ledger

Every bug a run flushes out goes here, classified. **Before any fix: classify against the classes
below; fix the mechanism behind the class, never the instance** (CLAUDE.md). A second instance of a
once-only class promotes it to a heading of its own.

## Rows

| date | where | what happened | class | fix |
|---|---|---|---|---|
| 09-04 | live-3 / contract-arbitrate-r1 | the model nested its answer under an extra `artifact` key; `claude -p` validated it itself, re-prompted three times, hit `--max-turns` and reported `error_max_turns` with no answer; the run halted `backend` and the runtime's validator never saw the answer | a refusal with no re-ask (two validators: the CLI's ran first and dropped the answer); also a policy that cannot tell progress from repetition (the CLI's retries), a message that hides the reason (the halt said `max_turns`, not the schema problems) | the backend keeps every `StructuredOutput` input and, when the CLI ends in `error_max_turns` or `error_max_structured_output_retries`, returns the last one as the answer; the one validator refuses it with its own problems, the re-ask inlines them, and stops on repetition (`backends/cli.py`) |
| 09-04 | live-3 / the same call | the failed result line carried usage the parser dropped, so the halt's call had zero tokens | an accounting path skipped on one exit | the usage fact is emitted on every result line, `is_error` included (`backends/cli.py`) |

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
