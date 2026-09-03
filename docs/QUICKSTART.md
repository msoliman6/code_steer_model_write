# Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                 # keys, models, mode; FAKE_MODELS=1 needs none
just doctor                          # exit 0 ready · 1 warnings · 2 halt; every line it checked is printed
just walk code_builder               # the whole recipe on fake models: 10 legs, zero tokens, ~20 s
just dash                            # the page on 127.0.0.1:3000 (runs dir: runs/)
just run examples/code_builder/task.json
```

A run lives in `runs/<task_id>/`: `state.json` (status, the owner), `events.jsonl` (everything that
happened), `artifacts/<key>/vNNN.json` (every version of every artifact), `review/` (findings and
arbitrations per round), `gates/` (the ask and the decision records), `build/` (tests and source),
`triage/` (rulings), `REPORT.md`. `csmw status runs/<id>` says where it is; `csmw resume` continues
after a halt or a gate; `csmw dash selfcheck runs/<id>` proves the page by code.

## The commands

| command | what |
|---|---|
| `csmw validate task.json` | DRAFT → VALIDATED: the task fits the recipe (params, roles, required checks) |
| `csmw run task.json [--run-dir D] [--prefect] [--no-mlflow]` | start and drive a run |
| `csmw resume D` | continue a halted or gated run at the step it stopped |
| `csmw status D` | the steps and their state |
| `csmw walk [recipe\|all] [--only leg] [--keep]` | the offline walk |
| `csmw doctor [--deep]` | preflight; `--deep` runs one walk leg |
| `csmw dash serve\|selfcheck D\|view D` | the page; the self-check; the view model as JSON |
| `csmw figure recipe -o file --theme dark\|light` | the workflow figure |

## Modes

`detailed` asks every question; `light` asks only the risky ones and every input gate; `auto` asks
nothing and records every default as an auto-answer, flagged, so the reviewer attacks those first.
