#!/usr/bin/env bash
# The full offline suite (rule 12): lint, every selftest, every walk leg. Zero tokens.
# A SKIPPED tool is loud; a red leg fails the suite.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
fail=0
echo "== ruff"
$PY -m ruff check code_steer_model_write tests || fail=1
echo "== selftests"
$PY -m pytest -q || fail=1
echo "== walk"
FAKE_MODELS=1 $PY -m code_steer_model_write.cli walk all || fail=1
if [ "$fail" = 0 ]; then echo "run.sh: green"; else echo "run.sh: RED"; fi
exit $fail
