#!/usr/bin/env bash
# =============================================================================
# AVIA Bank Sync + Actual parchado — instalación COMPLETA en el Synology NAS
#
# Uso (en el servidor):
#     git clone https://github.com/joacoAviles/avia-bank-sync.git && cd avia-bank-sync && sudo bash install.sh
#
# Qué hace (en orden, y se detiene ante cualquier error):
#   0. Revisa Docker, detecta tu contenedor de Actual y su proyecto compose
#   1. RESPALDA los datos de Actual (obligatorio, antes de tocar nada)
#   2. Descomprime los dos repos en /volume1/docker
#   3. Construye las imágenes (Actual con parche AVIA, runner y AVIA)
#   4. Genera secretos y .env de AVIA (te pide 2 datos)
#   5. Levanta AVIA (PostgreSQL + API + respaldos cifrados)
#   6. Cambia SOLO la imagen de Actual a la parchada (archivo override, no edita tu compose)
#   7. Levanta el runner que importa los datos a Actual
#   8. Verifica y deja un script de rollback
#
# Es re-ejecutable: no sobrescribe secretos ni respaldos existentes.
# =============================================================================
set -euo pipefail

# ---------- configuración ----------
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups-avia}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AVIA_DIR="$HERE/avia-bank-sync"
INTEG_DIR="$HERE/actual-avia-integration"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$HERE/instalacion-avia-$STAMP.log"
exec > >(tee -a "$LOG") 2>&1

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✖ %s\033[0m\n' "$*"; exit 1; }
ask()  { local v; read -r -p "  $1 " v </dev/tty; printf '%s' "$v"; }
asks() { local v; read -r -s -p "  $1 " v </dev/tty; echo >/dev/tty; printf '%s' "$v"; }

[ "$(id -u)" = 0 ] || die "Ejecuta con sudo:  sudo bash $0"

# ---------- 0. Preflight ----------
say "0/8 Revisando el NAS"
command -v docker >/dev/null || die "Docker no está instalado (Container Manager)."
docker info >/dev/null 2>&1 || die "El demonio de Docker no responde."
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null; then DC="docker-compose"
else die "No encuentro 'docker compose'."; fi
ok "Docker y compose disponibles ($DC)"


case "$(uname -m)" in
  x86_64)  PLATFORM=linux/amd64; JQARCH=amd64 ;;
  aarch64) PLATFORM=linux/arm64; JQARCH=arm64 ;;
  *) die "Arquitectura no soportada: $(uname -m)" ;;
esac
ok "Arquitectura $PLATFORM"

# Contenedor de Actual
mapfile -t CANDS < <(docker ps --format '{{.Names}} {{.Image}}' | grep -i 'actual' | grep -vi 'avia' | awk '{print $1}')
if [ "${#CANDS[@]}" -eq 0 ]; then die "No encuentro un contenedor de Actual en ejecución."; fi
if [ "${#CANDS[@]}" -eq 1 ]; then ACTUAL_CT="${CANDS[0]}"
else
  echo "  Contenedores candidatos: ${CANDS[*]}"
  ACTUAL_CT="$(ask 'Nombre exacto del contenedor de Actual:')"
fi
docker inspect "$ACTUAL_CT" >/dev/null 2>&1 || die "El contenedor '$ACTUAL_CT' no existe."

lbl() { docker inspect "$ACTUAL_CT" --format "{{ index .Config.Labels \"$1\" }}"; }
ACTUAL_IMG_OLD="$(docker inspect "$ACTUAL_CT" --format '{{.Config.Image}}')"
PROJ="$(lbl com.docker.compose.project)"
SVC="$(lbl com.docker.compose.service)"
WDIR="$(lbl com.docker.compose.project.working_dir)"
CFILES="$(lbl com.docker.compose.project.config_files)"
[ -n "$PROJ" ] && [ -n "$SVC" ] && [ -n "$WDIR" ] && [ -n "$CFILES" ] || \
  die "'$ACTUAL_CT' no fue creado con docker compose; no puedo cambiarlo con seguridad. Pásame tu compose de Actual."
ACTUAL_NET="$(docker inspect "$ACTUAL_CT" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')"
ACTUAL_DATA="$(docker inspect "$ACTUAL_CT" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
[ -d "$ACTUAL_DATA" ] || die "No encuentro el volumen /data de Actual."
ok "Actual: contenedor=$ACTUAL_CT imagen=$ACTUAL_IMG_OLD servicio=$SVC proyecto=$PROJ red=$ACTUAL_NET"
ok "Datos de Actual: $ACTUAL_DATA"

# ---------- 1. Respaldo ----------
say "1/8 Respaldo de los datos de Actual (obligatorio)"
mkdir -p "$BACKUP_DIR"
BK="$BACKUP_DIR/actual-data-$STAMP.tgz"
docker stop "$ACTUAL_CT" >/dev/null
tar -czf "$BK" -C "$(dirname "$ACTUAL_DATA")" "$(basename "$ACTUAL_DATA")"
docker start "$ACTUAL_CT" >/dev/null
[ -s "$BK" ] || die "El respaldo quedó vacío."
tar -tzf "$BK" >/dev/null || die "El respaldo está corrupto."
ok "Respaldo verificado: $BK ($(du -h "$BK" | cut -f1))"

# ---------- 2. Repo ----------
say "2/8 Preparando carpetas"
mkdir -p "$AVIA_DIR/secrets" "$AVIA_DIR/postgres" "$AVIA_DIR/runner" "$AVIA_DIR/backups"
chmod +x "$AVIA_DIR"/scripts/*.sh "$INTEG_DIR"/scripts/*.sh
ok "Carpetas listas en $HERE"

# ---------- 3. Imágenes ----------
say "3/8 Construyendo imágenes (Actual+AVIA, runner, AVIA) — tarda 10-30 min"
TOOLS="$(mktemp -d)"; mkdir -p "$TOOLS/bin"; export PATH="$TOOLS/bin:$PATH"
if ! command -v jq >/dev/null; then
  say "   instalando jq temporal"
  curl -fsSL -o "$TOOLS/bin/jq" "https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-$JQARCH" || die "No pude bajar jq"
  chmod +x "$TOOLS/bin/jq"
fi
if ! command -v git >/dev/null; then
  say "   git no instalado: uso contenedor alpine/git"
  cat > "$TOOLS/bin/git" <<'EOF'
#!/bin/sh
exec docker run --rm -v "$PWD":"$PWD" -w "$PWD" -e HOME=/tmp alpine/git "$@"
EOF
  chmod +x "$TOOLS/bin/git"
fi

# Actual necesita ~8 GB para compilar: si la RAM es poca, swap temporal
MEM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
SWAPF=""
if [ "$MEM_MB" -lt 7500 ]; then
  warn "RAM=${MEM_MB} MB (<8 GB). Creo swap temporal de 8 GB para compilar."
  SWAPF="$HERE/.avia-swap"
  if [ ! -f "$SWAPF" ]; then
    dd if=/dev/zero of="$SWAPF" bs=1M count=8192 status=none
    chmod 600 "$SWAPF"; mkswap "$SWAPF" >/dev/null
  fi
  swapon "$SWAPF" || warn "swapon falló; continúo sin swap"
fi

export PLATFORM
( cd "$INTEG_DIR" && ./scripts/build-images.sh )
( cd "$AVIA_DIR" && AVIA_VERSION=1.0.0 $DC build avia-api )

if [ -n "$SWAPF" ]; then swapoff "$SWAPF" 2>/dev/null || true; rm -f "$SWAPF"; fi

NEW_ACTUAL_IMG="$(jq -r .images.actual "$INTEG_DIR/version-lock.json")"
RUNNER_VER="$(jq -r .avia.version "$INTEG_DIR/version-lock.json")"
docker image inspect "$NEW_ACTUAL_IMG" >/dev/null || die "No se construyó $NEW_ACTUAL_IMG"
ok "Imágenes construidas: $NEW_ACTUAL_IMG, runner $RUNNER_VER, avia-bank-sync"

# ---------- 4. Secretos y .env ----------
say "4/8 Secretos y configuración de AVIA"
cd "$AVIA_DIR"
umask 077
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1" || true; }
gen() { [ -s "secrets/$1" ] || { printf '%s' "$2" > "secrets/$1"; ok "creado secrets/$1"; }; }
gen db_password "$(rnd 40)"
gen database_url "postgresql://avia:$(cat secrets/db_password)@avia-db:5432/avia"
gen api_token "$(rnd 64)"
gen encryption_keys "$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')"
gen backup_key "$(rnd 64)"
if [ ! -s secrets/actual_password ]; then
  P="$(asks 'Contraseña de tu servidor Actual (la que usas para entrar):')"
  [ -n "$P" ] || die "Contraseña vacía"
  printf '%s' "$P" > secrets/actual_password; ok "creado secrets/actual_password"
fi
[ -e secrets/actual_e2e_password ] || { : > secrets/actual_e2e_password; }
chmod 700 secrets; chmod 644 secrets/*   # los contenedores (uid 1001/postgres) deben poder leerlos; la carpeta es solo root

if [ ! -f .env ]; then
  SYNC="$(ask 'Sync ID del presupuesto (Actual > Configuración > Mostrar avanzado > Sync ID):')"
  [ -n "$SYNC" ] || die "Sync ID vacío"
  cp .env.example .env
  sed -i "s|^ACTUAL_BUDGET_SYNC_ID=.*|ACTUAL_BUDGET_SYNC_ID=$SYNC|" .env
  sed -i "s|^ACTUAL_NETWORK=.*|ACTUAL_NETWORK=$ACTUAL_NET|" .env
  sed -i "s|^AVIA_DATA_DIR=.*|AVIA_DATA_DIR=$AVIA_DIR|" .env
  sed -i "s|^AVIA_BACKUP_DIR=.*|AVIA_BACKUP_DIR=$AVIA_DIR/backups|" .env
  sed -i "s|^ACTUAL_AVIA_VERSION=.*|ACTUAL_AVIA_VERSION=$RUNNER_VER|" .env
  ok ".env creado"
else
  ok ".env ya existía: se conserva"
fi
cp -n secrets/encryption_keys "$BACKUP_DIR/avia-encryption_keys-$STAMP" 2>/dev/null || true
cp -n secrets/backup_key "$BACKUP_DIR/avia-backup_key-$STAMP" 2>/dev/null || true
warn "COPIA a un lugar fuera del NAS: secrets/encryption_keys y secrets/backup_key (sin ellas no se leen credenciales ni respaldos)"

# ---------- 5. AVIA ----------
say "5/8 Levantando AVIA (db, api, respaldos)"
$DC up -d avia-db avia-api avia-backup
for i in $(seq 1 60); do
  H="$(docker inspect avia-bank-sync-avia-api-1 --format '{{.State.Health.Status}}' 2>/dev/null || echo none)"
  [ "$H" = healthy ] && break; sleep 3
done
[ "${H:-}" = healthy ] || { $DC logs --tail 50 avia-api; die "avia-api no quedó healthy"; }
ok "avia-api healthy"

# ---------- 6. Actual con el parche ----------
say "6/8 Cambiando la imagen de Actual (solo imagen + 2 variables)"
OVR="$WDIR/compose.avia.override.yaml"
cat > "$OVR" <<EOF
# Generado por instalar-avia-nas.sh. Para volver a Actual normal: borra este archivo y ejecuta rollback-avia.sh
services:
  $SVC:
    image: $NEW_ACTUAL_IMG
    environment:
      AVIA_SERVER_URL: http://avia-api:8000
      AVIA_API_TOKEN_FILE: /run/secrets/avia_api_token
    volumes:
      - $AVIA_DIR/secrets/api_token:/run/secrets/avia_api_token:ro
EOF
FARGS=""; IFS=',' read -ra FS <<<"$CFILES"; for f in "${FS[@]}"; do FARGS="$FARGS -f $f"; done
( cd "$WDIR" && $DC -p "$PROJ" $FARGS -f "$OVR" config >/dev/null ) || die "El compose combinado no valida; no toco Actual."
( cd "$WDIR" && $DC -p "$PROJ" $FARGS -f "$OVR" up -d "$SVC" )
sleep 8
docker ps --format '{{.Names}}' | grep -qx "$ACTUAL_CT" || die "Actual no volvió a levantar: ejecuta rollback-avia.sh"
ok "Actual corriendo con la imagen parchada"

# ---------- 7. Runner ----------
say "7/8 Levantando el runner (importa a Actual)"
cd "$AVIA_DIR"
$DC up -d avia-runner || warn "El runner no arrancó: revisa 'docker compose logs avia-runner' (suele ser contraseña o Sync ID)"
sleep 8

# ---------- 8. Rollback + verificación ----------
say "8/8 Verificación y rollback"
cat > "$HERE/rollback-avia.sh" <<EOF
#!/usr/bin/env bash
# Vuelve a tu Actual original y apaga AVIA (los datos de Actual no se tocan).
set -e
cd "$AVIA_DIR" && $DC down || true
rm -f "$OVR"
cd "$WDIR"
sed -i "s|^\(\s*image:\s*\).*aviarockets/actual-server.*|\1$ACTUAL_IMG_OLD|" $(echo "$CFILES" | tr ',' ' ') 2>/dev/null || true
$DC -p "$PROJ" $(for f in "${FS[@]}"; do printf -- '-f %s ' "$f"; done) up -d --force-recreate "$SVC"
echo "Listo. Respaldo de datos si lo necesitas: $BK"
EOF
chmod +x "$HERE/rollback-avia.sh"

TOKEN="$(cat "$AVIA_DIR/secrets/api_token")"
curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8070/v1/status >/dev/null && ok "AVIA responde en el puerto 8070 (solo loopback)" || warn "AVIA no responde en 8070"
docker exec "$ACTUAL_CT" sh -c 'wget -qO- --header="Authorization: Bearer x" http://avia-api:8000/health' >/dev/null 2>&1 \
  && ok "Actual alcanza a AVIA por la red interna" || warn "Actual no alcanza a avia-api (revisa la red $ACTUAL_NET)"
$DC ps

cat <<EOF

=====================================================================
 LISTO.
  1) Abre https://finanzas.aviarockets.cl (recarga con Ctrl+Shift+R)
  2) Configuración > Sincronización bancaria: debe aparecer "Bancos chilenos"
  3) Set up > elige banco > RUT y clave > Sign in to the bank
  4) Luego "Enlazar cuenta" en tus cuentas Chile / Itaú / Ripley

 Respaldo de Actual : $BK
 Rollback           : sudo bash $HERE/rollback-avia.sh
 Log de esta corrida: $LOG
 IMPORTANTE         : copia fuera del NAS  $AVIA_DIR/secrets/encryption_keys  y  backup_key
=====================================================================
EOF
