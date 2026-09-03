# code_steer_model_write -- the working verbs. `just` (https://github.com/casey/just); every recipe is one honest command.
set shell := ["bash", "-cu"]
py := ".venv/bin/python"

default:
    @just --list

# preflight: exit 0 ready, 1 warnings, 2 halt
doctor *args:
    {{py}} -m code_steer_model_write.cli doctor {{args}}

# the offline walk: fake models, every branch, zero tokens (recipe name or `all`)
walk recipe="all" *args:
    FAKE_MODELS=1 {{py}} -m code_steer_model_write.cli walk {{recipe}} {{args}}

# lint + every selftest + the walk; SKIPPED is loud
test:
    bash scripts/run.sh

# start a run from a task spec
run task *args:
    {{py}} -m code_steer_model_write.cli run {{task}} {{args}}

# continue a halted or gated run
resume run_dir *args:
    {{py}} -m code_steer_model_write.cli resume {{run_dir}} {{args}}

# where a run is
status run_dir:
    {{py}} -m code_steer_model_write.cli status {{run_dir}}

# the dashboard on 127.0.0.1:3000 (runs dir: runs/)
dash *args:
    {{py}} -m code_steer_model_write.cli dash serve {{args}}

# prove the page by code for one run
selfcheck run_dir:
    {{py}} -m code_steer_model_write.cli dash selfcheck {{run_dir}}

# one real call per backend (costs tokens)
smoke *backends="anthropic":
    {{py}} scripts/smoke_live.py {{backends}}

# the workflow figure from a recipe, both themes
figure recipe="code_builder":
    {{py}} -m code_steer_model_write.cli figure {{recipe}} -o docs/media/workflow-dark.svg --theme dark
    {{py}} -m code_steer_model_write.cli figure {{recipe}} -o docs/media/workflow.svg --theme light
    {{py}} -m code_steer_model_write.cli figure harness -o docs/media/harness-dark.svg --theme dark
    {{py}} -m code_steer_model_write.cli figure harness -o docs/media/harness.svg --theme light

# scaffold a new recipe from the skeleton
new-recipe name:
    {{py}} scripts/new_recipe.py {{name}}
