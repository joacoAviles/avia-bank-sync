# Mercado Pago (cuenta personal, Chile)

**Estado: implementado, pendiente de primera prueba con un token real.**

- Autorización: Access Token de producción del titular (Mercado Pago Developers → Tus integraciones → Credenciales).
  Se guarda cifrado; no se usa RUT ni clave.
- Datos: «Reporte de liberaciones» de la API oficial (`/v1/account/release_report`). Es asíncrono: AVIA pide un
  rango (tramos de 60 días), espera a que aparezca en la lista y descarga el CSV. Cada fila es un movimiento real
  del saldo; el saldo sale del último `BALANCE_AMOUNT` (o del endpoint de saldo si el token lo permite).
- IDs: `SOURCE_ID` no es único (comisiones, retenciones); AVIA arma un ID estable con fecha, descripción, monto y
  ocurrencia.
- Límite conocido: el nombre exacto de columnas puede variar por cuenta; se leen por encabezado.
- Prueba real: crear la conexión desde Actual con el token y revisar el primer reporte.
