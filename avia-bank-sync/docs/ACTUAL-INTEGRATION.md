# Auditoría técnica de Actual Budget 26.11.0 e integración nativa de AVIA

Fuente inspeccionada: `actualbudget/actual`, tag `v26.11.0`
(commit `1766241e3f4b3c578e424c4fa15f1eb83c0da17d`), monorepo con `packages/loot-core`,
`packages/desktop-client` y `packages/sync-server`.

## 1. Estructura real de los proveedores existentes

En 26.11.0 hay **cinco** proveedores: GoCardless, SimpleFIN y Pluggy.ai (siempre visibles), más
Akahu y Enable Banking (detrás de *feature flags*). Cada uno existe en tres capas:

| Capa | Dónde | Rol |
| --- | --- | --- |
| sync-server | `packages/sync-server/src/app-<proveedor>/` montado en `src/app.ts` (`app.use('/akahu', …)`) | Habla con el servicio externo. Guarda los secretos en la tabla `secrets` del servidor |
| loot-core (cliente) | `src/server/accounts/app.ts` (handlers `<p>-status`, `<p>-accounts`, `<p>-accounts-link`) y `src/server/accounts/sync.ts` (`download<P>Transactions`) | Vincula cuentas y descarga movimientos desde el sync-server |
| desktop-client | `components/banksync/useBuiltInBankSyncProviders.ts`, `components/modals/<P>InitialiseModal.tsx`, `SelectLinkedAccountsModal.tsx` | Tarjeta del proveedor, Set up y Link bank account |

El proveedor más reciente y simple (**Akahu**) toca 18 archivos. AVIA sigue el mismo patrón.

## 2. Archivos responsables del listado de proveedores
- `desktop-client/src/components/banksync/bankSyncUtils.ts`: `BUILT_IN_BANK_SYNC_PROVIDERS` y nombres legibles.
- `desktop-client/src/components/banksync/useBuiltInBankSyncProviders.ts`: construye cada tarjeta
  (`displayName`, `isConfigured`, `onConfigure` = Set up, `onLink` = Link bank account, `onReset`).
- `desktop-client/src/components/banksync/BuiltInProviders.tsx`: renderiza las tarjetas (no se modificó).
- `loot-core/src/types/models/bank-sync.ts`: `SYNC_PROVIDERS` (tipo de `account_sync_source`).

## 3. Flujo real de Set up
Tarjeta → `onConfigure` → `pushModal({ name: '<p>-init' })` → el modal guarda los secretos
(`send('secret-set', …)` → `POST /secret` del sync-server, solo admin) → `onSuccess` marca el proveedor como configurado.
**AVIA:** el modal `avia-init` no guarda secretos en Actual. Crea, reautoriza o elimina **conexiones**
en el servicio AVIA (`avia-connection-*` → `/avia/connections/*`, solo admin). El token de servicio vive
en variables de entorno del contenedor de Actual y nunca llega al navegador.

## 4. Flujo real de Link bank account
`onLink` → `send('<p>-accounts')` → normaliza a `{account_id, name, institution, orgDomain, orgId, balance}`
→ modal `select-linked-accounts` (`syncSource`) → mutación `useLinkAccount<P>Mutation` →
handler `<p>-accounts-link` → `link.findOrCreateBank` + inserta o actualiza la cuenta con
`account_sync_source` → `bankSync.syncAccount(...)` hace la primera sincronización y crea el saldo inicial.

## 5. Interfaces de sincronización
`syncAccount()` despacha por `account_sync_source` a `download<P>Transactions()`, que debe devolver:
`{ transactions: BankSyncTransaction[] (más reciente primero), accountBalance, startingBalance }`.
`processBankSyncDownload` → `normalizeBankSyncTransactions` (`transactionId` → `imported_id`,
`booked` → `cleared`, `transactionAmount.amount` → `amountToInteger`) → `reconcileTransactions`
(match exacto por `imported_id` y difuso por monto y fecha ±7 días) → reglas → `batchUpdateTransactions` (`runTransfers`).
También es relevante:
- `useAutomaticBankSync` (desktop-client): ya **sincroniza automáticamente mientras Actual está
  abierto**, según la preferencia *Sincronización automática*.
- `api/bank-sync` en `@actual-app/api`: permite el mismo bank sync en modo headless.

## 6. Manejo de credenciales
Los proveedores comerciales guardan sus secretos en el sync-server (`services/secrets-service.js`,
tabla `secrets`, global o por archivo). AVIA no usa esa tabla: sus secretos bancarios quedan cifrados
con Fernet en PostgreSQL de AVIA, y el token Actual↔AVIA va en `AVIA_API_TOKEN(_FILE)`.

## 7. Persistencia
Las cuentas viven en la tabla `accounts` del presupuesto (CRDT, sincronizada entre dispositivos):
`account_id` (ID externo), `bank`, `account_sync_source`, `last_sync`, `bank_sync_status`.
Los movimientos se escriben **solo** mediante los mutadores de loot-core. Nunca SQL directo.

## 8. Manejo de errores
`download*` lanza `BankSyncError(category, code)`. `ITEM_ERROR/ITEM_LOGIN_REQUIRED` se traduce a
estado *requiere reautorización* (`getBankSyncStatusFromError`). Los demás quedan como error y
se guardan por cuenta (`persistBankSyncError`). AVIA responde exactamente ese par cuando un banco
pide reautorizar, así Actual muestra su propio indicador.

## 9. Estrategia de integración mínima (implementada)
Un parche (`actual-avia-integration/patches/0001-avia-bank-sync-provider.patch`) con
**13 archivos modificados + 6 nuevos** (dos son pruebas). No se tocan el presupuesto, los informes,
las reglas, los beneficiarios ni el motor de conciliación.

Decisiones clave verificadas en el código:
- **Montos CLP:** Actual guarda CLP con 2 decimales internos (`shared/currencies.ts`). AVIA envía
  `"−15990.00"` (string exacta, sin float) y `startingBalance` como entero ×100.
- **Pendiente → contabilizado sin duplicar:** AVIA mantiene el mismo `transactionId` (lineage)
  cuando el banco cambia el ID. Actual lo encuentra por `imported_id` y solo actualiza `cleared`.
- **Pagos de tarjeta como transferencias:** `resolvePayee` respeta un `payee` ya asignado. Si la
  contrapartida aún no existe, se asigna el payee de transferencia de la tarjeta y `runTransfers`
  crea el espejo, con el que el abono de la tarjeta se concilia después. Si ya existe (la tarjeta
  se vinculó primero), se enlazan ambas como lo hace «Make transfer» (`transfer_id` cruzado,
  `runTransfers: false`). Está probado en ambos órdenes.
- **Saldo inicial:** `startingBalance` de AVIA es el saldo **contable**, así que solo se descuentan
  los movimientos contabilizados (los pendientes no están en ese saldo).
- **Al abrir Actual:** no se agregó código. `useAutomaticBankSync` (preferencia *Sincronización
  automática*, p. ej. cada 12 h) llama a AVIA. AVIA responde desde su base si los datos tienen
  menos de `AVIA_FRESHNESS_HOURS`, o sincroniza esa conexión primero si están viejos. No bloquea la interfaz.
- **Sin Actual abierto:** el **runner** (`@actual-app/api` compilado desde el mismo fork) llama a
  `runBankSync` tras cada sincronización de AVIA y como respaldo cada 24 h.

## 10. Riesgos de actualización
| Riesgo | Mitigación |
| --- | --- |
| Upstream refactoriza `useBuiltInBankSyncProviders` o `SelectLinkedAccountsModal` (cambiaron en 2026) | `git apply --check` en CI. El parche es aditivo: copia el patrón de Akahu |
| Cambia el contrato de `BankSyncResponse` / `processBankSyncDownload` | `sync-avia.test.ts` lo cubre (saldo inicial, transferencias, idempotencia, reautorización) |
| Upstream agrega su propio proveedor `'avia'` (improbable) | Renombrar el identificador en el parche |
| `@actual-app/api` deja de incluir loot-core | El runner fallaría al arrancar. Se detecta en la verificación de la imagen |
| Actualizar Actual sin el parche borra el proveedor | Las cuentas quedan con `account_sync_source='avia'` y fallan con «Unrecognized provider». No se pierden datos. Volver a la imagen AVIA |

## 11. Pruebas necesarias (implementadas)
Ver `actual-avia-integration/docs/UPGRADES.md` → checklist de 9 puntos (§19), automatizado en
`scripts/verify.sh` y `tests/e2e.mjs`.

## 12. Evaluación: ¿cómo corre con Actual "en el mismo Docker"?
Se evaluaron tres opciones:

| Opción | Descripción | Veredicto |
| --- | --- | --- |
| A. Todo en un compose | Reemplazar el compose de Actual por uno con Actual + AVIA | ✗ Mezcla ciclos de vida; un error de AVIA puede tumbar Actual al hacer `up` |
| **B. Dos proyectos, una red** | Actual sigue en `/volume1/docker/actual-budget` (solo cambia la imagen y se agregan 2 variables). AVIA es un proyecto aparte que se une a `actual-budget_default` | ✓ **Recomendada** (cumple §5 y §18) |
| C. AVIA dentro del contenedor de Actual | Un solo contenedor | ✗ Rompe la separación y complica las actualizaciones |

Con la opción B:
- `actual-budget` → `http://avia-api:8000` (alias en la red compartida).
- `avia-runner` → `http://actual-budget:5006`.
- PostgreSQL solo está en `avia_internal` (`internal: true`): sin puertos ni salida a Internet.
- Cloudflare Tunnel **no se toca**: AVIA no se publica. El panel técnico solo escucha en
  `127.0.0.1:8070` del NAS (se accede por túnel SSH).
- Rollback: volver a la imagen oficial `actualbudget/actual-server:26.11.0` deja Actual operativo;
  las cuentas AVIA quedan sin sincronizar hasta volver a la imagen AVIA.
