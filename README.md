<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/banner-dark.svg">
<img src="docs/media/banner.svg" alt="Code steers, models write" width="720">
</picture></p>

<p align="center"><b>Code steers, models write: a template for agentic AI workflows that are versatile, reliable and fast to start.</b></p>

<p align="center">
<a href="LICENSE"><img alt="license: MIT" src="https://img.shields.io/badge/license-MIT-d4a72c?style=flat-square"></a>
<a href="https://www.python.org/"><img alt="python: 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white"></a>
<a href="https://docs.pydantic.dev/"><img alt="schemas: pydantic v2" src="https://img.shields.io/badge/schemas-pydantic%20v2-E92063?style=flat-square&logo=pydantic&logoColor=white"></a>
<a href="https://www.prefect.io/"><img alt="orchestration: prefect" src="https://img.shields.io/badge/orchestration-prefect-4f46e5?style=flat-square&logo=prefect&logoColor=white"></a>
<a href="https://mlflow.org/"><img alt="traces and evals: mlflow" src="https://img.shields.io/badge/traces%20and%20evals-mlflow-0194E2?style=flat-square&logo=mlflow&logoColor=white"></a>
<a href="https://reflex.dev/"><img alt="dashboard: reflex" src="https://img.shields.io/badge/dashboard-reflex-5646ED?style=flat-square&logo=reflex&logoColor=white"></a>
</p>
<p align="center">
<a href="https://docs.astral.sh/ruff/"><img alt="code check: ruff" src="https://img.shields.io/badge/code%20check-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black"></a>
<a href="https://github.com/microsoft/pyright"><img alt="code check: pyright" src="https://img.shields.io/badge/code%20check-pyright-1E90FF?style=flat-square&logoSize=auto&logo=data%3Aimage%2Fpng%3Bbase64%2CiVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAEZUlEQVR42q2XS2hdVRSGv3XOyW2vTWpbbWOTRokPqC1ixIkPKDhRcVwHgg6dOXCgA0eOFHGiE4VOFEEF8UHxBYoDwYkdWRVDhQ7EmrSxJjfXJjfNfZzloP%2BWlePNzU1ww%2BHec%2FZj%2Fetf%2F1p7b9hGc%2FdMv%2BPu%2FpW7v%2BjuE6E%2Fd3fbzpq2HeNmVrr7IeBl4A5gP3AZ%2BBJ438wuJiBAaWb%2BvwAIxseAN4ASGAGmgavADUAT%2BAx4z8zmhwViQxg3M3N33w28CtwILAAHgKPAlQBon96HBmJbGdeYEeAVYBK4COzS97vEQGpdoFBo%2FgY%2BrwCxKgjbyriofwm4E7gg4wA94LjW6FbW6gZGmsCnwNtm1qiCyAbpQ8ZfAI4BvwE54AHAmjyuUpu%2BXdbvk8BH7j4Ts2lTAEF0zwP3AedF66EKe62wRj82E5BLwEHgpLy3TQG4ewGYuz8BnADmxcBhYByoBY9bComLdt8EyG6gAdzr7nuumblWL7LotTzvmlkPeFQTpyWoc8AiUAc6AnJcnk2JoSIAia1UuA4DM2ZWJqBFUGep%2F9PAyZBuDQ2O8c%2BBBxSSrsRWB67TewNoa14RsqYAnnL3eWAOaFvI82PA48DdWmQhTErK3q8wTKoOLAHLEtufMvSQAF5RXxtY0f9VMXcbcMrM3ilk%2FBngYU2aF2W1FJ2glxZwvUT1g8avB8Gtab7LgWS0G1hsAPendE7ejStfF9WR94ljyvczSsFcoGqhvycAKwJQ6Ht61rWHTAr8vwC%2BV1VrDLE1FGGeB6AuUEvAPcAton9dv2sac1TvGwD8LPTZMHvTgL5MlDfFZKlMSozulVjbAkqmfJwD%2FtJgZ2ct0ewq2VnwfFWp3AlOlAlxprw%2FD4yKiZ0Y7oruutJzNK2vJ9eTxq7EEAD8BDwYqpkPcY4o5VWmFJ0CJoA98n5E%2FRbqRyZWlhOAUp0%2FalI%2BwLiFjainOE8AN6twpUp4VcbHFNpMc7MAvARIdcCUNgtCv1YRZGIkxXAMOKJnb9gL2sFQqb7lSi0xrd%2BKIcjMrOfus6pkq2IielsAN8nbcXmfjEYtJJFl4VsZ3lOV3KCBhPAs8EjwqBQjk4rvPi3SkeCsz%2B6X6kEH%2BEPgLTCzQWNVAL%2BKGlNMp7SD1bVQp4%2B3%2FYy3ZbwbwpGM7gJ%2BEeN5oaOPaytecvcm8JgWqoX02uoMmYyvB8%2BzSvwLOfhampP1OQeeUkHKtJgP8Di2XOL6PaSeV84EB3R%2FmHX33MzKLBwAS4nxLPBsUPewxagl47l0k9K5p5AU2uxel6P%2BnyOZ4lKY2YfAm9JBZ4DhUiFC3s0obBfERl2XloPA7cBbZjYnR8u%2BMRW6lDKfqDouVwSbRFXX09SO%2BjHwjZktuvtoMD4B3Aq8KxZIR3Pb4lR8BPhaZXZN42uiuAfMAl8Ap83s3E53sM0uJrlCcgL4IBSRS8C3wGngOzNrV5grQ3W1Str2hrmwVo%2FouPtz7n7G3Z%2BO1%2FE0Jl40ttv%2BAbe8BGG9m5lPAAAAAElFTkSuQmCC"></a>
<a href="https://docs.pytest.org/"><img alt="verification: pytest" src="https://img.shields.io/badge/verification-pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white"></a>
<a href="https://www.sqlite.org/"><img alt="ui state: sqlite" src="https://img.shields.io/badge/ui%20state-sqlite-003B57?style=flat-square&logo=sqlite&logoColor=white"></a>
<a href="https://docs.litellm.ai/"><img alt="any provider: litellm" src="https://img.shields.io/badge/any%20provider-litellm-555?style=flat-square&logo=data%3Aimage%2Fpng%3Bbase64%2CiVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAHzUlEQVR42uWXXYydRRnHf8%2FMvOc95%2Bw5%2B93t0gL1g1JIDAZL7AViKH4EbwQuSpSEC6NckKgXRBIvwNMaY8SISY0xMcQYIzSxJSAmaEFwwRiFpALyJZgWdVvabXfb7fnYc96PmXm8OLul0SIE5cI4ydzMO%2B%2F8Z%2F7P1%2F%2BB%2F6ehqqKq0mq1jGrLqKp5F8FaZm5uzqnOOdW9VkTOuU%2FeBWwB9Fwfdu%2FenU5PTzfTNB2ZmRlLG43U%2Fdcu0Gq1DFdfbXZt3%2B4BXn31hUuThCu8j5ephouKIr%2BwKIvJxJmxGLUGJN6XKv%2BpTfftw9y4g4iIAnzrSzecf8G2T93fGKlvHZ8Yc2maYp1ldmYdU9OzDPIcAUSELCtK906Bd%2B58woqIBwLAfffdt%2FlwnLzm%2BOmVHX95Pd%2B2vNzBx06wIuoVGR85KLdd%2F0Hes3FWBnmBtYYsG%2BDeyYtFJAB%2B8Xc%2Fb95%2FvHnDYqY3P5PFq0LSSP3oGCONGKYuSEzFOesSh7OOfhF5%2BKUFbqwa6rU6ee7JsuztX2Dv3r12FTj84aE965%2FqT3%2FhuwfNLaWtbcJY6k1hslkLE406aSWxYChLT3%2BQ0ev18dmAhbaw98l5rtu2DmMtRVG8dRSoqhFQRFSf%2BunoPcc2fnG%2Bo1%2FOksZ6Zw1TjWqYbNaoiDFFnku312PQbVMOOlBmOAmkLqGaVqjXEmpphUve22S0USXL8jf3AVWVJ54Y2tkCDz76%2BM1fP8idy1rfXMbAqIgfs2qTrG1X%2BifwxlNPlM2jFdZdOMJEc5pGvUZarZI4i3MOYywglF5ReHMTnEW3f%2B65ly5%2FfqH77UcP5x8%2FueKZqnb9hWPWbmwWbqZpmBmrMj46PgRLU6x1IJaoBlVBEUQMWZHjfQ4iqEZG6g0q6ci%2FmmBubs5t377d79%2F%2F%2B8nZWb3jVLtz6ytLUj2dETavr8r7Zmpm3VidkVoVm6QYk4BYxFisdVhrETEkzgLmTG7qdo5SrdYBIQSPMYKzlVLOplx27hR27YoHnnryk7jy%2B9bq5jzPWTcxFer1uk2SKsZVEVvBugqJS7DWYq1ZO4MQIs5FXni1w9%2BPZqAlZVlAOMV5s%2BvQGAhR6XRzOu2VoQ%2B0Wi0jItFa0Ucf%2F9XOaPotAyRJ009MnGcrac1W0hpJkpIkCc5aAGIMlGXGYOAJweO9p5Iohw4PuGP3UfqZJ%2Fo%2BvughYYnR8Qk0elAoipKlxUVcq9Uyu3btirr87Phnbv%2FNj0%2B18%2Bs3bJiMaTpOo9F0aTpCpZIiIsQYKYuMgS%2FxviQET4wBVUVRNEIMcO9DCxRFwdhIpCwChQQolcQKEYOIYoBGGoc%2B8OsHfjL1o%2F3tRw4ec1vvvHWL337lZhd1%2BNoQPGVZUJY53pfEGIgxAorqkHZQfIg0aobfHjjND%2FacoFYFXxYEn%2BGLAZSnaIyvIwSPxpLoPcunlkp34Bc%2FrN%2B5Z%2BGBvrlg6%2FjUaDk1NZNY6%2Bi2O%2FhygPcFIQRiVCAS4zCEVHV1DteMKN1O5P5fHoFQkPcDMXiizymLAaE4jUsswZeggahKWazgvnbviXsGdtNHR5sNPxj0k8XF1zl8eJleL0NdZRizOqQ5qiIoJgyIMZ4BjzFSTYWfPXyKl%2F58knpVKAtPVI8GT1n0ieVJQgCNkRgLEEunfRp3apDcVB0ZxNOLS67b7bGwsJ7p0Qa9geKPPs%2Bo6aOuBjGClmRe6I9fjDGsXkIRgSz3LBxbZvP5gkhA8KhGVAPRB7odz0ijJOrwqCSxTI85XGf5CL32gloj5IVn8XjkaKNCb6Ak7ZOYSoHYAWhAtKBfwlLZXPWBISuJE5790zE6y%2BCsIcQARNChLgnBE%2FKTlHawGvOREEcoByu4fOXEg0We3%2BCLXkQqcX6%2Bb1KXii%2BjqGtwaIXhYcMqjhGwnSVCiMQYz7Aw2oh84GJB1Q8Fkb4huKI6VnpNqtUKa8rMuYQ8r%2BM%2B8ulbb%2FrjY3u%2B1%2B8lt2T9tul1uywuDijLoALRWqPWWgFsiBHvAzGyCv6GQxpZS2hDXFkNzbU1gWFCWt0%2FGGSEEPyZTHjNjXdt7y4f%2Fdy2S8urNs6aWYSqcwZjDCEEVnodskFOCBGEIbies4ihKiCGYT0RFcGIiNGzfhARvPervA5nBLj77rtr9XqxPsva58Wos1idbC91Lnnltey2vBSxiZGgQvQRCBhZe6kiRFBIrKfm%2BgoqPgSyLCfPC40xioio90GMke6WLZt2n2Fgx44ddh%2FAvn3hn1%2B19crPP7ic1a8T66JYTPAlMXhgGIrEMLyADIvddPo3P1HPKu3e4LEiKx7JB9lnrbUfKr0vUZWy9JIX5cLrCyfOP5cgkVarJS%2B%2FjNu7F3%2Flx458pecn7yqDV1epiBEwRMwZ5a1DVxPBiCPVvzLTPM7xxfaJF158bUu73T69acOGyycnxw5MT06YGAKl9yycWPrON%2B768Ffl32h71q%2B%2FrD668YqnXdp8v7FRrXHGGkMlcSSJxVqLEQMaVYyVImv3sqW5hUoS548vnr7j0KH5Z6699qJ0%2F%2F6D%2BXkzM5%2BYHB%2B73Tkz1e2tPPTa%2FJFvAuGtJJnZcMn1E41KGBUpFKpUq1CtVs9syABTlBqcNXF5vv%2Fii08vrvnTWU3KmzYr70pj1Gq1zFlqZG3Y1bLPDrBrLMvba7Vab7OB2fWGY%2FyvjH8AcURzkt6vUdYAAAAASUVORK5CYII%3D"></a>
</p>
<p align="center">
<a href="https://docs.anthropic.com/en/docs/claude-code"><img alt="Claude Code: author" src="https://img.shields.io/badge/Claude_Code-author-d97757?style=flat-square"></a>
<a href="https://openai.com/codex/"><img alt="OpenAI Codex: adversarial checker" src="https://img.shields.io/badge/OpenAI_Codex-adversarial%20checker-10a37f?style=flat-square"></a>
<a href="https://github.com/anthropics/anthropic-sdk-python"><img alt="Anthropic SDK" src="https://img.shields.io/badge/Anthropic_SDK-backend-d97757?style=flat-square"></a>
<a href="https://github.com/anthropics/claude-agent-sdk-python"><img alt="Claude Agent SDK" src="https://img.shields.io/badge/Claude_Agent_SDK-backend-d97757?style=flat-square"></a>
<a href="https://docs.anthropic.com/en/docs/claude-code"><img alt="Claude Code CLI" src="https://img.shields.io/badge/Claude_Code_CLI-backend-d97757?style=flat-square"></a>
<a href="https://github.com/openai/codex"><img alt="OpenAI Codex CLI" src="https://img.shields.io/badge/OpenAI_Codex_CLI-backend-10a37f?style=flat-square"></a>
</p>

<p align="center"><a href="#the-14-universal-rules">The 14 rules</a> · <a href="#the-workflow">The workflow</a> · <a href="#the-harness">The harness</a> · <a href="#install">Install</a> · <a href="#first-run">First run</a> · <a href="#settings-you-choose-once">Settings</a> · <a href="#read-more">Read more</a></p>

<p align="center">
<a href="docs/PLAN.md"><img alt="docs: the plan" src="https://img.shields.io/badge/docs-the%20plan-30363d?style=flat-square"></a>
<a href="docs/QUICKSTART.md"><img alt="docs: quick start" src="https://img.shields.io/badge/docs-quick%20start-30363d?style=flat-square"></a>
<a href="docs/HACKATHON-30MIN.md"><img alt="docs: hackathon in 30 min" src="https://img.shields.io/badge/docs-hackathon%20in%2030%20min-30363d?style=flat-square"></a>
<a href="docs/ADD-A-RECIPE.md"><img alt="docs: add a recipe" src="https://img.shields.io/badge/docs-add%20a%20recipe-30363d?style=flat-square"></a>
<a href="docs/DASHBOARD-DESIGN.md"><img alt="docs: dashboard design" src="https://img.shields.io/badge/docs-dashboard%20design-30363d?style=flat-square"></a>
</p>

<p align="center"><i>Independent open-source project. Not affiliated with or endorsed by Anthropic or OpenAI.<br>Claude and Claude Code are trademarks of Anthropic; Codex and GPT are trademarks of OpenAI. Prefect, MLflow, Reflex, ruff, pyright and pytest belong to their owners.</i></p>

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
    spent. Tool denial is stated as fact in the prompt and enforced by the harness.
14. **Cost is a design axis.** No unused tools, thinking off where a check catches every
    mistake, calls batched, tokens as the honest measure.

## This is a template, not a project

Do not build a specific workflow inside this repository. It holds the runtime, the recipes and
the rules; a project is a **separate repo** scaffolded from it:

```bash
copier copy gh:<you>/code_steer_model_write ../my-workflow    # a new repo outside this one
cd ../my-workflow && csmw doctor
```

Your workflow's brief, task specs, prompts, fixtures and runs live there. Changes that belong
to everyone -- a new recipe, a fixed check, a better renderer -- come back here as a commit;
`copier update` carries them into every project.

## What it is

A Python package (`code_steer_model_write`, CLI `csmw`) plus recipes. A **recipe** declares a
workflow as data: stages, who authors and who checks each one, the pydantic schema every model
answer must fit, the code checks, the human gates, the evaluations. A coded driver runs it,
resumable from disk, with one append-only event log, a Prefect flow around it, MLflow traces
and evals beside it, and a Reflex dashboard on top. Four backends sit behind one `ask()`:
the Anthropic SDK, the Claude Agent SDK, LiteLLM, and the `claude` / `codex` CLIs — plus a
fake backend that walks the whole pipeline offline with zero tokens.

Recipes in the box: **code-builder** (plan → contract → freeze → tests by one model, source by
the other → null run → verify → triage; walked offline on 10 legs, proven live on `claude -p` +
`codex exec`) and **debate** (hypotheses → support vs challenge → rebuttal by id → a fresh judge
on a rubric; walked offline, unproven live). The research and tool-assistant recipes are
designed in `docs/PLAN.md` §5.2 and not built yet; `just new-recipe` is the way in.

Two diagrams, both generated from the code so they cannot drift from it (`just figure`):

## The workflow

The block diagram of the workflow itself, generated from the recipe (`csmw figure code_builder`):
what each stage does, who writes and who attacks, where code freezes, merges and runs.

<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/workflow-dark.svg">
<img src="docs/media/workflow.svg" alt="How the code-builder workflow operates" width="820">
</picture></p>

## The harness

The harness operates on top of the workflow: the workflow figure above is the top box of this
one. The agent workflow is Python; it feeds Prefect and MLflow through their SDKs; both feed
`monitor.db`; Reflex is the human control plane; the custom dashboard is what you look at.

<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/harness-dark.svg">
<img src="docs/media/harness.svg" alt="How the runtime is wired" width="760">
</picture></p>

### Clean responsibility split

| system | owns |
|---|---|
| **Prefect** | workflow execution · task dependencies · retries · scheduling · cancellation · run/task state |
| **MLflow** | agent / LLM traces · spans · tool calls · retrieval traces · token / cost / latency · workflow / agent evaluation · scientific / ML experiments · parameters / metrics · artifacts / models |
| **monitor.db** | dashboard-only state · live human-readable progress · current activity · UI metadata · graph layout / positions |
| **Reflex** | human control plane · create tasks · launch / cancel runs · live dashboard · inspect traces · inspect experiments · inspect evaluations |

The main rule:

```text
workflow/task state  -> Prefect
agent behavior       -> MLflow traces
experiment results   -> MLflow experiments
UI-only state        -> monitor.db
human interaction    -> Reflex
```

Do not log the same data into all systems.

### Shared workflow id

Every subsystem receives the same application-level id, and the dashboard joins on it:

```text
workflow_run_id = "run_123"
   |
   +-- Prefect -----> What is executing?
   +-- MLflow ------> What did the agents do? How did the experiment perform?
   +-- monitor.db --> What UI-specific state should be displayed?
```

In this template the id is the run's folder name under `runs/`; `state.json` and `events.jsonl`
in that folder are the one owner of status and history, and Prefect, MLflow and `monitor.db` are
fed from them (rule 4, one owner per fact).

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # one API key is enough to start; FAKE_MODELS=1 needs none
just doctor                   # exit 0 = ready; every line it checked is printed (or: .venv/bin/csmw doctor)
```

## First run

```bash
just walk code_builder        # the whole recipe on fake models: 10 legs, zero tokens, ~20 s
just dash                     # the dashboard on 127.0.0.1:3000
just run examples/code_builder/task.json
```

`docs/QUICKSTART.md` lists every command; `docs/HACKATHON-30MIN.md` is the first half hour.

## Settings you choose once

The run's start page is one form: the brief, then one card per setting — the running mode,
the rounds cap, the checker's model, effort and speed, then a model and an effort per stage
for the author side, then the verification-run overrides — each a row of chips with the default
pre-selected and a one-line reason for that default. The pre-selected setup is a one-round
average task: the checker at high effort (a lazy review looks identical to a clean pass), the
contract and verification rows carrying the judgment, the build on the cheapest model. Adjust
per task; your picks are remembered for the next run. The form derives from one settings
schema, which the CLI reads too. The layout is `docs/DASHBOARD-DESIGN.md` → *The start page*.

**Estimated cost.** The dashboard prices a run's tokens on read (rule 14: tokens are the fact, dollars
are a lookup). An unknown model shows `$?` until you price it. Add or correct prices without touching code with a
`prices.json` next to your runs (or `CSMW_PRICES_FILE`):

```json
{"gpt-5.4-mini": [0.25, 2.0], "claude-haiku-4-5": [1.0, 5.0]}
```

Values are USD per million input and output tokens.

## Read more

- [docs/PLAN.md](docs/PLAN.md) — the full design: backbone, schemas, verification, recipes, dashboard, figure, build order
- [docs/RELIABILITY.md](docs/RELIABILITY.md) — the doctrine the rules come from (imported from freeze-and-swap)
- [docs/BUG-LEDGER.md](docs/BUG-LEDGER.md) — the bug classes; classify before fixing, fix the class
- [docs/HACKATHON-30MIN.md](docs/HACKATHON-30MIN.md) — the first thirty minutes
- [docs/ADD-A-RECIPE.md](docs/ADD-A-RECIPE.md) — extend it

## Prior art

Descends from [freeze-and-swap](https://github.com/msoliman6/freeze-and-swap) (MIT): the
freeze, the swap, the coded driver, the offline walk, the page. This template generalises its
doctrine into recipes on a Prefect + MLflow + Reflex runtime.

## License

MIT.
