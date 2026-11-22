# AGENTS.md — AVIA Bank Sync

Instrucciones para agentes (Hermes, Claude, Codex) que trabajen en este repo.

## Qué es
Sincroniza bancos chilenos con Actual Budget entrando a cada portal con el RUT y la clave del titular
(Playwright + Chromium). El segundo factor (Mi Pass, código, CAPTCHA) lo aprueba el titular en la vista en vivo; nunca se evade.

- `avia-bank-sync/`: servicio Python (FastAPI, PostgreSQL, scheduler, conectores).
- `actual-avia-integration/`: parche sobre Actual v26.11.0 (proveedor «Bancos chilenos») y runner que importa a Actual.
- `install.sh`: instalador para el servidor Synology (respaldo → build → AVIA → override de Actual → runner).
- `tools/`: grabadores de portales y `mapa_codigo.py`.

## Antes de tocar código
1. Lee **`MAPA-CODIGO.md`**: cada módulo, clase, función y endpoint con su línea de contexto y número de línea.
2. Estado de conectores: Banco de Chile y Ripley leen cuentas, saldos y movimientos; Mercado Pago por Access Token;
   BancoEstado solo login (lectura pendiente); Itaú bloqueado (su portal rechaza ingresos automatizados, Error 15).

## Pruebas
```bash
cd avia-bank-sync
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# PostgreSQL 16 en localhost:5432, usuario avia/avia, base avia_test (o AVIA_TEST_DATABASE_URL)
.venv/bin/pytest -q
```
Las pruebas verifican también que toda función del servicio tenga docstring y que `MAPA-CODIGO.md` esté al día.

## Reglas
- Toda función nueva lleva una docstring de una línea (qué hace, no cómo). Después: `python3 tools/mapa_codigo.py`.
- Cambios por rama + PR, con `pytest` en verde. Nunca push directo a `main`.
- Producción (Actual y AVIA en el servidor) nunca sin respaldo y sin el OK del dueño; sigue `avia-bank-sync/docs/OPERATIONS.md`.
- RUT, claves, tokens, Sync ID y llaves de cifrado nunca en logs, commits, issues ni chat.
