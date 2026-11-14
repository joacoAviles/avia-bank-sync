# Operación en el Synology NAS

> Regla: no modificar producción sin respaldo y aprobación (§3.12). Cada paso que toca Actual
> empieza con un respaldo y se puede revertir.

## 0. Requisitos
- Construir las imágenes **fuera del NAS** (Actual necesita ~8 GB de RAM para compilar):
  `actual-avia-integration/scripts/build-images.sh` en un Mac/PC con Docker, o con el workflow de CI.
- Llevarlas al NAS con un registro privado (GHCR) o con `docker save | docker load`.

## 1. Inspección previa (no modifica nada)
```bash
ssh nas
cd /volume1/docker/actual-budget
sudo docker compose config            # ver el compose real: imagen, volúmenes, red, variables
sudo docker network ls | grep actual  # confirmar el nombre: actual-budget_default
sudo docker inspect actual-budget --format '{{.Config.Image}}'
```
Si la red, el nombre del contenedor o el puerto no coinciden con `actual-budget_default`,
`actual-budget` y `5006`, se ajustan `ACTUAL_NETWORK` y `ACTUAL_SERVER_URL` en `.env` de AVIA.

## 2. Respaldo de Actual (obligatorio)
```bash
sudo docker compose -f /volume1/docker/actual-budget/compose.yaml stop actual-budget
sudo tar -czf /volume1/backups/actual-data-$(date +%F).tgz -C /volume1/docker/actual-budget data
sudo docker compose -f /volume1/docker/actual-budget/compose.yaml start actual-budget
```
También conviene exportar el presupuesto desde la interfaz (Archivo → Exportar).

## 3. Desplegar AVIA (proyecto independiente)
```bash
sudo mkdir -p /volume1/docker/avia-bank-sync && cd /volume1/docker/avia-bank-sync
# copiar el repo avia-bank-sync aquí
cp .env.example .env               # completar ACTUAL_BUDGET_SYNC_ID
./scripts/generate-secrets.sh      # crea ./secrets (no versionado)
echo -n 'CONTRASEÑA-DEL-SERVIDOR-ACTUAL' > secrets/actual_password
sudo docker compose up -d avia-db avia-api avia-backup
sudo docker compose ps             # avia-api debe quedar "healthy"
```
**Copie `secrets/encryption_keys` y `secrets/backup_key` a un lugar seguro fuera del NAS.**

## 4. Cambiar la imagen de Actual (único cambio en el proyecto existente)
En `/volume1/docker/actual-budget/compose.yaml`:
```yaml
services:
  actual-budget:
    image: aviarockets/actual-server:26.11.0-avia.1   # antes: actualbudget/actual-server:26.11.0
    environment:
      AVIA_SERVER_URL: http://avia-api:8000
      AVIA_API_TOKEN_FILE: /run/secrets/avia_api_token
    secrets: [avia_api_token]
secrets:
  avia_api_token:
    file: /volume1/docker/avia-bank-sync/secrets/api_token
```
```bash
cd /volume1/docker/actual-budget && sudo docker compose up -d actual-budget
```

## 5. Configurar en Actual
1. Preferencias → Sincronización bancaria → **AVIA Bank Sync → Set up**.
2. Crear la conexión. Hoy solo está disponible el *AVIA Sandbox* (datos ficticios): úselo en un
   **presupuesto de prueba**, nunca en el real.
3. **Link bank account** → elegir las cuentas → crear nuevas o vincular existentes.
4. *Sincronización automática* → «Cada 12 horas» (mientras Actual está abierto).
5. Copiar el *Sync ID* (Preferencias → Advanced) en `.env` → `ACTUAL_BUDGET_SYNC_ID` y levantar el runner:
   `sudo docker compose up -d avia-runner`.

## 6. Día a día
| Qué | Cuándo | Cómo |
| --- | --- | --- |
| Sincronización con bancos | 06:15 America/Santiago | scheduler de AVIA |
| Importación a Actual | justo después (aviso al runner); respaldo cada 24 h | avia-runner |
| Al abrir Actual | si los datos tienen > 12 h | sincronización automática de Actual + frescura de AVIA |
| Manual | cuando quiera | botón «Sincronización bancaria» de la cuenta en Actual, o el panel técnico |
| Respaldo cifrado de AVIA | 03:00 | avia-backup (30 días de retención) |

Panel técnico (solo diagnóstico): `ssh -L 8070:127.0.0.1:8070 nas` → http://localhost:8070/panel.

## 7. Restaurar un respaldo de AVIA
```bash
sudo docker compose stop avia-api
sudo docker compose run --rm -e CONFIRM=yes avia-backup /backup.sh restore /backups/avia-AAAAMMDD-HHMMSS.sql.gz.enc
sudo docker compose start avia-api
```
(Restaurar sobre una base vacía: `docker compose down avia-db` + borrar `postgres/` antes de levantarla.)

## 8. Rollback
- **Solo Actual:** volver a `image: actualbudget/actual-server:26.11.0` y `docker compose up -d`.
  Los datos del presupuesto no cambian; las cuentas AVIA quedan sin sincronizar.
- **AVIA:** `docker compose down` en `/volume1/docker/avia-bank-sync`. Actual sigue funcionando
  (AVIA aparece como «no alcanzable»).
- **Versión anterior de AVIA:** `AVIA_VERSION=<anterior>` en `.env` y `docker compose up -d`.
  Las migraciones son aditivas.

## 9. Monitoreo
- `docker compose ps`: los healthchecks de avia-api (`/ready`), avia-db y avia-runner.
- `AVIA_NOTIFY_WEBHOOK_URL` (p. ej. un tópico privado de ntfy): avisa cada sincronización fallida o parcial.
- Panel → «Conciliación de saldos»: cualquier diferencia ≠ 0 genera un evento `balance_mismatch`.
