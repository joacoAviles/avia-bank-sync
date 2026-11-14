#!/bin/sh
# Genera los secretos locales (no se versionan). No sobrescribe archivos existentes.
set -eu
cd "$(dirname "$0")/../secrets"
umask 077
gen() { [ -s "$1" ] || { printf '%s' "$2" > "$1"; echo "creado secrets/$1"; }; }
rand() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-"$1"; }
DBPW=$(rand 40)
gen db_password "$DBPW"
gen database_url "postgresql://avia:$(cat db_password)@avia-db:5432/avia"
gen api_token "$(rand 64)"
gen encryption_keys "$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
gen backup_key "$(rand 64)"
[ -s actual_password ] || { printf 'CAMBIAR' > actual_password; echo "EDITAR secrets/actual_password (contraseña del servidor Actual)"; }
[ -s actual_e2e_password ] || { : > actual_e2e_password; echo "secrets/actual_e2e_password vacío (rellenar solo si el presupuesto tiene cifrado E2E)"; }
echo "Guarde una copia de secrets/encryption_keys y secrets/backup_key fuera del NAS: sin ellas no se pueden leer credenciales ni respaldos."
