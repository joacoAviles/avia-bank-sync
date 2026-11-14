#!/usr/bin/env bash
# Pruebas de regresión de la integración sobre la fuente parcheada (sin Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/build/actual}"
[ -d "$SRC/node_modules" ] || (cd "$SRC" && yarn install --immutable)
cd "$SRC"
yarn typecheck
(cd packages/loot-core && npx vitest --run src/server/accounts)
(cd packages/sync-server && NODE_ENV=test NODE_OPTIONS=--experimental-vm-modules npx vitest --run src/app-avia src/app-gocardless src/app-simplefin)
(cd packages/desktop-client && npx vitest --run src/components/banksync)
echo "Regresión OK"
