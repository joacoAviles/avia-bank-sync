# ADR 0004 · Pagos de tarjeta como transferencias sin modificar reglas del usuario

**Decisión.** AVIA empareja la salida (`card_payment`) con el abono (`payment`). En loot-core: si la
contrapartida no existe, se asigna el payee de transferencia (`runTransfers` crea el espejo, que luego concilia
con el abono). Si ya existe, se enlazan ambas igual que «Make transfer». Así el pago no cuenta como gasto,
en cualquier orden de vinculación, sin crear ni alterar reglas (§15).
