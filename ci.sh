#!/bin/bash
# Run locally everything CI runs, so a push won't go red. Mirrors
# .github/workflows/tests.yml. Usage: ./ci.sh
set -euo pipefail

step() { printf '\n=== %s ===\n' "$1"; shift; "$@"; }

step "uv sync (locked)" uv sync --all-groups --locked
step "ruff check" uv run ruff check --no-fix .
step "ruff format --check" uv run ruff format --check .
step "tests" uv run pytest -q

printf '\nAll CI checks passed.\n'
