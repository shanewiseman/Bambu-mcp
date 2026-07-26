#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

mkdir -p .ci-cache artifacts
export COVERAGE_FILE=artifacts/.coverage

exec .ci-venv/bin/python -m pytest \
  --basetemp=.ci-cache/pytest \
  --junitxml=artifacts/junit.xml \
  --cov=bambu_mcp \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml:artifacts/coverage.xml \
  --cov-fail-under=90
