#!/bin/sh
set -eu

repository_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_dir"

scripts/validate-static.sh
scripts/validate-source-security.sh
scripts/test-native.sh
scripts/validate-generated-docs.sh
scripts/validate-distribution.sh
scripts/validate-supply-chain.sh

echo "Completed hardware-free native validation"
