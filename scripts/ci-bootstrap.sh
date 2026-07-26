#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

if [ ! -f requirements.lock ] || [ ! -f requirements-dev.lock ]; then
  echo "requirements.lock and requirements-dev.lock are required for CI bootstrap" >&2
  exit 1
fi

mkdir -p .ci-cache
python -c \
  "import sys; assert sys.version_info[:2] == (3, 12) and sys.version_info >= (3, 12, 11), sys.version"
python -m venv .ci-venv
.ci-venv/bin/python -m pip install --requirement requirements-dev.lock
.ci-venv/bin/python -m pip install --no-deps --no-build-isolation --editable .
python -m venv .ci-cache/runtime-venv
.ci-cache/runtime-venv/bin/python -m pip install --requirement requirements.lock

echo "Installed the exact Python 3.12 development and runtime environments"
