#!/bin/sh
# Respaldo cifrado de PostgreSQL (pg_dump | gzip | AES-256 con openssl).
#   backup.sh once      -> un respaldo ahora
#   backup.sh loop      -> respaldo diario a BACKUP_HOUR (America/Santiago)
#   backup.sh restore F -> restaura el archivo F (pide confirmación con CONFIRM=yes)
set -eu
apk add --no-cache openssl >/dev/null 2>&1 || true
printf '%s:5432:%s:%s:%s\n' "$PGHOST" "$PGDATABASE" "$PGUSER" "$(cat /run/secrets/db_password)" > /tmp/.pgpass
chmod 600 /tmp/.pgpass
KEY=/run/secrets/backup_key

once() {
  ts=$(date +%Y%m%d-%H%M%S)
  out="/backups/avia-$ts.sql.gz.enc"
  pg_dump --format=plain --no-owner | gzip -9 | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEY" > "$out.tmp"
  mv "$out.tmp" "$out"
  find /backups -name 'avia-*.sql.gz.enc' -mtime +"${BACKUP_RETENTION_DAYS:-30}" -delete
  echo "{\"level\":\"info\",\"logger\":\"avia.backup\",\"msg\":\"respaldo creado\",\"file\":\"$out\"}"
}

case "${1:-once}" in
  once) once ;;
  loop)
    while true; do
      now=$(date +%H)
      if [ "$now" = "$(printf '%02d' "${BACKUP_HOUR:-3}")" ]; then once; sleep 3700; else sleep 600; fi
    done ;;
  restore)
    [ "${CONFIRM:-}" = "yes" ] || { echo "Defina CONFIRM=yes para restaurar $2"; exit 1; }
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in "$2" | gunzip | psql -v ON_ERROR_STOP=1 ;;
esac
