# code_steer_model_write — read this first

## The 14 universal rules

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
    spent. Tool denial is stated as fact in the prompt and enforced by the runtime.
14. **Cost is a design axis.** No unused tools, thinking off where a check catches every
    mistake, calls batched, tokens as the honest measure.

Every module docstring, check and walk leg cites the rule number it enforces.

## Working rules in this repo

- **This repository is the template.** Never create a specific workflow or project inside it.
  A project is scaffolded into its own repo outside this one (`copier copy`); only what
  belongs to every project (runtime, recipes, checks, docs) is committed here.

- The design is `docs/PLAN.md`. Read the section you are touching before changing it.
- The verbs are the `justfile`: `just doctor|walk|test|run|resume|dash|selfcheck|figure|new-recipe`.
- `csmw walk --all` before any live run; `bash scripts/run.sh` is the full offline suite.
- Never edit the package while a run lives — every step re-imports it.
- Before any fix: classify the bug against the classes in `docs/BUG-LEDGER.md`; fix the
  mechanism behind the class, never the instance. Code first, never the prompt.
- Raw ids (`C-012`, `F-003`) never reach a human; `render_md(audience="human")` resolves them.
- Add a recipe by `csmw new-recipe <name>`, then `spec.py` → fixtures → prompts →
  `csmw walk <name>` green **before** any prompt tuning. See `docs/ADD-A-RECIPE.md`.
- When a check fails live, first ask whether the prompt's guide could have produced anything
  else; a guide and a check that disagree means the template is the bug.
- Never add a dashboard signal that does not answer where / healthy / remaining / cost.
- Every colour, size and spacing on the page and in the figure is a token in
  `dashboard/theme.py`; no literal in a component.
- Tokens, never dollars, are the measure of cost.
- Done means one run start to finish with no halt, no resume, no fix along the way. The run's
  verdict (failing tests, carried findings) is a result, not a bug.

- The seams are `code_steer_model_write/layers/` (ARCHITECTURE.md section 6 in
  `production_agentic_workflow`): a check or a step never shells out, reads a policy or judges
  content directly; it goes through `layers.current()`. A tool is chosen behind an interface.
- Live runs use the CLI logins (`claude_cli`, `codex_cli`, `CSMW_CLI_USE_LOGIN=1`, the shell's
  `ANTHROPIC_API_KEY` unset), never API keys. The `pydantic_ai` backend exists for deployments
  that have keys.
- Version 3 (2026-09-04): all ten layers are live behind their seams -- `docs/PLAN.md`,
  "Version 3", holds the phase record and every live pass. The container tier needs an engine
  (`brew install colima docker && colima start`) and the image (`csmw sandbox build`); without
  them the subprocess tier runs and the record says so. Prefect as the runner needs `prefect
  server start` and `csmw gateway prefect serve`; the walk needs neither. Everything a step
  checks lives under the run folder (`paths.staging()`), never the system temp.
