#!/usr/bin/env bash
# Start RocqiPath Studio on http://127.0.0.1:8765.
#
#   bash start-studio.sh            # serve the built interface (no Node.js needed)
#   bash start-studio.sh --dev      # also run the interface dev server with live reload
#
# Other arguments are passed to `rocqipath studio` (e.g. --workspace, --port).
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v rocqipath >/dev/null 2>&1; then
  echo "rocqipath is not on PATH. Run: python -m pip install -e \".[studio]\"" >&2
  exit 1
fi

if [ "${1:-}" != "--dev" ]; then
  exec rocqipath studio "$@"
fi
shift

if ! command -v pnpm >/dev/null 2>&1; then
  echo "--dev needs Node.js 20+ and pnpm on PATH." >&2
  exit 1
fi
rocqipath studio "$@" &
backend=$!
trap 'kill "$backend" 2>/dev/null' EXIT
cd studio-web
[ -d node_modules ] || pnpm install
pnpm dev
