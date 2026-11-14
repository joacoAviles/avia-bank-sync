# Banco de Chile

**Estado: BLOQUEADO para cuentas personales** (consulta del 2026-11-14). Detalle y fuentes en [BANK-CONNECTIVITY.md](BANK-CONNECTIVITY.md).

| Punto (§4.1) | Hallazgo | Certeza |
| --- | --- | --- |
| API oficial de saldos y movimientos | API Store para **empresas** (oct. 2025): transferencias, distribución de fondos, alertas y cartolas | Media (prensa) |
| Personas naturales | Sin evidencia | Media |
| Enrolamiento / producción | «Procesos de contratación» de clientes corporativos; sandbox previo; onboarding digital anunciado | Media |
| Sandbox | Sí, según la fuente | Media |
| OAuth / scopes / renovación / límites | No publicados | — |
| Costos | No publicados | — |
| Tarjetas de crédito / cuenta corriente / saldo contable vs disponible | No documentado para la API. Los portales (Mi Banco, Banconexión) sí los muestran | — |

**Conector:** `avia/connectors/blocked.py::BancoChileConnector`. Visible en Set up con su motivo; rechaza conexiones (`INSTITUTION_BLOCKED`).

**Próximas acciones**
1. Consulta formal vía el ejecutivo empresas de Avia Rockets SpA: ¿la API de cartolas permite leer cuentas de una persona natural con su autorización? ¿Costo? ¿Contrato?
2. Si la respuesta es «sí, pagado»: documentar el costo y pedir aprobación (§20).
3. Si es «no»: esperar el SFA (julio 2027) y evaluar inscribir a AVIA Rockets SpA en su sandbox.
