#!/usr/bin/env bash
# Clona Actual en la versión bloqueada y aplica los parches AVIA.
#   scripts/prepare-source.sh [directorio]   (por defecto ./build/actual)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/build/actual}"
REPO=$(jq -r .upstream.repository "$ROOT/version-lock.json")
TAG=$(jq -r .upstream.tag "$ROOT/version-lock.json")
COMMIT=$(jq -r .upstream.commit "$ROOT/version-lock.json")

if [ ! -d "$DEST/.git" ]; then
  git clone --filter=blob:none --branch "$TAG" "$REPO" "$DEST"
fi
cd "$DEST"
git fetch --tags --quiet
git checkout --quiet --force "$TAG"
git clean -fdq -- packages
[ "$(git rev-parse HEAD)" = "$COMMIT" ] || { echo "El tag $TAG no apunta al commit bloqueado $COMMIT"; exit 1; }

for p in $(jq -r '.avia.patches[]' "$ROOT/version-lock.json"); do
  git apply --check "$ROOT/$p"
  git apply "$ROOT/$p"
  echo "aplicado $p"
done
echo "Fuente lista en $DEST (Actual $TAG + AVIA)"
