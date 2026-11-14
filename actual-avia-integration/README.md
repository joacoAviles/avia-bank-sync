# actual-avia-integration

Integración nativa de **AVIA Bank Sync** en **Actual Budget**, mantenida como **parche sobre un tag oficial**.

| | |
| --- | --- |
| Upstream | `actualbudget/actual` **v26.11.0** (`version-lock.json`) |
| Versión AVIA | `26.11.0-avia.1` |
| Parche | `patches/0001-avia-bank-sync-provider.patch`: 13 archivos modificados + 6 nuevos (+2 082 líneas) |
| Imágenes | `aviarockets/actual-server:26.11.0-avia.1`, `aviarockets/avia-actual-runner:26.11.0-avia.1` |

## Qué agrega a Actual
- **«Bancos chilenos»** como cuarto proveedor visible (sin feature flag), con *Set up* (iniciar sesión en
  Banco de Chile, Itaú o Ripley con RUT y clave, vista en vivo para Mi Pass/código/CAPTCHA, volver a iniciar sesión) y *Link bank account* (flujo nativo
  `SelectLinkedAccountsModal`: cuentas nuevas o existentes).
- `app-avia` en el sync-server: proxy autenticado hacia el servicio AVIA (el token no llega al navegador).
- `account_sync_source = 'avia'` en loot-core: descarga, saldo inicial contable, pagos de tarjeta como
  transferencias, errores de reautorización nativos.
- `runner/`: importación headless con `@actual-app/api` del mismo fork.

## Uso
```bash
scripts/prepare-source.sh          # clona v26.11.0 y aplica el parche (verifica el commit)
scripts/verify.sh                  # typecheck + pruebas de regresión
scripts/build-images.sh [--push]   # imágenes (8 GB RAM: no en el NAS)
node tests/e2e.mjs                 # E2E contra un stack levantado
```

## Verificado el 2026-11-14
- `yarn typecheck` del monorepo completo ✔ · oxlint/oxfmt ✔
- loot-core `src/server/accounts`: 55 pruebas ✔ (5 de AVIA)
- sync-server: 765 + 7 pruebas de `app-avia` ✔ · desktop-client `banksync`: 36 pruebas ✔
- E2E (PostgreSQL + AVIA + sync-server compilado + `@actual-app/api`): saldos exactos, transferencias,
  idempotencia ✔ · UI renderizada con Chrome ✔ (`docs/screenshots/`)

Docs: [UPSTREAM](docs/UPSTREAM.md) · [INTEGRATION](docs/INTEGRATION.md) · [PATCHES](docs/PATCHES.md) · [UPGRADES](docs/UPGRADES.md)
