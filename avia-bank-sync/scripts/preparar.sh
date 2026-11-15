#!/usr/bin/env bash
# Prepara la carpeta para lanzarla desde Container Manager (Proyecto): crea secretos, .env y carpetas.
# No levanta ningún contenedor.   Uso:  cd /volume1/docker/avia-bank-sync && sudo bash scripts/preparar.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
mkdir -p secrets postgres runner backups
umask 077
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1" || true; }
gen() { [ -s "secrets/$1" ] || { printf '%s' "$2" > "secrets/$1"; echo "  creado secrets/$1"; }; }
gen db_password "$(rnd 40)"
gen database_url "postgresql://avia:$(cat secrets/db_password)@avia-db:5432/avia"
gen api_token "$(rnd 64)"
gen encryption_keys "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
gen backup_key "$(rnd 64)"
if [ ! -s secrets/actual_password ]; then
  read -r -s -p "  Contraseña de tu servidor Actual: " P </dev/tty; echo
  [ -n "$P" ] || { echo "Contraseña vacía"; exit 1; }
  printf '%s' "$P" > secrets/actual_password
fi
[ -e secrets/actual_e2e_password ] || : > secrets/actual_e2e_password
chmod 700 secrets; chmod 644 secrets/*
if [ ! -f .env ]; then
  read -r -p "  Sync ID del presupuesto (Actual > Configuración > Mostrar avanzado): " S </dev/tty
  [ -n "$S" ] || { echo "Sync ID vacío"; exit 1; }
  cp .env.example .env
  sed -i "s|^ACTUAL_BUDGET_SYNC_ID=.*|ACTUAL_BUDGET_SYNC_ID=$S|" .env
  sed -i "s|^AVIA_DATA_DIR=.*|AVIA_DATA_DIR=$DIR|; s|^AVIA_BACKUP_DIR=.*|AVIA_BACKUP_DIR=$DIR/backups|" .env
fi
echo
echo "LISTO. Ahora en Container Manager > Proyecto > Crear:"
echo "  Nombre: avia-bank-sync   Ruta: $DIR   Origen: usar compose.yaml existente"
echo "GUARDA fuera del NAS: $DIR/secrets/encryption_keys y backup_key"
