#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

export XDG_CACHE_HOME="$repository_dir/.ci-cache"
mkdir -p artifacts "$XDG_CACHE_HOME"
.ci-venv/bin/pip-audit \
  --requirement requirements.lock \
  --no-deps \
  --disable-pip \
  --strict \
  --progress-spinner=off \
  --format=json \
  --output artifacts/pip-audit.json

echo "Validated locked Python dependencies against the vulnerability service"
