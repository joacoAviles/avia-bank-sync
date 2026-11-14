# ADR 0008 · Login asistido en los portales bancarios (RUT + clave del titular)

**Estado:** aceptada · 2026-11-14 · Reemplaza la 0007.

**Contexto.** Ningún banco objetivo ofrece una API gratuita para personas. El dueño quiere iniciar
sesión desde Actual en cada banco con su RUT y clave, y que AVIA consulte todo automáticamente.

**Decisión.**
- AVIA abre el portal oficial del banco en un **Chromium estándar** (Playwright, ventana real bajo
  Xvfb, sin plugins *stealth* ni identidad falseada), escribe RUT y clave y envía el formulario.
- Si el banco pide un paso humano (Mi Pass, código, CAPTCHA, términos), la sesión pasa a
  `needs_user`: Actual muestra la pantalla en vivo y **el titular** lo resuelve con clics y teclado.
  AVIA nunca resuelve ni evade esos controles.
- Al terminar se guarda, cifrado con Fernet: RUT, clave y `storage_state` (cookies de sesión), para
  reutilizar la sesión y volver a ingresar sin reescribir la clave.
- Selectores por banco en `avia/portal/banks.py`, verificados sobre las páginas públicas de login el 2026-11-14.

**Riesgos aceptados por el dueño.** Puede contravenir condiciones de uso del banco. Si el banco cambia
el portal, el conector se rompe (se ajusta `banks.py`). El reCAPTCHA v3 invisible de Itaú y Ripley
puede rechazar ingresos desde el servidor; en ese caso se informa el rechazo y no se intenta evadirlo.

**Siguiente paso.** Extracción: mapear cómo entrega los datos cada portal ya autenticado y
implementar `get_accounts`, `get_balances` y `get_transactions` en `avia/connectors/portal.py`.
