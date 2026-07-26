#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

mkdir -p artifacts/sbom
.ci-venv/bin/cyclonedx-py environment \
  .ci-cache/runtime-venv/bin/python \
  --pyproject pyproject.toml \
  --output-reproducible \
  --output-format JSON \
  --output-file artifacts/sbom/bambu-mcp-ci.cdx.json
.ci-venv/bin/pip-licenses \
  --python .ci-cache/runtime-venv/bin/python \
  --format json \
  --output-file artifacts/dependency-licenses.json
.ci-venv/bin/python scripts/check_dependency_licenses.py \
  artifacts/dependency-licenses.json
.ci-venv/bin/python -m json.tool \
  artifacts/sbom/bambu-mcp-ci.cdx.json >/dev/null

echo "Validated the runtime SBOM and core dependency license boundary"
