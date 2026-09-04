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


## A recipe in its own repo (the normal case)

A project is a package that depends on the template and registers its recipe by entry point;
nothing in the template names it. In the project's `pyproject.toml`:

```toml
[project]
dependencies = ["code_steer_model_write"]

[project.entry-points."csmw.recipes"]
coder = "csmw_coder.recipe:CodeBuilder"      # a Recipe class, instance or factory

[project.entry-points."csmw.walk_legs"]
coder = "csmw_coder.walk_legs:LEGS"           # {leg name: function(tmp_dir) -> detail}
```

After `pip install -e .` the recipe appears in `csmw walk coder`, on the start page's recipe
dropdown (first, ahead of the bundled debate) and on the run page. Its prompts, fixtures and
example task live in the project; `csmw figure coder` writes its workflow figure.
