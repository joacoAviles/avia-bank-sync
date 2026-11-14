# Actualizar Actual Budget

**Nunca** actualizar Actual automáticamente (sin Watchtower ni `:latest`) mientras se use la imagen AVIA.

1. `version-lock.json` → nuevo `tag` y `commit`.
2. `scripts/prepare-source.sh`. Si `git apply --check` falla, rehacer el parche sobre el nuevo tag
   siguiendo el patrón del proveedor más reciente de upstream y subir la versión a `<tag>-avia.1`.
3. `scripts/verify.sh` (typecheck + regresión).
4. Levantar un stack de prueba (Postgres + AVIA + sync-server compilado) y ejecutar `node tests/e2e.mjs`.
5. Checklist manual (§19), en un **presupuesto de prueba**:
   1. Abre Actual · 2. Presupuestos accesibles · 3. Cuentas accesibles · 4. Set up de AVIA ·
   5. Link bank account · 6. Sincronización · 7. Re-sincronizar sin duplicados ·
   8. Reiniciar contenedores y verificar persistencia · 9. Apagar avia-api: Actual sigue operando y muestra el error.
6. `scripts/build-images.sh --push` → en el NAS: respaldo → cambiar el tag de la imagen → `docker compose up -d`.
7. **Rollback:** volver al tag anterior de la imagen. El formato del presupuesto lo gestiona Actual.
   Si upstream migró el esquema, restaurar el respaldo del paso de despliegue.
