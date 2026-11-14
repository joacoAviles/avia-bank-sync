# Modelo de datos (PostgreSQL)

Esquema: `database/migrations/001_initial.sql`. Migraciones numeradas, aplicadas al arrancar bajo
lock, cada una atómica y registrada en `schema_migrations`.

| Tabla | Propósito | Claves e índices |
| --- | --- | --- |
| `banks` | Instituciones y su conector | PK `id` |
| `connections` | Conexiones autorizadas (estado, último éxito, error) | índice parcial de activas |
| `credentials` | Secretos cifrados por conexión + `key_id` | PK = `connection_id` |
| `bank_accounts` | Cuentas detectadas (tipo, moneda, máscara) | UNIQUE (`connection_id`, `external_id`) |
| `actual_accounts` | Cuentas de Actual vistas por AVIA | PK = UUID de Actual |
| `account_mappings` | Banco ↔ Actual (1 a 1, estable) | PK `bank_account_id` |
| `transactions` | Movimientos normalizados. `amount NUMERIC(20,4)`, moneda original, tipo de cambio | `lineage_id` UNIQUE; CHECK de contabilizado con fecha; CHECK de tipo de cambio con fecha |
| `transaction_identifiers` | IDs bancarios y referencias por movimiento | UNIQUE (`bank_account_id`, `scheme`, `value`) |
| `sync_runs` | Ejecuciones (origen, estado, estadísticas) | índice por fecha |
| `sync_cursors` | Último contabilizado confirmado por cuenta | PK `bank_account_id` |
| `balance_snapshots` | Saldo contable, disponible, calculado por Actual y diferencia, uno por día | UNIQUE (cuenta, fecha) |
| `sync_events` | Auditoría (info/warning/error) | índices por fecha y ejecución |
| `pending_authorizations` | Reautorizaciones abiertas | UNIQUE parcial por conexión abierta |

Estados de `transactions.status`: `pending`, `booked`, `reversed`, `deleted`.
Tipos (`kind`): `purchase`, `installment`, `payment`, `card_payment`, `interest`, `fee`, `refund`,
`cash_advance`, `transfer_in/out`, `deposit`, `withdrawal`, `other`.
