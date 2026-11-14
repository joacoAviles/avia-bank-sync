# Cómo funciona la integración

```
UI (Set up / Link) ──send()──▶ loot-core (avia-*) ──HTTP──▶ sync-server /avia/* ──Bearer──▶ avia-api
Bank sync (UI, sincronización automática o runner) ──▶ syncAccount('avia') ──▶ /avia/transactions ──▶ AVIA DB
```
- **Al abrir Actual:** la *Sincronización automática* nativa (p. ej. «cada 12 horas») dispara el bank sync.
  AVIA responde desde su base si los datos están frescos, o sincroniza esa conexión primero. No hay código extra.
- **Sin Actual abierto:** `avia-runner` recibe `POST /run` de AVIA tras cada sincronización (y cada 24 h como
  respaldo), abre el presupuesto con `@actual-app/api` y llama a `runBankSync` solo para las cuentas `avia`.
  Después informa el saldo conciliado a AVIA para la conciliación.
- **Estados en Actual:** tarjeta del proveedor (Configured / Not configured), modal Set up (estado por
  conexión, último éxito, errores, botón *Reauthorize*), tabla de cuentas con «Última sincronización» y el
  indicador nativo de error o reautorización por cuenta.
- **Desvincular:** el «Unlink» nativo de Actual + aviso a AVIA (`account_mappings`).
