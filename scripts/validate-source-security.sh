#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

mkdir -p artifacts
.ci-venv/bin/python -m bandit \
  --configfile pyproject.toml \
  --recursive src \
  --format json \
  --output artifacts/bandit.json

echo "Validated the Python source with Bandit"
