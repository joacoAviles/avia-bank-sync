# Arquitectura

```
                        Synology NAS (Docker)
┌──────────── red actual-budget_default ─────────────────────────────────────────┐
│                                                                                │
│  ┌──────────────────────────────┐   /avia/*    ┌──────────────────────────────┐│
│  │ actual-budget (imagen AVIA)  │ ───────────▶ │ avia-api  (FastAPI)           ││
│  │  · desktop-client (UI)       │  Bearer token│  · API v1 + panel técnico     ││
│  │  · sync-server + app-avia    │              │  · scheduler 06:15 CLT        ││
│  └──────────────▲───────────────┘              │  · motor de sincronización    ││
│                 │ api.runBankSync              │  · conectores (sandbox,       ││
│  ┌──────────────┴───────────────┐   POST /run  │    banco-chile*, itau*,       ││
│  │ avia-runner                  │ ◀─────────── │    ripley*)  *bloqueados      ││
│  │  (@actual-app/api del fork)  │              └──────────────┬───────────────┘│
│  └──────────────────────────────┘                             │                │
└───────────────────────────────────────────────────────────────┼────────────────┘
                                          red avia_internal (sin salida)
                                         ┌────────────────────┴───────┐
                                         │ avia-db (PostgreSQL 16)    │◀─ avia-backup
                                         └────────────────────────────┘   (pg_dump AES-256)
```

## Responsabilidades
| Componente | Hace | No hace |
| --- | --- | --- |
| **Actual Budget** | Cuentas, movimientos, categorías, reglas, presupuesto, UI | Hablar con bancos |
| **AVIA Bank Sync** (`avia-api`) | Conectores, autorización, cursores, normalización, deduplicación, conciliación, scheduler, auditoría | Escribir en el presupuesto de Actual |
| **AVIA Actual Integration** (parche + runner) | Proveedor en «Enlazar cuenta», Set up, Link, traducción al contrato de bank sync de Actual, import headless | Lógica bancaria |

## Flujo de un movimiento
1. Scheduler (o Actual con datos viejos) → `SyncEngine.run()` toma el lock de PostgreSQL.
2. El conector entrega `BankTransaction` (Decimal, ID bancario, pendiente/contabilizado).
3. El motor valida, deduplica (`transaction_identifiers`), promueve pendientes manteniendo el
   `lineage_id`, marca revertidos, empareja pagos de tarjeta, guarda saldo y avanza el cursor,
   todo en **una transacción SQL por cuenta**.
4. Actual (UI, sincronización automática o runner) llama a `/avia/transactions` y recibe un
   `BankSyncResponse`. `reconcileTransactions` de Actual inserta o actualiza.
5. El runner informa el saldo conciliado de Actual → `balance_snapshots.difference`.

## Contrato de conectores
`avia/connectors/base.py`: `authenticate`, `get_accounts`, `get_balances`, `get_transactions`,
`refresh_authorization` y `capabilities`. Las capacidades son explícitas: por ejemplo, solo se
detectan pendientes revertidos si el conector declara `COMPLETE_PENDING_LIST`.

Ver también: [SYNC-STRATEGY.md](SYNC-STRATEGY.md), [DATA-MODEL.md](DATA-MODEL.md), [SECURITY.md](SECURITY.md).
