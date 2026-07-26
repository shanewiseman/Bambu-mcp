#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

mkdir -p .ci-cache artifacts/distributions
distribution_dir=$(mktemp -d "$repository_dir/.ci-cache/distributions.XXXXXX")
trap 'rm -r -- "$distribution_dir"' EXIT HUP INT TERM

.ci-venv/bin/python -m build \
  --no-isolation \
  --outdir "$distribution_dir/dist"
.ci-venv/bin/python scripts/check_distribution.py "$distribution_dir/dist"

wheel=$(find "$distribution_dir/dist" -name 'bambu_mcp-*.whl' -print -quit)
test -n "$wheel"
.ci-venv/bin/python -m pip install \
  --no-deps \
  --target "$distribution_dir/installed" \
  "$wheel"
PYTHONPATH="$distribution_dir/installed" .ci-venv/bin/python -c \
  "from importlib.metadata import version; import bambu_mcp; assert version('bambu-mcp') == '0.1.0'"

cp "$distribution_dir/dist/"* artifacts/distributions/
echo "Validated and staged the wheel and source distribution"
