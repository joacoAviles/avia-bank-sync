# Seguridad

| Control | Implementación |
| --- | --- |
| Credenciales bancarias | Cifradas con Fernet (AES-128-CBC + HMAC-SHA256) en `credentials.ciphertext`. Nunca en texto plano, en Git ni en logs |
| Rotación de llaves | `AVIA_ENCRYPTION_KEYS="nueva,antigua"`: cifra con la primera y descifra con todas (`MultiFernet`). `SecretBox.rotate()` re-cifra |
| Solo campos declarados | `create_connection` descarta todo campo que el conector no declare en `setup_fields` |
| Autenticación Actual ↔ AVIA | Bearer de ≥ 32 caracteres, comparación en tiempo constante. En Actual vive en `AVIA_API_TOKEN_FILE` (Docker secret) y nunca llega al navegador |
| Autorización | Las rutas `/avia/*` exigen sesión válida de Actual; crear, eliminar y reautorizar conexiones exige **admin** |
| Red | PostgreSQL solo en `avia_internal` (`internal: true`, sin puertos). AVIA no se publica en Cloudflare Tunnel. Panel solo en `127.0.0.1` |
| Contenedores | Usuario no root, `read_only`, `no-new-privileges`, tini |
| Logs | JSON. Redacción automática de claves `password/secret/token/authorization/clave/rut/cookie`. Los errores no incluyen movimientos completos (solo `lineage_id` o máscara) |
| Datos mostrados | Cuentas con número enmascarado (`****0001`) |
| Respaldos | `pg_dump` → gzip → AES-256-CBC con PBKDF2 (200 000 iteraciones), 30 días de retención |
| Al eliminar una conexión | Se borra el secreto; el historial se conserva para auditoría |
| Límites | Rate limit de 500 req/min del sync-server de Actual. Una sola sincronización a la vez |
| Prohibido por diseño | Scraping, evadir MFA/CAPTCHA/antifraude, simular autorizaciones (ver BANK-CONNECTIVITY.md) |

## Pendiente antes de un banco real
- Revisión de los requisitos de seguridad del SFA (certificaciones del anexo técnico de la NCG 569).
- mTLS / certificados si el banco o el SFA lo exigen. Se agregan en el conector.
- Copia de `encryption_keys` y `backup_key` fuera del NAS (gestor de contraseñas).
