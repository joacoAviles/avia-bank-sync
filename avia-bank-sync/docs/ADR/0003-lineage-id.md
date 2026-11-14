# ADR 0003 · ID estable (lineage) para pendientes que pasan a contabilizados

**Contexto.** Los bancos suelen cambiar el ID cuando un pendiente se contabiliza. El fuzzy matching de Actual
puede fallar si cambian la fecha o la descripción.
**Decisión.** AVIA entrega a Actual el `lineage_id` del primer avistamiento y lo conserva al promover.
Actual hace match exacto por `imported_id` y solo actualiza `cleared`.
