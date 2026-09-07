#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/studio-web"

if command -v pnpm >/dev/null 2>&1; then
  studio_pnpm="$(command -v pnpm)"
elif [ -f "/c/Users/$USERNAME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd" ]; then
  studio_pnpm="/c/Users/$USERNAME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd"
else
  echo "pnpm was not found. Install Node.js LTS with Corepack, then run: corepack enable && corepack prepare pnpm@latest --activate" >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  "$studio_pnpm" install
fi

exec "$studio_pnpm" dev "$@"
