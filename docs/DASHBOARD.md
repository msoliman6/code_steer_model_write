# The dashboard

`just dash` serves the page on `127.0.0.1:3000` (frontend) and `3001` (backend), reading every run
under `runs/`. Nothing is hosted; the page binds localhost on purpose because its buttons drive runs.
Over SSH: `ssh -L 3000:localhost:3000 -L 3001:localhost:3001 user@host`.

One page, four zones (docs/PLAN.md §7): the constant header — identity line, the stage rail, the
clock line with tokens per side, the NOW line with Stop, the wrong-ness chips — then the selected
stage's panel with the gate form inline when a gate is open, the stage's evidence, and the run's
evidence (swimlane, carried items, the event log with a filter per stage, the report).

- Every number comes from `dashboard/model.py::build_view(run_dir)`, built from the run's files; the
  page renders it and nothing else. `csmw dash view runs/<id>` prints the model as JSON.
- `csmw dash selfcheck runs/<id>` proves the page by code: the NOW line equals the record, chip counts
  equal recounts from the events, a gate form is present iff an ask file has no decision, the
  refresh hash covers every live file, every colour is a token, every disclosure has an id.
- The page polls every 3 s and re-renders only when the refresh hash moved; the picked stage
  survives the reload; a pick on the running stage rides with the run and a pick elsewhere shows a
  "jump to running" chip.
- A gate answered on the page writes `gates/<id>.decision.json` atomically; the driver's wait sees it.
- The design language is `docs/DASHBOARD-DESIGN.md`; the tokens are `dashboard/theme.py`.
