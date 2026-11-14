# Parches

## 0001-avia-bank-sync-provider.patch
| Paquete | Archivo | Cambio |
| --- | --- | --- |
| sync-server | `src/app-avia/app-avia.ts` (nuevo) | Proxy `/avia/*` → AVIA (status, accounts, transactions, sync, connections/*, **logins/start·status·input**, unlink). Admin para conexiones y logins. Token por env/secret |
| sync-server | `src/app-avia/app-avia.test.ts` (nuevo) | 8 pruebas (sesión, login asistido, token no expuesto, admin, errores, servicio caído) |
| sync-server | `src/app.ts` | `app.use('/avia', …)` (+2 líneas) |
| loot-core | `types/models/avia.ts` (nuevo), `types/models/index.ts`, `types/models/bank-sync.ts` | Tipos y `'avia'` en `SYNC_PROVIDERS` |
| loot-core | `server/server-config.ts` | `AVIA_SERVER` |
| loot-core | `server/db/types/index.ts` | `'avia'` en el tipo de `account_sync_source` |
| loot-core | `server/accounts/app.ts` | `linkAviaAccount` (sin duplicar cuentas), `avia-status/accounts/sync/connection-*`, `avia-login-start/status/input`, aviso a AVIA al desvincular |
| loot-core | `server/accounts/sync.ts` | `downloadAviaTransactions`, `linkAviaTransfers`, rama en `syncAccount`, saldo inicial contable |
| loot-core | `server/accounts/sync-avia.test.ts` (nuevo) | 5 pruebas (saldo inicial, transferencias en ambos órdenes, idempotencia, pendiente→contabilizado, reautorización) |
| desktop-client | `banksync/useBuiltInBankSyncProviders.ts`, `banksync/bankSyncUtils.ts` | Tarjeta AVIA siempre visible |
| desktop-client | `modals/AviaInitialiseModal.tsx` (nuevo), `hooks/useAviaStatus.ts` (nuevo), `Modals.tsx`, `modals/modalsSlice.ts` | Set up «Bancos chilenos»: banco + RUT (validado) + clave, progreso del login, **vista en vivo** clicable para Mi Pass/código/CAPTCHA, volver a iniciar sesión |
| desktop-client | `accounts/mutations.ts`, `modals/SelectLinkedAccountsModal.tsx` | Link bank account (`syncSource: 'avia'`) |

Regenerar el parche desde un árbol de trabajo:
```bash
git add -N <archivos nuevos> && git diff v26.11.0 -- packages/ > patches/0001-avia-bank-sync-provider.patch
```
