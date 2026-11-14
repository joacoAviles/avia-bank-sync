# Viabilidad de conectividad bancaria

> **Actualización 2026-11-14 (ADR 0008):** por decisión del dueño, los bancos se conectan
> **iniciando sesión en su portal** con RUT y clave del titular (login asistido). Este documento
> queda como registro de la investigación de APIs oficiales.

**Fecha de consulta:** 14 de noviembre de 2026 · **Presupuesto para proveedores externos:** $0 CLP

## Conclusión

Hoy **ninguna de las tres instituciones objetivo ofrece un mecanismo autorizado y gratuito**
para que un desarrollador independiente lea saldos y movimientos de cuentas de **personas naturales**.
Por regla del proyecto (§3.6, §4.4 y §20) esto se documenta como **bloqueo**: no se
implementó scraping ni se recurrió a agregadores de pago.

La vía regulada es el **Sistema de Finanzas Abiertas (SFA)** de la Ley Fintec 21.521. Su entrada en
vigencia es en **julio de 2027**, y desde unos 9 meses antes existe un ambiente de pruebas (Sandbox y
Directorio). Para participar como receptor de datos, AVIA Rockets SpA tendría que inscribirse ante la CMF.

Todo lo demás (motor, base de datos, scheduler, integración nativa en Actual, despliegue) está
construido y probado con un **conector sandbox de datos ficticios**. Cuando exista acceso
autorizado, solo hay que escribir el conector del banco con el contrato `BankConnector`.

## Matriz

| Institución    | API oficial                                   | Acceso personal | Gratuito    | Producción                  | Estado      |
| -------------- | --------------------------------------------- | --------------- | ----------- | --------------------------- | ----------- |
| Banco de Chile | Sí, **solo empresas** (API Store, oct. 2025)   | No encontrado   | No informado | Contratación comercial      | **Bloqueado** |
| Itaú Chile     | No se encontró portal público                  | No encontrado   | —           | —                           | **Bloqueado** |
| Banco Ripley   | No; solo vía agregador comercial (Floid)       | Vía agregador   | No ($0 lo excluye) | —                    | **Bloqueado** |
| SFA (CMF)      | Estándar regulado (NCG 514 + NCG 569)          | Sí, con consentimiento | Por definir | Julio 2027        | **Futuro**  |

## Detalle por fuente

### Banco de Chile — ver [BANCO-CHILE.md](BANCO-CHILE.md)
- **Evidencia:** en octubre de 2025 Banco de Chile presentó una *API Store* para integraciones con
  empresas: transferencias, distribución de fondos, alertas y cartolas, contratable por clientes
  corporativos, con sandbox antes de contratar. La fuente no menciona personas naturales ni costos.
  Fuente: https://chocale.cl/2025/10/banco-de-chile-solucion-api-store-integraciones-empresas/
- **Restricciones:** orientada a clientes corporativos, requiere contratación.
- **Certeza:** media. La fuente es prensa, no la documentación del banco (no se encontró un portal público).
- **Próxima acción:** consultar formalmente al banco (ejecutivo empresas de Avia Rockets SpA) si la API
  de cartolas puede leer cuentas de una persona natural con su autorización, a qué costo y con qué
  contrato. Si es pagada, se documenta y se pide aprobación (§20).

### Sistema de Finanzas Abiertas (CMF)
- **Evidencia:** la CMF publicó el 1 de junio de 2026 la modificación de la NCG 514 (NCG 569) con el
  anexo técnico del SFA, y pospuso la entrada en vigor a julio de 2027.
  Fuente: https://www.cmfchile.cl/portal/prensa/625/w4-article-110881.html
- La propuesta de modificación extendió el plazo de 24 a 36 meses e incluyó ambientes de prueba
  (Sandbox y Directorio) habilitados 9 meses antes de la entrada en vigencia.
  Fuente: https://www.carey.cl/propuesta-normativa-de-la-cmf-a-la-ncg-n514-posterga-en-12-meses-la-entrada-en-vigencia-del-sistema-de-finanzas-abiertas-y-otorga-mayor-gradualidad-en-su-implementacion
- **Restricciones:** requiere inscripción como participante, certificaciones de seguridad y funcionales.
  No hay costos publicados para pequeños participantes (por verificar).
- **Certeza:** alta en el calendario (fuente oficial CMF); baja en costos y requisitos para un participante pequeño.
- **Próxima acción:** revisar en cmfchile.cl ("Ley Fintec") los requisitos de inscripción como
  proveedor de servicios basados en información y si el sandbox está abierto a postulantes.

### Itaú Chile — ver [ITAU.md](ITAU.md)
- **Evidencia:** no se encontró portal de desarrolladores público ni productos de API para cuentas
  personales (búsquedas del 14-11-2026; Open Banking Tracker lista Itaú Chile sin recursos para desarrolladores).
- **Certeza:** media (ausencia de evidencia).
- **Próxima acción:** consulta directa al banco; sin respuesta, esperar el SFA.

### Banco Ripley — ver [RIPLEY.md](RIPLEY.md)
- **Evidencia:** sin API pública; Open Banking Tracker lo muestra accesible solo vía el agregador
  Floid, cuya documentación lista Ripley con productos y transacciones.
  Fuentes: https://openbankingtracker.com/provider/banco-ripley · https://readme.floid.io/docs/bancos
- **Restricciones:** un agregador comercial queda fuera del presupuesto $0 (§20).
- **Certeza:** media.
- **Próxima acción:** esperar el SFA. Usar Floid solo si se aprueba un presupuesto explícito.

### Referencia: Bci (no es objetivo, pero muestra lo que se busca)
Bci sí tiene un API Market con portal de desarrolladores y sandbox gratuito con datos simulados;
el paso a producción requiere solicitud formal y evaluación del banco.
Fuente: https://www.bci.cl/apimarket

## Qué NO se hizo (deliberadamente)
- Automatizar el portal web o la app (RPA/scraping): pide guardar la clave bancaria, choca con
  MFA/Mi Pass/Digipass y probablemente con las condiciones de uso. Está descartado salvo una
  evaluación legal explícita (§4.4).
- Integrar Floid, Fintoc, Belvo u otros agregadores: tienen costo por conexión, lo que viola el presupuesto $0.
