# Roadmap

| Fase | Estado |
| --- | --- |
| 0 · Auditoría de Actual 26.11.0 | ✅ [ACTUAL-INTEGRATION.md](ACTUAL-INTEGRATION.md) |
| 1 · Viabilidad bancaria | ✅ Concluida: **bloqueo** documentado ([BANK-CONNECTIVITY.md](BANK-CONNECTIVITY.md)) |
| 2 · Repos y arquitectura | ✅ `avia-bank-sync` + `actual-avia-integration` |
| 3 · Motor AVIA | ✅ API, scheduler, PostgreSQL, cursores, locks, idempotencia, auditoría, healthchecks (27 pruebas) |
| 4 · Integración nativa | ✅ Proveedor en Actual, Set up, Link, estados, sync, runner (E2E en stack real) |
| 5a · Login en portales (Banco de Chile, Itaú, Ripley) | ✅ Login asistido con vista en vivo para Mi Pass/código/CAPTCHA (ADR 0008). Probado contra portal falso; **pendiente: primer login real** |
| 5b · Extracción de datos por portal | ⏭️ Siguiente: mapear cada portal ya autenticado |
| 7 · Producción en el NAS | 🟡 Artefactos listos (compose, respaldos, rollback). Falta construir las imágenes y desplegar con aprobación |

## Próximos pasos
1. Consultas formales a Banco de Chile e Itaú (ver BANCO-CHILE.md).
2. Seguir la publicación del sandbox y del directorio del SFA en cmfchile.cl. Evaluar la inscripción de AVIA Rockets SpA.
3. Cuando haya acceso: `avia/connectors/<banco>.py` con el contrato `BankConnector`, pruebas con
   cartolas oficiales, y quitar el banco de `blocked.py`.
4. Desplegar en el NAS con el sandbox en un **presupuesto de prueba** para validar la operación real
   (scheduler, runner, respaldos) antes de tener un banco.
