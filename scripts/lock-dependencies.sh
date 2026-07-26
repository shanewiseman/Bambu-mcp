#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

python_command=${PYTHON:-python3.12}
"$python_command" -m pip install --upgrade pip-tools
"$python_command" -m piptools compile \
  --resolver=backtracking \
  --strip-extras \
  --output-file=requirements.lock \
  pyproject.toml
"$python_command" -m piptools compile \
  --resolver=backtracking \
  --extra=dev \
  --all-build-deps \
  --strip-extras \
  --output-file=requirements-dev.lock \
  pyproject.toml
