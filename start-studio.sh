#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/studio-web"

if command -v pnpm >/dev/null 2>&1; then
  studio_pnpm="$(command -v pnpm)"
else
  echo "pnpm was not found. Install Node.js LTS with Corepack, then run: corepack enable && corepack prepare pnpm@latest --activate" >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  "$studio_pnpm" install
fi

if [[ "$studio_pnpm" == *.cmd ]]; then
  studio_node_dir="$(dirname "$(command -v node)")"
  studio_node_win="$(cygpath -w "$studio_node_dir")"
  studio_pnpm_win="$(cygpath -w "$studio_pnpm")"
  exec cmd.exe //d //s //c "set \"PATH=$studio_node_win;%PATH%\" & call $studio_pnpm_win dev"
fi

exec "$studio_pnpm" dev "$@"
