# The first thirty minutes

| min | do | you get |
|---|---|---|
| 0–3 | `copier copy gh:msoliman6/code_steer_model_write ../my-workflow && cd ../my-workflow`; `cp .env.example .env`, one key (or none: `FAKE_MODELS=1`) | a repo of your own; the template stays a template |
| 3–5 | `just doctor` (exit 0), `just walk code_builder` | proof the pipeline runs end to end here, zero tokens |
| 5–8 | `just dash`, open the page, click a stage, open the event log | the four signals: where, healthy, time, tokens |
| 8–15 | edit `examples/code_builder/task.json`: the brief's request, must_be_true, out_of_scope; `mode: light`, `rounds: 1`; small models on both sides | a task that fits your idea |
| 15–25 | `just run examples/code_builder/task.json`; answer the assumptions gate on the page | the plan, the contract, the freeze; the tests and source by opposite sides |
| 25–30 | read `runs/<id>/REPORT.md`: carried items, the waste table; `just selfcheck runs/<id>` | what to change next: the brief (cheap), a prompt (medium), a stage (`just new-recipe`) |

Rules of thumb under a deadline: run `just walk` before every live run; keep `rounds: 1`; let `auto`
mode drive the demo and show the flagged decisions as the honest list of what nobody checked; a halt
is a report with a Resume button, not a crash; never edit the package while a run lives.
