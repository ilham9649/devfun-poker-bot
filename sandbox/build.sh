#!/usr/bin/env bash
# Assemble the sandbox harness bundle: strategy.py (entry) + vendored quant.py.
# Usage: sandbox/build.sh [outdir]   (default: sandbox/bundle)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/bundle}"
mkdir -p "$out"
cp "$here/strategy.py" "$out/strategy.py"
cp "$here/../pokerbot/quant.py" "$out/quant.py"
echo "bundle ready: $out"
