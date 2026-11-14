# ADR 0005 · Runner con @actual-app/api para importar sin Actual abierto

**Contexto.** Actual es local-first: solo un cliente con loot-core puede escribir movimientos. Sin un cliente
abierto no se importa nada.
**Decisión.** Un contenedor `avia-runner` usa `@actual-app/api` compilado desde el MISMO fork (incluye la
rama `avia` de `syncAccount`) y llama a `runBankSync` tras cada sincronización de AVIA. No hay SQL directo (§3.9).
