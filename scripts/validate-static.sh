#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

.ci-venv/bin/python -m ruff check .
.ci-venv/bin/python -m ruff format --check .
.ci-venv/bin/python -m mypy src
.ci-venv/bin/python -m compileall -q src tests scripts

echo "Validated Ruff, formatting, strict typing, and Python compilation"
