# AVIA Bank Sync

Proveedor bancario propio de **Avia Rockets** para **Actual Budget**: aparece en
*Preferencias → Sincronización bancaria → Providers* junto a GoCardless, SimpleFIN y Pluggy.ai,
con su propio **Set up** y **Link bank account**.

> **Estado (2026-11-14):** en Actual aparece **«Bancos chilenos»**. Para Banco de Chile, Itaú y Ripley se
> inicia sesión con **RUT y clave**: AVIA entra al portal del banco y, si el banco pide Mi Pass, un código o
> un CAPTCHA, Actual te muestra la pantalla en vivo para resolverlo. La sesión queda guardada cifrada.
> **Siguiente paso:** la extracción de cuentas y movimientos de cada portal (ver [ADR 0008](docs/ADR/0008-login-asistido-por-portal.md)).
> Motor, importación a Actual y despliegue ya están probados de punta a punta con el banco *AVIA Sandbox*.

## Qué hace
- Sincroniza saldos y movimientos una vez al día (06:15, America/Santiago), cuando Actual pide datos
  viejos (> 12 h) y a pedido.
- Deduplica por ID bancario, conserva el ID cuando un pendiente se contabiliza, detecta pendientes
  revertidos y manda los casos ambiguos a revisión.
- Pagos de tarjeta → **transferencias** en Actual (no se cuentan como gasto).
- Concilia el saldo contable del banco con el saldo conciliado de Actual y registra las diferencias.
- Cifra las credenciales (Fernet), guarda un log auditable de cada ejecución y respalda PostgreSQL con cifrado.

## Repositorios
| Repo | Contenido |
| --- | --- |
| `avia-bank-sync` (este) | Servicio Python: API, motor, conectores, scheduler, PostgreSQL, Docker |
| `actual-avia-integration` | Parche sobre Actual 26.11.0, runner headless, scripts de build y actualización, E2E |

## Desarrollo local
```bash
pip install -r requirements-dev.txt
createdb avia_test   # PostgreSQL 16 local (usuario avia/avia)
pytest               # 27 pruebas (motor, API, seguridad, recuperación)
AVIA_DATABASE_URL=postgresql://avia:avia@localhost/avia \
AVIA_API_TOKEN=$(openssl rand -hex 32) \
AVIA_ENCRYPTION_KEYS=$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())') \
uvicorn avia.api.main:app --port 8000
```

## Producción (Synology)
Ver [docs/OPERATIONS.md](docs/OPERATIONS.md). En resumen: `scripts/generate-secrets.sh`, `.env`,
`docker compose up -d`, y en Actual cambiar la imagen a `aviarockets/actual-server:26.11.0-avia.1`
más dos variables.

## Documentación
[ARCHITECTURE](docs/ARCHITECTURE.md) · [ACTUAL-INTEGRATION (auditoría)](docs/ACTUAL-INTEGRATION.md) ·
[BANK-CONNECTIVITY](docs/BANK-CONNECTIVITY.md) · [SYNC-STRATEGY](docs/SYNC-STRATEGY.md) ·
[DATA-MODEL](docs/DATA-MODEL.md) · [SECURITY](docs/SECURITY.md) · [OPERATIONS](docs/OPERATIONS.md) ·
[ROADMAP](docs/ROADMAP.md) · [ADR](docs/ADR/)

## API (Bearer `AVIA_API_TOKEN`)
`GET /health` · `GET /ready` · `GET /v1/status` · `GET /v1/institutions` · `GET|POST /v1/connections` ·
`DELETE /v1/connections/{id}` · `POST /v1/connections/{id}/reauthorize` · `GET /v1/accounts` ·
`POST /v1/transactions` · `POST /v1/sync` · `POST /v1/accounts/{id}/actual-balance` ·
`GET /v1/reconciliation` · `GET /v1/runs` · `GET /v1/events` · `GET /v1/review` · `GET /panel`
