#!/usr/bin/env bash
# Construye las imágenes de Actual (con AVIA) y del runner.
# Requiere ~8 GB de RAM para compilar Actual: construir en un Mac/PC o en CI, NO en el NAS.
#   [REGISTRY=ghcr.io/usuario] scripts/build-images.sh [--push]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/build/actual"
ACTUAL_IMG="${REGISTRY:+$REGISTRY/}$(jq -r .images.actual "$ROOT/version-lock.json")"
RUNNER_IMG="${REGISTRY:+$REGISTRY/}$(jq -r .images.runner "$ROOT/version-lock.json")"
PLATFORM="${PLATFORM:-linux/amd64}"   # Synology x86_64. Para ARM: PLATFORM=linux/arm64

"$ROOT/scripts/prepare-source.sh" "$SRC"

# 1) Imagen del servidor: se usa el Dockerfile OFICIAL de Actual sin modificar.
docker build --platform "$PLATFORM" -f "$SRC/sync-server.Dockerfile" -t "$ACTUAL_IMG" "$SRC"

# 2) Runner: @actual-app/api compilado desde la MISMA fuente parcheada.
#    (contexto preparado a mano: no depende de `--build-context`, que el Docker del Synology no trae)
CTX="$ROOT/build/runner-ctx"
rm -rf "$CTX"; mkdir -p "$CTX/actual" "$CTX/runner"
tar -C "$SRC" --exclude=.git --exclude=node_modules -cf - . | tar -C "$CTX/actual" -xf -
cp "$ROOT/runner/package.json" "$ROOT/runner/index.mjs" "$CTX/runner/"
docker build --platform "$PLATFORM" -f "$ROOT/docker/runner.Dockerfile" -t "$RUNNER_IMG" "$CTX"

if [ "${1:-}" = "--push" ]; then
  docker push "$ACTUAL_IMG"
  docker push "$RUNNER_IMG"
else
  echo "Para llevarlas al NAS sin registro:"
  echo "  docker save $ACTUAL_IMG $RUNNER_IMG | gzip > avia-images.tar.gz"
  echo "  scp avia-images.tar.gz nas: && ssh nas 'gunzip -c avia-images.tar.gz | sudo docker load'"
fi
