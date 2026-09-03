# Add a recipe

1. `just new-recipe <name>` — copies the skeleton into `code_steer_model_write/recipes/<name>/recipe.py`,
   makes `prompts/<name>/`, `fixtures/<name>/`, `examples/<name>/task.json`, registers the name.
2. **`spec.py` first**: the params model, the stages (author and checker sides, the figure phrases,
   the hue and emoji), the gates that pass the two-kinds test (a value only the human has, early; a
   judgment only the human can make, on exception), the evals, and `required_checks` — the profile
   checklist the validate step refuses without. Reuse the shared artifacts (`artifacts/`) and the
   review loop (`review/rounds.py`); a new artifact is a pydantic `Artifact` with `key` fields the
   model chooses and ids code assigns.
3. **Fixtures second**: `fakers(paths, store)` returns a schema-valid answer per schema name, bound
   to the store so a re-emit is the real current artifact; one variant per branch (a finding, a
   closing-read finding, a verdict), steered by the knobs in `backends/knobs.py`.
4. **Prompts third**: role and output contract in the first three lines; tool denial as fact; a
   "what you do not have" section; the reviewer criteria; `{{KEY}}` placeholders only for values
   code renders (`fill` refuses raw JSON).
5. `steps()` derives every step from the files in the run dir, never from a counter; a program lists
   all its steps, done or pending; a step's `deliverables` prove it done.
6. Add walk legs in `walk.py` for every branch, and assert from `events.jsonl`.
7. `just walk <name>` green — including the refuse, revise and verdict legs — **before** any prompt
   tuning.
8. Register evals; run one clean live pass on small models; flip `status` to `proven`.

The figure regenerates from the spec: `just figure <name>`.
