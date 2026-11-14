# Estrategia de sincronización

## Ventana y cursores
- Primera vez: `AVIA_INITIAL_HISTORY_DAYS` (90 por defecto, máximo `AVIA_MAX_HISTORY_DAYS` = 365).
- Después: desde `último contabilizado confirmado − AVIA_OVERLAP_DAYS` (10 días), para recoger
  correcciones tardías del banco.
- El cursor avanza **en la misma transacción SQL** que los movimientos. Si el proceso muere, se
  hace rollback de todo lo de esa cuenta y la próxima ejecución reanuda sin perder ni duplicar.
- Al arrancar, las ejecuciones que quedaron en `running` sin lock vivo pasan a `interrupted`.

## Concurrencia
Un lock consultivo de PostgreSQL (`pg_try_advisory_lock`) garantiza **una sola ejecución a la vez**,
la dispare quien la dispare (scheduler, Actual, panel). Si el proceso cae, PostgreSQL libera el lock.

## Reglas de importación
| Caso | Comportamiento |
| --- | --- |
| Mismo ID bancario | Sin cambios, o `UPDATE` de los campos que cambiaron (evento `transaction_updated`). Nunca degrada contabilizado → pendiente |
| Contabilizado con `pending_ref` a un pendiente conocido | Se promueve la misma fila; `lineage_id` intacto → Actual actualiza `cleared` |
| Contabilizado sin referencia | Coincidencia conservadora: mismo monto y moneda, ±4 días, descripción compatible, **exactamente 1** candidato. Si hay varios → nuevo con `needs_review` |
| Pendiente que desaparece (y el conector garantiza lista completa) | `reversed` + `needs_review`; ya no se exporta a Actual |
| Monto `float`, sin ID, moneda inválida, divisa sin tipo de cambio | Rechazado y auditado (`transaction_rejected`) |
| Pago de tarjeta | `card_payment` (cuenta) ↔ `payment` (tarjeta), mismo monto, ±3 días y referencia si existe → `transfer_peer_id`. En Actual queda como transferencia |
| Compras en cuotas | `installment_number/total`; nota «Cuota n/N» |

ID entregado a Actual: `avia:<banco>:<cuenta externa>:<ID bancario del primer avistamiento>`.

## Saldos
- `booked` (contable) se usa para el saldo inicial y la conciliación.
- `available` (disponible) es informativo y nunca reemplaza al contable.
- Diferencia = contable banco − saldo conciliado en Actual. Si ≠ 0 se genera el evento
  `balance_mismatch` con causas posibles. **Nunca se corrigen movimientos para ocultarla.**

## Frescura
`AVIA_FRESHNESS_HOURS` (12): si Actual pide movimientos y la última sincronización exitosa de esa
conexión tiene más de 12 h, AVIA sincroniza primero. Si no, responde desde su base.

## Categorización
AVIA no crea categorías ni reglas. Entrega `payeeName` limpio (contraparte o descripción). Las
reglas existentes de Actual (por ejemplo, COPEC → Transporte/Combustible) se aplican solas en la importación.
