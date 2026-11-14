# ADR 0001 · AVIA como proveedor nativo mediante un parche sobre Actual

**Estado:** aceptada · 2026-11-14

**Contexto.** El objetivo es que AVIA aparezca en «Enlazar cuenta → Providers». Actual 26.11.0 no tiene
sistema de plugins de bank sync: los proveedores están cableados en loot-core, sync-server y desktop-client.
`@actual-app/api` no puede registrar proveedores en la interfaz.

**Decisión.** Mantener un parche único y aditivo (patrón Akahu, 19 archivos), aplicado sobre un tag
oficial bloqueado en `version-lock.json`. La imagen se construye con el `sync-server.Dockerfile` **oficial** sin cambios.

**Alternativas.** (a) Fork completo con ramas: más ruido en los merges. (b) Importador externo con
`@actual-app/api`: no aparece como proveedor y viola §1. (c) Esperar un sistema de plugins upstream: no existe.

**Consecuencias.** Cada actualización de Actual exige re-aplicar y verificar (`scripts/verify.sh`, `tests/e2e.mjs`).
