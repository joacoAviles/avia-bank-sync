# AVIA Bank Sync

Bancos chilenos (Banco de Chile, Itaú, Ripley) dentro de Actual Budget.

- `avia-bank-sync/` — servicio AVIA (FastAPI + PostgreSQL + login por portal)
- `actual-avia-integration/` — parche de Actual (proveedor «Bancos chilenos») + runner

## Instalar en el servidor (un solo comando)

```bash
git clone https://github.com/joacoAviles/avia-bank-sync.git
cd avia-bank-sync && sudo bash install.sh
```

Pide la contraseña de Actual y el Sync ID; respalda Actual, construye imágenes, levanta AVIA y cambia la imagen de Actual. Deja `rollback-avia.sh`.
