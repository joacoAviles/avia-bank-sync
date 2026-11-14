# ADR 0002 · El sync-server de Actual hace de proxy hacia AVIA

**Decisión.** El cliente (navegador) habla solo con `/avia/*` del sync-server, que agrega el token de servicio
y reenvía a `avia-api` por la red Docker interna. **Motivo:** el token nunca llega al navegador, AVIA no se expone
y se reutilizan la sesión y el control de admin de Actual. Es el mismo patrón que los demás proveedores.
