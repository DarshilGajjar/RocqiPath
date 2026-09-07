#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/studio-web"

if command -v pnpm >/dev/null 2>&1; then
  studio_pnpm="$(command -v pnpm)"
elif [ -f "/c/Users/$USERNAME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd" ]; then
  studio_pnpm="/c/Users/$USERNAME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd"
else
  echo "pnpm was not found." >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node was not found on PATH." >&2
  exit 1
fi

if [ ! -f node_modules/vinext/dist/cli.js ]; then
  "$studio_pnpm" install
fi

exec node node_modules/vinext/dist/cli.js dev "$@"