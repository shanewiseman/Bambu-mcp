#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

mkdir -p .ci-cache
generated_dir=$(mktemp -d "$repository_dir/.ci-cache/generated-docs.XXXXXX")
trap 'rm -r -- "$generated_dir"' EXIT HUP INT TERM

.ci-venv/bin/bambu-mcp generate-docs --output "$generated_dir"
diff -u docs/generated/mcp-tools.md "$generated_dir/mcp-tools.md"
diff -u docs/generated/openapi.json "$generated_dir/openapi.json"

echo "Validated committed MCP and OpenAPI references"
