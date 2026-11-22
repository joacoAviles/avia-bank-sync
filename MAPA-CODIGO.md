# Mapa del código — AVIA Bank Sync

Generado por `python3 tools/mapa_codigo.py`. No editar a mano: corre el script tras cambiar código.
Cada línea: nombre, línea del archivo (`L`) y su propósito (docstring o comentario).

## Endpoints HTTP
| Ruta | Dónde | Qué hace |
| --- | --- | --- |
| `GET /health` | `avia-bank-sync/avia/api/main.py` L96 `health` | Vida del proceso (sin tocar la base). |
| `GET /ready` | `avia-bank-sync/avia/api/main.py` L102 `ready` | Listo para servir: la base responde e indica si el scheduler corre. |
| `GET /v1/status` | `avia-bank-sync/avia/api/main.py` L169 `status` | Estado general: conexiones, última sincronización, próxima y pendientes de revisión. |
| `GET /v1/institutions` | `avia-bank-sync/avia/api/main.py` L175 `institutions` | Bancos que ofrece AVIA, si están disponibles y qué campos pide su Set up. |
| `GET /v1/connections` | `avia-bank-sync/avia/api/main.py` L181 `connections` | Lista de conexiones con su estado. |
| `POST /v1/connections` | `avia-bank-sync/avia/api/main.py` L187 `create_connection` | Crea una conexión sin login por portal (los bancos con portal usan /v1/logins). |
| `DELETE /v1/connections/{cid}` | `avia-bank-sync/avia/api/main.py` L193 `delete_connection` | Elimina una conexión y borra su credencial cifrada. |
| `POST /v1/connections/{cid}/reauthorize` | `avia-bank-sync/avia/api/main.py` L199 `reauthorize` | Renueva la autorización de una conexión que el banco dejó de aceptar. |
| `POST /v1/logins` | `avia-bank-sync/avia/api/main.py` L205 `login_start` | Abre el portal del banco en Chromium y empieza el ingreso con RUT y clave. |
| `GET /v1/logins/{sid}` | `avia-bank-sync/avia/api/main.py` L211 `login_status` | Estado del ingreso en curso, con captura de pantalla si espera al usuario. |
| `POST /v1/logins/{sid}/input` | `avia-bank-sync/avia/api/main.py` L217 `login_input` | Reenvía al portal la acción del usuario (Mi Pass, código, CAPTCHA). |
| `GET /v1/accounts` | `avia-bank-sync/avia/api/main.py` L223 `accounts` | Cuentas para «Enlazar cuenta» en Actual; la primera vez lanza la extracción y espera hasta ~50 s. |
| `POST /v1/accounts/{bank_account_id}/link` | `avia-bank-sync/avia/api/main.py` L244 `link` | Vincula una cuenta bancaria de AVIA con una cuenta de Actual. |
| `POST /v1/actual-accounts/{actual_account_id}/unlink` | `avia-bank-sync/avia/api/main.py` L250 `unlink` | Quita la vinculación de una cuenta de Actual. |
| `POST /v1/transactions` | `avia-bank-sync/avia/api/main.py` L256 `transactions` | Movimientos de una cuenta en el formato de bank sync de Actual. |
| `POST /v1/accounts/{bank_account_id}/actual-balance` | `avia-bank-sync/avia/api/main.py` L262 `actual_balance` | Registra el saldo de Actual y devuelve la diferencia con el banco. |
| `GET /v1/reconciliation` | `avia-bank-sync/avia/api/main.py` L268 `reconciliation` | Último saldo banco vs Actual por cuenta. |
| `POST /v1/sync` | `avia-bank-sync/avia/api/main.py` L274 `sync` | Lanza una sincronización en segundo plano (manual o al abrir Actual). |
| `GET /v1/runs` | `avia-bank-sync/avia/api/main.py` L289 `runs` | Historial de ejecuciones de sincronización. |
| `GET /v1/events` | `avia-bank-sync/avia/api/main.py` L295 `events` | Bitácora de eventos (info/warning/error). |
| `GET /v1/review` | `avia-bank-sync/avia/api/main.py` L301 `review` | Movimientos marcados para revisión manual. |
| `GET /panel` | `avia-bank-sync/avia/api/main.py` L309 `admin_panel` | Panel técnico HTML (solo por loopback del servidor). |

## Servicio AVIA (`avia-bank-sync/avia`)

### `avia-bank-sync/avia/api/main.py`
API HTTP de AVIA Bank Sync. Consumida por el sync-server de Actual (app-avia).
- **clase `State`** · L31 — Estado global del proceso: el servicio y el scheduler diario.
- `build_service(settings)` · L40 — Arma AviaService con su motor de sincronización y la caja de cifrado.
- `async lifespan(app)` · L47 — Arranque/cierre: logs, migraciones, pool, recuperar ejecuciones cortadas y scheduler.
- `require_token(authorization)` · L70 — Exige `Authorization: Bearer <AVIA_API_TOKEN>` (comparación en tiempo constante).
- `async service_error_handler(_req, exc)` · L79 — Convierte ServiceError al formato de error que entiende Actual.
- `async in_progress_handler(_req, exc)` · L88 — Responde 409 SYNC_IN_PROGRESS si ya hay una sincronización corriendo.
- `health()` · L96 **[GET /health]** — Vida del proceso (sin tocar la base).
- `ready()` · L102 **[GET /ready]** — Listo para servir: la base responde e indica si el scheduler corre.
- **clase `ConnectionIn`**(BaseModel) · L113 — Cuerpo para crear una conexión sin login por portal (sandbox, Mercado Pago).
- **clase `ReauthIn`**(BaseModel) · L120 — Parámetros opcionales para reautorizar una conexión.
- **clase `TransactionsIn`**(BaseModel) · L125 — Pedido de movimientos desde Actual: cuenta AVIA, fecha inicial y cuenta de Actual.
- **clase `LinkIn`**(BaseModel) · L132 — Cuenta de Actual a la que se vincula una cuenta bancaria.
- **clase `SyncIn`**(BaseModel) · L137 — Pedido de sincronización (manual o al abrir Actual), opcionalmente solo si los datos están viejos.
- **clase `LoginIn`**(BaseModel) · L144 — Inicio de login por portal: banco, RUT, clave y, si es reingreso, la conexión.
- **clase `LoginInputIn`**(BaseModel) · L153 — Acción del usuario sobre la vista en vivo: clic, texto, tecla, scroll o cancelar.
- **clase `BalanceIn`**(BaseModel) · L163 — Saldo conciliado que informa Actual (entero ×100).
- `status()` · L169 **[GET /v1/status]** — Estado general: conexiones, última sincronización, próxima y pendientes de revisión.
- `institutions()` · L175 **[GET /v1/institutions]** — Bancos que ofrece AVIA, si están disponibles y qué campos pide su Set up.
- `connections()` · L181 **[GET /v1/connections]** — Lista de conexiones con su estado.
- `create_connection(body)` · L187 **[POST /v1/connections]** — Crea una conexión sin login por portal (los bancos con portal usan /v1/logins).
- `delete_connection(cid)` · L193 **[DELETE /v1/connections/{cid}]** — Elimina una conexión y borra su credencial cifrada.
- `reauthorize(cid, body)` · L199 **[POST /v1/connections/{cid}/reauthorize]** — Renueva la autorización de una conexión que el banco dejó de aceptar.
- `login_start(body)` · L205 **[POST /v1/logins]** — Abre el portal del banco en Chromium y empieza el ingreso con RUT y clave.
- `login_status(sid, screenshot)` · L211 **[GET /v1/logins/{sid}]** — Estado del ingreso en curso, con captura de pantalla si espera al usuario.
- `login_input(sid, body)` · L217 **[POST /v1/logins/{sid}/input]** — Reenvía al portal la acción del usuario (Mi Pass, código, CAPTCHA).
- `accounts()` · L223 **[GET /v1/accounts]** — Cuentas para «Enlazar cuenta» en Actual; la primera vez lanza la extracción y espera hasta ~50 s.
- `link(bank_account_id, body)` · L244 **[POST /v1/accounts/{bank_account_id}/link]** — Vincula una cuenta bancaria de AVIA con una cuenta de Actual.
- `unlink(actual_account_id)` · L250 **[POST /v1/actual-accounts/{actual_account_id}/unlink]** — Quita la vinculación de una cuenta de Actual.
- `transactions(body)` · L256 **[POST /v1/transactions]** — Movimientos de una cuenta en el formato de bank sync de Actual.
- `actual_balance(bank_account_id, body)` · L262 **[POST /v1/accounts/{bank_account_id}/actual-balance]** — Registra el saldo de Actual y devuelve la diferencia con el banco.
- `reconciliation()` · L268 **[GET /v1/reconciliation]** — Último saldo banco vs Actual por cuenta.
- `sync(body)` · L274 **[POST /v1/sync]** — Lanza una sincronización en segundo plano (manual o al abrir Actual).
- `runs(limit)` · L289 **[GET /v1/runs]** — Historial de ejecuciones de sincronización.
- `events(limit, level)` · L295 **[GET /v1/events]** — Bitácora de eventos (info/warning/error).
- `review()` · L301 **[GET /v1/review]** — Movimientos marcados para revisión manual.
- `admin_panel()` · L309 **[GET /panel]** — Panel técnico HTML (solo por loopback del servidor).

### `avia-bank-sync/avia/api/panel.py`
Panel técnico mínimo de diagnóstico. No contiene datos; los pide al API con el token.

### `avia-bank-sync/avia/config.py`
Configuración por variables de entorno. Sin valores secretos por defecto.
- `_env(name, default, required)` · L10 — Lee una variable de entorno; si es obligatoria y falta, falla con su nombre.
- `_read_secret(name)` · L18 — Admite NAME o NAME_FILE (Docker secrets).
- **clase `Settings`** · L28 — Configuración del servicio leída del entorno (base, token, llaves, horario, conectores).
- `_require(value, name)` · L47 — Falla si falta un valor obligatorio (o su variante _FILE).
- `get_settings()` · L55 — Construye Settings validando token (≥32), llaves Fernet y valores numéricos.

### `avia-bank-sync/avia/connectors/__init__.py`
Registro de conectores.
- `get_connector_class(key)` · L22 — Clase del conector por su clave de REGISTRY (p. ej. 'banco_chile').

### `avia-bank-sync/avia/connectors/bancochile.py`
Banco de Chile (Mi Banco Chile personas): lectura de cuentas, saldos y movimientos.
- `clp(v)` · L28 — '12.345' | '-12.345' | 12345 | 12345.0 → Decimal (CLP no usa decimales).
- `to_date(v)` · L43 — Convierte las fechas del portal (epoch ms/s, ISO o dd/mm/aaaa) a date.
- `_h(*parts)` · L60 — Hash corto estable para armar IDs de movimientos sin ID propio.
- **clase `BancoChilePortal`**(PortalConnector) · L65 — Conector Banco de Chile: entra al portal y lee cuentas, tarjetas, saldos y movimientos por su API REST interna.
  - `__init__(credentials)` · L72 — Guarda credenciales; los datos se cargan una vez por sincronización.
  - `authenticate()` · L79 — No valida aquí: la sesión se prueba al abrir el portal en get_accounts.
  - `_load(since)` · L84 — Abre el portal una sola vez y carga productos, saldos y movimientos (90 días por defecto).
  - `_account_body(p, rut, nombre)` · L128 — Cuerpo JSON que el portal exige para identificar una cuenta corriente.
  - `_checking(c, rec, rut, nombre, since)` · L134 — Lee la cartola paginada de una cuenta corriente y arma sus movimientos.
  - `_card_bodies(it, nombre)` · L183 — Variantes del cuerpo JSON de tarjeta (código de marca y nombre) a probar en orden.
  - `_try(c, url, bodies)` · L202 — Prueba cada cuerpo hasta que el portal acepte uno; devuelve respuesta y cuerpo usado.
  - `_card(c, rec, nombre, since)` · L214 — Lee saldo, movimientos no facturados y facturados de una tarjeta de crédito.
  - `get_accounts()` · L250 — Cuentas y tarjetas del titular.
  - `get_balances(accounts)` · L254 — Saldos de las cuentas pedidas (deuda de tarjeta en negativo).
  - `get_transactions(account, since)` · L259 — Movimientos de una cuenta desde `since`; si su lectura falló, lanza BankError.

### `avia-bank-sync/avia/connectors/base.py`
Contrato común de conectores bancarios.
- **clase `Capability`**(str, enum.Enum) · L18 — Qué sabe entregar un conector (cuentas, saldos, pendientes, tarjetas, cuotas…).
- **clase `AuthorizationRequired`**(Exception) · L35 — El banco exige que el titular vuelva a autorizar el acceso.
- **clase `ConnectorUnavailable`**(Exception) · L39 — No existe hoy un mecanismo autorizado y gratuito para este banco.
  - `__init__(bank_id, reason, doc)` · L42 — Guarda banco, motivo y documento que explica el bloqueo.
- **clase `BankError`**(Exception) · L50 — Error transitorio o de negocio reportado por el banco.
- **clase `BankAccount`** · L55 — Cuenta o tarjeta tal como la entrega el banco.
- **clase `Balance`** · L65 — Saldo contable y disponible de una cuenta en una fecha.
- **clase `BankTransaction`** · L75 — Movimiento bancario normalizado (pendiente o contabilizado), con cuotas y moneda original.
- **clase `BankConnector`**(ABC) · L97 — Interfaz común de todos los conectores de banco.
  - `__init__(credentials)` · L105 — Recibe las credenciales ya descifradas.
  - `availability()` · L110 — Si el banco se puede usar hoy y, si no, por qué.
  - `authenticate()` · L115 — Valida la autorización. Devuelve credenciales actualizadas (p. ej. tokens renovados).
  - `get_accounts()` · L119 — Lista de cuentas del titular.
  - `get_balances(accounts)` · L123 — Saldos de las cuentas pedidas.
  - `get_transactions(account, since)` · L127 — Movimientos de una cuenta desde una fecha.
  - `refresh_authorization()` · L130 — Renueva la autorización; por defecto no se puede y pide reautorizar.

### `avia-bank-sync/avia/connectors/mercadopago.py`
Mercado Pago (cuenta personal) por la API oficial de reportes.
- `_dec(v)` · L41 — Convierte montos con coma o punto decimal a Decimal.
- `_d(v)` · L56 — Fecha ISO (con o sin hora) a date.
- `parse_release_csv(text)` · L61 — Devuelve (movimientos, último saldo informado por el reporte).
- **clase `MercadoPagoConnector`**(BankConnector) · L95 — Conector Mercado Pago por Access Token: saldo y movimientos vía reportes de liberación.
  - `__init__(credentials)` · L108 — Guarda credenciales y el último saldo leído.
  - `_token()` · L114 — Token guardado cifrado o, la primera vez, AVIA_MP_ACCESS_TOKEN del .env.
  - `_client()` · L120 — Cliente HTTP con el token; sin token pide configurarlo.
  - `_check(r)` · L130 — Traduce 401/403 a reautorización y otros errores HTTP a BankError.
  - `authenticate()` · L138 — Valida el token con /users/me y exige cuenta chilena (MLC).
  - `get_accounts()` · L148 — Una sola cuenta vista «Mercado Pago».
  - `get_balances(accounts)` · L154 — Saldo total y disponible de la cuenta.
  - `_ensure_config(c)` · L170 — Crea la configuración del reporte de liberación si no existe.
  - `_fetch_range(c, begin, end)` · L182 — Pide un reporte de un rango, espera a que esté listo y devuelve el CSV.
  - `get_transactions(account, since)` · L198 — Movimientos desde `since` (máx. 2 años), pedidos en tramos de 60 días.

### `avia-bank-sync/avia/connectors/portal.py`
Conectores por portal (usuario + clave del titular, login asistido).
- **clase `ExtractionPending`**(Exception) · L17 — El login funciona, pero la lectura de datos de este portal aún no está implementada.
- **clase `PortalConnector`**(BankConnector) · L21 — Base de bancos con login por portal (RUT + clave); sin lectura propia marca «extracción pendiente».
  - `authenticate()` · L30 — La sesión se comprueba al extraer, no aquí.
  - `_pending()` · L35 — Lanza ExtractionPending: login listo, lectura aún no implementada.
  - `get_accounts()` · L39 — Pendiente hasta implementar la lectura de este portal.
  - `get_balances(accounts)` · L43 — Pendiente hasta implementar la lectura de este portal.
  - `get_transactions(account, since)` · L47 — Pendiente hasta implementar la lectura de este portal.
- **clase `ItauPortal`**(PortalConnector) · L52 — Itaú: bloqueado, su portal rechaza ingresos automatizados (Error 15).
  - `availability()` · L58 — Siempre no disponible, con el motivo.
- **clase `BancoEstadoPortal`**(PortalConnector) · L64 — Login listo (RUT + clave). La lectura de datos se implementa tras el reconocimiento (`python -m avia.recon banco-estado`) con una sesión iniciada por el titular.

### `avia-bank-sync/avia/connectors/ripley.py`
Banco Ripley (web.bancoripley.cl): cuentas, saldos y movimientos.
- **clase `RipleyPortal`**(PortalConnector) · L51 — Conector Banco Ripley: entra al portal y captura las respuestas JSON de cuentas y tarjetas.
  - `__init__(credentials)` · L58 — Guarda credenciales; los datos se cargan una vez por sincronización.
  - `authenticate()` · L65 — La sesión se prueba al abrir el portal.
  - `_cap(page, pred_js)` · L71 — Respuestas JSON capturadas en la página que cumplen el filtro JS.
  - `_wait_cap(page, pred_js, timeout_s)` · L75 — Espera hasta `timeout_s` a que aparezca una respuesta capturada que cumpla el filtro.
  - `_click_menu(page, label)` · L85 — Hace clic en un ítem del menú del portal por su texto.
  - `_load(since)` · L98 — Abre el portal una vez y carga productos, saldos y movimientos.
  - `_read_deposits(page, data)` · L156 — Depósitos a plazo: una cuenta «Depósitos a plazo» con el total al vencimiento en CLP.
  - `_read_checking(page, rec, since)` · L187 — Lee los movimientos de la cuenta corriente.
  - `_read_card(page, rec, since)` · L214 — Lee saldo y movimientos (no facturados y facturados) de la tarjeta.
  - `get_accounts()` · L270 — Cuentas y tarjetas del titular.
  - `get_balances(accounts)` · L274 — Saldos de las cuentas pedidas.
  - `get_transactions(account, since)` · L279 — Movimientos desde `since`; si su lectura falló, lanza BankError.

### `avia-bank-sync/avia/connectors/sandbox.py`
Banco ficticio determinista para pruebas de punta a punta.
- `_h(*parts)` · L49 — Hash entero estable para generar datos ficticios deterministas.
- `_santiago_today()` · L54 — Fecha de hoy en Santiago.
- **clase `SandboxConnector`**(BankConnector) · L59 — Banco ficticio determinista para pruebas: cuenta corriente y tarjeta con pendientes, reversas y pagos.
  - `authenticate()` · L84 — Simula expiración (90 días) y fallas según `fail_mode`.
  - `refresh_authorization()` · L96 — Renueva el token ficticio y quita la falla simulada.
  - `get_accounts()` · L103 — Cuenta corriente y tarjeta ficticias.
  - `_events(until)` · L107 — Genera todos los eventos de negocio desde ANCHOR hasta `until` (incluido).
  - `_is_reversed(ev)` · L152 — ~1 de cada 25 compras cotidianas es una retención que se anula.
  - `get_transactions(account, since)` · L157 — Movimientos ficticios desde `since` (pendientes que luego se contabilizan).
  - `_booked_balance(account, as_of)` · L188 — Saldo contable a una fecha: apertura + movimientos ya contabilizados.
  - `get_balances(accounts)` · L197 — Saldo contable y disponible (descontando pendientes).
  - `opening_balance(account)` · L214 — Saldo de apertura de la cuenta ficticia.

### `avia-bank-sync/avia/crypto.py`
Cifrado de credenciales/tokens con Fernet (AES-128-CBC + HMAC-SHA256).
- **clase `SecretBox`** · L15 — Cifra credenciales con MultiFernet; la primera llave es la activa.
  - `__init__(keys)` · L17 — Carga las llaves (la primera cifra, todas descifran).
  - `key_id(key)` · L26 — Identificador corto de una llave (sin revelarla).
  - `encrypt(payload)` · L30 — Cifra un dict como JSON.
  - `decrypt(token)` · L34 — Descifra a dict; ante llave incorrecta falla sin mostrar el dato.
  - `rotate(token)` · L41 — Re-cifra un dato con la llave activa.

### `avia-bank-sync/avia/db.py`
Acceso a PostgreSQL: pool, migraciones y locks consultivos.
- `init_pool(dsn, min_size, max_size)` · L27 — Crea el pool de conexiones (filas como dict, sin autocommit).
- `close_pool()` · L41 — Cierra el pool.
- `pool()` · L49 — Pool activo; falla si no se inicializó.
- `tx()` · L57 — Transacción atómica: commit al salir, rollback ante excepción.
- `migrate(dsn)` · L64 — Aplica migraciones pendientes en orden, bajo lock, cada una atómica.
- `sync_lock()` · L89 — Intenta tomar el lock de sincronización. Cede True si lo obtuvo.
- `sync_lock_held()` · L107 — Si algún proceso tiene tomado el lock de sincronización.

### `avia-bank-sync/avia/engine/actual_format.py`
Traducción del modelo AVIA al contrato BankSyncResponse de Actual Budget 26.11.0.
- `money_str(v)` · L24 — Monto con 2 decimales como texto.
- `to_actual_integer(v)` · L29 — Monto a entero ×100 (formato interno de Actual).
- `build_notes(t)` · L34 — Notas para Actual: cuota n/m, moneda original y contraparte.
- `to_actual_transaction(t, transfer)` · L47 — Un movimiento de AVIA al formato de bank sync de Actual (y transferencia si es pago de tarjeta).
- `build_response(txns, transfer_map, balance, currency)` · L67 — Respuesta completa para Actual: contabilizados, pendientes y saldos.

### `avia-bank-sync/avia/engine/repo.py`
Operaciones SQL del motor. Todas reciben una conexión dentro de una transacción.
- `event(conn, level, event_type, message, run_id, connection_id, bank_account_id, data)` · L16 — Registra un evento en la bitácora sync_events.
- `lineage_id(bank_id, account_external_id, external_id)` · L26 — ID estable de un movimiento en Actual: avia:<banco>:<cuenta>:<id banco>.
- `upsert_bank_account(conn, connection_id, acct)` · L31 — Crea o actualiza una cuenta bancaria y devuelve su id.
- `find_by_identifier(conn, bank_account_id, scheme, value)` · L48 — Busca un movimiento por uno de sus identificadores (bank_id, referencia…).
- `add_identifier(conn, transaction_id, bank_account_id, scheme, value)` · L57 — Agrega un identificador a un movimiento (sin duplicar).
- `insert_transaction(conn, bank_account_id, lineage, t, run_id, needs_review, review_reason)` · L66 — Inserta un movimiento nuevo con su linaje y marca de revisión.
- `apply_update(conn, existing, t, run_id)` · L90 — Actualiza los campos que cambiaron; nunca baja un contabilizado a pendiente.
- `promote_pending(conn, pending, t, run_id)` · L107 — Un pendiente pasa a contabilizado: misma fila, mismo lineage_id => Actual actualiza, no duplica.
- `_norm(v)` · L122 — Normaliza Decimal para comparar sin falsos cambios.
- `_desc_key(s)` · L129 — Clave corta de descripción (10 alfanuméricos en mayúscula) para emparejar pendiente↔contabilizado.
- `conservative_pending_match(conn, bank_account_id, t)` · L134 — Busca el pendiente que corresponde a un contabilizado sin referencia bancaria.
- `stale_pendings(conn, bank_account_id, since, seen_external_ids)` · L157 — Pendientes desde `since` que el banco ya no informa (posibles reversas).
- `get_cursor(conn, bank_account_id)` · L171 — Última fecha contabilizada confirmada de una cuenta.
- `set_cursor(conn, bank_account_id, last_booked, run_id)` · L178 — Avanza el cursor de la cuenta (nunca retrocede).
- `upsert_balance(conn, bank_account_id, snapshot_date, booked, available, currency)` · L191 — Guarda el saldo del día y recalcula la diferencia con Actual.

### `avia-bank-sync/avia/engine/sync.py`
Motor de sincronización, independiente de cada banco.
- **clase `SyncInProgress`**(Exception) · L31 — Ya hay otra sincronización tomando el lock.
- `_validate(t, currency)` · L36 — Revisa que un movimiento sea válido; devuelve el motivo si no lo es.
- **clase `SyncEngine`** · L53 — Motor de sincronización: por cada conexión lee el banco y guarda sin duplicar.
  - `__init__(settings, box, today)` · L55 — Recibe configuración, caja de cifrado y un reloj opcional (pruebas).
  - `today()` · L61 — Fecha de hoy en la zona configurada (o la del reloj de pruebas).
  - `run(trigger, connection_ids)` · L70 — Ejecuta una sincronización completa bajo lock y devuelve estado y estadísticas.
  - `_connections(ids)` · L102 — Conexiones activas a sincronizar (todas o las pedidas).
  - `build_connector(conn_row)` · L113 — Instancia el conector de una conexión con sus credenciales descifradas.
  - `store_credentials(conn, connection_id, creds)` · L124 — Guarda (cifradas) las credenciales de una conexión.
  - `_set_connection_status(connection_id, status, error, success)` · L135 — Actualiza estado y último error; con éxito marca last_success_at.
  - `_sync_connection(run_id, conn_row, stats)` · L147 — Sincroniza una conexión: autentica, lee cuentas y saldos y sincroniza cada cuenta.
  - `_auth_required(run_id, cid, reason, stats)` · L199 — Marca la conexión como «requiere reautorización» y lo deja pendiente.
  - `_connection_error(run_id, cid, kind, reason, stats)` · L209 — Marca la conexión con error y lo registra.
  - `_sync_account(run_id, conn_row, connector, acct, balance, stats)` · L216 — Sincroniza una cuenta de forma atómica: movimientos, reversas, cursor y saldo.
- `recover_interrupted_runs()` · L294 — Al arrancar: runs en 'running' sin lock vivo quedaron interrumpidos.

### `avia-bank-sync/avia/engine/transfers.py`
Emparejamiento de pagos de tarjeta (salida en cuenta corriente <-> abono en tarjeta).
- `pair_card_payments(conn, run_id)` · L13 — Empareja pagos de tarjeta (salida en cuenta ↔ abono en tarjeta) como transferencia.

### `avia-bank-sync/avia/logging_setup.py`
Logs JSON estructurados. Nunca registrar credenciales ni detalle financiero completo.
- `_redact(value)` · L15 — Oculta valores de claves sensibles (password, token, rut…) en los logs.
- **clase `JsonFormatter`**(logging.Formatter) · L24 — Formato de log JSON de una línea.
  - `format(record)` · L26 — Arma el JSON con hora, nivel, mensaje y extras redactados.
- `setup_logging(level)` · L42 — Configura logs JSON a stdout y baja el ruido de uvicorn.access.

### `avia-bank-sync/avia/portal/banks.py`
Configuración de login de cada portal bancario.
- **clase `PortalConfig`** · L15 — Cómo entrar al portal de un banco: URL, selectores, formato de RUT y señales de éxito.
  - `is_success(url)` · L34 — La URL indica sesión iniciada (y no es la de login).
  - `is_login(url)` · L38 — La URL es una página de login.
- `host_of(url)` · L102 — Dominio de una URL.

### `avia-bank-sync/avia/portal/client.py`
Cliente de portal: reutiliza la sesión guardada y llama a las APIs del propio portal.
- **clase `PortalClient`** · L34 — Navegador con la sesión guardada para llamar la API interna del portal (reentra si venció).
  - `__init__(portal, credentials, api_marker, init_script)` · L36 — Prepara portal, credenciales, sesión guardada y marcador de URLs de la API.
  - `__enter__()` · L48 — Abre Chromium, reutiliza la sesión o vuelve a entrar con RUT y clave.
  - `_where()` · L83 — Dónde quedó la página (dominio + ruta) para mensajes de error.
  - `_session_ok()` · L92 — Si la sesión guardada sigue válida.
  - `_login()` · L103 — Ingreso automático con RUT y clave guardados (como lo haría el titular).
  - `__exit__(*exc)` · L130 — Cierra navegador y Playwright sin propagar errores.
  - `_on_request(req)` · L138 — Copia los encabezados que usa el portal en sus llamadas a la API.
  - `call(method, url, body)` · L146 — Llama la API del portal desde la página; 401/403 pide reautorizar.

### `avia-bank-sync/avia/portal/manager.py`
Registro en memoria de las sesiones de login activas (un solo proceso).
- **clase `LoginManager`** · L16 — Administra las sesiones de ingreso en curso (una por banco a la vez).
  - `__init__(portals, login_url_override)` · L18 — Portales disponibles (reales o de prueba) y registro de sesiones.
  - `_gc()` · L25 — Borra sesiones terminadas hace rato.
  - `start(bank_id, rut, password, on_success, **kw)` · L31 — Inicia un ingreso; cancela otro activo del mismo banco y rechaza si hay demasiados en curso.
  - `get(sid)` · L49 — Sesión de ingreso por id.

### `avia-bank-sync/avia/portal/rut.py`
RUT chileno: limpieza, validación (módulo 11) y formatos.
- `clean(rut)` · L8 — RUT solo con dígitos y K mayúscula.
- `check_digit(body)` · L13 — Dígito verificador (módulo 11).
- `is_valid(rut)` · L23 — Si el RUT tiene dígito verificador correcto.
- `fmt(rut, style)` · L31 — dotted: 12.345.678-9 · dash: 12345678-9 · plain: 123456789
- `mask(rut)` · L42 — RUT enmascarado para mostrar (**.***.123-4).

### `avia-bank-sync/avia/portal/session.py`
Sesión de login asistido a un portal bancario.
- `browser_settings()` · L55 — Opciones de Chromium desde el entorno (headless y ruta).
- **clase `LoginResult`** · L63 — Resultado de un ingreso: cookies/almacenamiento y URL final.
- **clase `LoginSession`** · L70 — Un ingreso a un portal en su propio hilo, con vista en vivo para el segundo factor.
  - `start()` · L94 — Lanza el ingreso en un hilo aparte.
  - `send(cmd)` · L99 — Encola una acción del usuario si el ingreso sigue abierto.
  - `cancel()` · L104 — Cancela el ingreso.
  - `snapshot(include_screenshot)` · L108 — Estado para la UI (RUT enmascarado y captura si espera al usuario).
  - `_set(state, message, **kw)` · L122 — Cambia el estado y lo registra.
  - `_run()` · L132 — Cuerpo del hilo: abre Chromium y conduce el ingreso; cualquier falla queda como estado.
  - `_visible_error(page)` · L159 — Mensaje de error visible del portal (ignora enlaces de «olvidé mi clave»).
  - `_hint(page)` · L172 — Pista según lo que muestra la página (Mi Pass, código, CAPTCHA).
  - `_shoot(page)` · L183 — Toma captura JPEG para la vista en vivo.
  - `_apply(page, cmd)` · L191 — Aplica una acción del usuario a la página; False si cancela.
  - `_drive(page, ctx)` · L213 — Abre el login, escribe RUT y clave, envía y pasa a esperar respuesta.
  - `_wait_user(page, ctx, deadline)` · L249 — Bucle hasta éxito, rechazo, segundo factor o tiempo agotado; al entrar llama on_success.

### `avia-bank-sync/avia/probe.py`
Prueba de extracción con tu sesión real. Salida ENMASCARADA.
- `mag(x)` · L18 — Orden de magnitud con signo (oculta el monto exacto).
- `mask_txt(s)` · L26 — Enmascara letras y dígitos de un texto.
- `main(bank)` · L31 — Lee cuentas, saldos y movimientos con la sesión real e imprime todo enmascarado.

### `avia-bank-sync/avia/recon.py`
Reconocimiento de portales: SOLO LECTURA, datos enmascarados.
- `shape(v, key, depth)` · L33 — Forma de un JSON (claves y tipos) sin los valores.
- `norm_url(u)` · L56 — URL con números e IDs reemplazados y solo los nombres de sus parámetros.
- `mask_label(t)` · L65 — Etiqueta con los dígitos enmascarados.
- `load_state(bank_id, full)` · L70 — Sesión (y, con full, credenciales) guardada de un banco, descifrada desde la base.
- `main(bank_id)` · L85 — Recorre en solo lectura las secciones de consulta del portal y registra la estructura de sus respuestas.

### `avia-bank-sync/avia/scheduler.py`
Scheduler: sincronización diaria en America/Santiago y aviso al runner de Actual.
- **clase `AviaScheduler`** · L16 — Sincronización diaria (6:15) y aviso al runner de Actual.
  - `__init__(settings, service)` · L18 — Prepara APScheduler en la zona horaria configurada.
  - `running()` · L25 — Si el scheduler está corriendo.
  - `start()` · L29 — Programa la sincronización diaria y arranca.
  - `shutdown()` · L40 — Detiene el scheduler.
  - `next_run_time()` · L45 — Próxima ejecución programada.
  - `daily()` · L50 — Sincroniza todo si hay conexiones y luego avisa al runner.
  - `after_sync(result)` · L61 — Tras sincronizar los bancos, pedir al runner que Actual importe (vía su propio bank sync).
  - `_notify(result)` · L74 — Si la sincronización no salió bien, avisa por AVIA_NOTIFY_WEBHOOK_URL (compatible con ntfy).

### `avia-bank-sync/avia/service.py`
Casos de uso consumidos por la API (y por pruebas).
- **clase `ServiceError`**(Exception) · L21 — Error de negocio con estado HTTP, código y mensaje para Actual.
  - `__init__(status, code, message)` · L23 — Guarda estado HTTP, código y mensaje.
- **clase `AviaService`** · L29 — Lógica de la API: bancos, conexiones, logins, cuentas, movimientos y conciliación.
  - `__init__(settings, engine)` · L31 — Recibe configuración y motor; crea el administrador de logins.
  - `institutions()` · L40 — Bancos con disponibilidad, motivo, campos de Set up y método de ingreso.
  - `status()` · L62 — Resumen del sistema: estado global, conexiones, última y próxima sincronización.
  - `is_stale(last_ok)` · L104 — Si la última sincronización exitosa es más vieja que freshness_hours.
  - `create_connection(institution, label, params)` · L111 — Crea una conexión por token o sandbox; los bancos con portal deben usar login_start.
  - `delete_connection(cid)` · L147 — Desconecta conservando el historial: borra el secreto y desactiva sus cuentas.
  - `reauthorize(cid, params)` · L159 — Renueva la autorización con el conector, guarda credenciales y relee; si el banco no lo permite, AUTHORIZATION_FAILED.
  - `login_start(institution, rut, password, label, connection_id)` · L188 — Valida banco, RUT y clave e inicia el ingreso por portal (o reingreso con la clave guardada).
  - `_store_portal_login(institution, bank_name, label, connection_id, rut, password, result)` · L226 — Tras un ingreso exitoso guarda RUT, clave y sesión cifrados y lanza la lectura de cuentas.
  - `login_status(sid, include_screenshot)` · L251 — Estado de un ingreso por id.
  - `login_input(sid, cmd)` · L258 — Reenvía una acción permitida del usuario al ingreso.
  - `accounts()` · L269 — Cuentas activas con su institución, último saldo y vínculo con Actual.
  - `link(bank_account_id, actual_account_id)` · L296 — Vincula cuenta AVIA ↔ cuenta de Actual.
  - `unlink_actual(actual_account_id)` · L301 — Quita los vínculos de una cuenta de Actual; devuelve cuántos.
  - `_ensure_mapping(conn, bank_account_id, actual_account_id)` · L311 — Crea o cambia el vínculo y lo registra en la bitácora.
  - `transactions_for_actual(bank_account_id, start_date, actual_account_id)` · L328 — Movimientos para Actual; si los datos están viejos, sincroniza esa conexión antes.
  - `record_actual_balance(bank_account_id, cleared_balance_integer)` · L376 — Compara el saldo de Actual con el del banco y explica posibles causas de diferencia.
  - `reconciliation()` · L406 — Último saldo por cuenta con su diferencia contra Actual.
  - `start_background_sync(trigger, connection_ids, on_done)` · L419 — Lanza una sincronización en un hilo si no hay otra; False si ya hay una.
  - `runs(limit)` · L438 — Últimas ejecuciones de sincronización.
  - `events(limit, level)` · L443 — Últimos eventos, opcionalmente filtrados por nivel.
  - `review_items()` · L451 — Movimientos que necesitan revisión manual (máx. 200).
- `santiago_now(tz)` · L460 — Hora actual en la zona dada.

## Pruebas del servicio (`avia-bank-sync/tests`)

### `avia-bank-sync/tests/conftest.py`
_(sin docstring de módulo)_
- **clase `Clock`** · L22
  - `__init__(d)` · L23
  - `__call__()` · L26
- `clock(monkeypatch)` · L31
- `fresh_db()` · L38
- `service(fresh_db, clock)` · L49
- `q(sql, *params)` · L58

### `avia-bank-sync/tests/integration/test_api.py`
_(sin docstring de módulo)_
- `client(fresh_db, clock, service)` · L11
- `H()` · L18
- `test_health_is_public_and_v1_requires_token(client)` · L22 — prueba: health is public and v1 requires token
- `test_full_flow_over_http(client)` · L29 — prueba: full flow over http
- `test_portal_bank_requires_login_flow(client)` · L45 — prueba: portal bank requires login flow
- `test_unknown_account_404(client)` · L53 — prueba: unknown account 404

### `avia-bank-sync/tests/integration/test_portal_login.py`
Login asistido contra un portal bancario FALSO servido localmente (Chrome real).
- **clase `FakeBank`**(BaseHTTPRequestHandler) · L37
  - `log_message(*a)` · L41
  - `_html(body, code, headers)` · L44
  - `_redirect(to, cookie)` · L52
  - `do_GET()` · L59
  - `do_POST()` · L68
- `fake_bank()` · L84
- `fake_config(base)` · L91
- `wait(sess, states, timeout)` · L100
- `test_rut()` · L109 — prueba: rut
- `test_login_success_stores_session(fake_bank)` · L116 — prueba: login success stores session
- `test_wrong_password_reports_bank_message(fake_bank)` · L129 — prueba: wrong password reports bank message
- `test_mfa_step_is_completed_by_the_user(fake_bank)` · L138 — prueba: mfa step is completed by the user
- `test_cancel(fake_bank)` · L157 — prueba: cancel
- `test_service_flow_creates_encrypted_connection(fake_bank, service, monkeypatch)` · L166 — prueba: service flow creates encrypted connection
- `test_service_validates_input(service)` · L200 — prueba: service validates input
- `test_unreachable_portal_has_clear_error()` · L216 — prueba: unreachable portal has clear error

### `avia-bank-sync/tests/integration/test_sync_engine.py`
_(sin docstring de módulo)_
- `connect_sandbox(service)` · L16
- `test_initial_sync_imports_accounts_and_movements(service)` · L20 — prueba: initial sync imports accounts and movements
- `test_rerun_is_idempotent(service)` · L31 — prueba: rerun is idempotent
- `test_pending_becomes_booked_without_duplicate(service, clock)` · L40 — prueba: pending becomes booked without duplicate
- `test_reversed_pending_is_flagged(service, clock)` · L60 — prueba: reversed pending is flagged
- `test_card_payment_is_paired_and_exported_as_transfer(service)` · L78 — prueba: card payment is paired and exported as transfer
- `test_export_contract_matches_actual(service)` · L97 — prueba: export contract matches actual
- `test_mapping_is_stable_and_not_duplicated(service)` · L118 — prueba: mapping is stable and not duplicated
- `test_no_concurrent_runs(service)` · L128 — prueba: no concurrent runs
- `test_authorization_required_and_reauthorize(service, clock)` · L151 — prueba: authorization required and reauthorize
- `test_bank_error_keeps_other_data(service)` · L167 — prueba: bank error keeps other data
- `test_restart_recovery_resumes_without_duplicates(service, clock)` · L178 — prueba: restart recovery resumes without duplicates
- `test_crash_mid_account_rolls_back_cursor(service, clock, monkeypatch)` · L189 — prueba: crash mid account rolls back cursor
- `test_validation_rejects_unsafe_amounts(service, monkeypatch)` · L212 — prueba: validation rejects unsafe amounts
- `test_ambiguous_pending_goes_to_review(service, monkeypatch, clock)` · L228 — prueba: ambiguous pending goes to review
- `test_reconciliation_records_difference(service)` · L247 — prueba: reconciliation records difference
- `test_credentials_are_encrypted(service)` · L257 — prueba: credentials are encrypted
- `test_portal_institutions_use_login_flow(service)` · L263 — prueba: portal institutions use login flow
- `test_delete_connection_removes_secret_keeps_history(service)` · L279 — prueba: delete connection removes secret keeps history
- `test_sync_without_movements(service, monkeypatch)` · L288 — prueba: sync without movements

### `avia-bank-sync/tests/unit/test_mapa_codigo.py`
El mapa del código (MAPA-CODIGO.md) debe estar al día y cada función del servicio con su línea de contexto.
- `test_mapa_al_dia()` · L10 — prueba: mapa al dia
- `test_toda_funcion_del_servicio_tiene_docstring()` · L15 — prueba: toda funcion del servicio tiene docstring

### `avia-bank-sync/tests/unit/test_mercadopago.py`
_(sin docstring de módulo)_
- `test_parse_signs_dedupe_and_balance()` · L19 — prueba: parse signs dedupe and balance
- `test_parse_identical_rows_get_distinct_ids_and_stable_across_runs()` · L27 — prueba: parse identical rows get distinct ids and stable across runs
- `test_parse_semicolon_and_decimal_comma()` · L36 — prueba: parse semicolon and decimal comma
- `_mock(handler)` · L42
- `test_full_flow(monkeypatch)` · L46 — prueba: full flow
- `test_rejects_other_country_and_bad_token(monkeypatch)` · L94 — prueba: rejects other country and bad token
- `test_token_from_env_is_persisted(monkeypatch)` · L106 — prueba: token from env is persisted

### `avia-bank-sync/tests/unit/test_units.py`
_(sin docstring de módulo)_
- `test_clp_conversion_is_exact()` · L12 — prueba: clp conversion is exact
- `test_key_rotation()` · L20 — prueba: key rotation
- `test_logs_redact_secrets()` · L31 — prueba: logs redact secrets
- `test_sandbox_is_deterministic(monkeypatch)` · L36 — prueba: sandbox is deterministic

## Scripts, SQL, parche de Actual y runner
- `actual-avia-integration/.github/workflows/ci.yml`
- `actual-avia-integration/patches/0001-avia-bank-sync-provider.patch`
- `actual-avia-integration/runner/index.mjs` — AVIA Actual Runner
- `actual-avia-integration/scripts/build-images.sh` — Construye las imágenes de Actual (con AVIA) y del runner.
- `actual-avia-integration/scripts/prepare-source.sh` — Clona Actual en la versión bloqueada y aplica los parches AVIA.
- `actual-avia-integration/scripts/verify.sh` — Pruebas de regresión de la integración sobre la fuente parcheada (sin Docker).
- `actual-avia-integration/tests/e2e.mjs` — Prueba de punta a punta contra un stack real:
- `avia-bank-sync/compose.yaml` — AVIA Bank Sync — proyecto Docker independiente para el Synology NAS.
- `avia-bank-sync/database/migrations/001_initial.sql` — AVIA Bank Sync — esquema inicial.
- `avia-bank-sync/database/migrations/002_banco_estado.sql`
- `avia-bank-sync/database/migrations/003_mercado_pago.sql`
- `avia-bank-sync/scripts/backup.sh` — Respaldo cifrado de PostgreSQL (pg_dump | gzip | AES-256 con openssl).
- `avia-bank-sync/scripts/generate-secrets.sh` — Genera los secretos locales (no se versionan). No sobrescribe archivos existentes.
- `avia-bank-sync/scripts/preparar.sh` — Prepara la carpeta para lanzarla desde Container Manager (Proyecto): crea secretos, .env y carpetas.
- `install.sh` — AVIA Bank Sync + Actual parchado — instalación COMPLETA en el Synology NAS
- `tools/grabador-dom.mjs` — AVIA · grabador de PANTALLAS (DOM enmascarado) — se ejecuta en TU computador, con tu Chrome.
- `tools/grabador-json.mjs` — AVIA · grabador de DATOS DESCIFRADOS (estructura enmascarada) — corre en TU computador.
- `tools/grabador.mjs` — AVIA · grabador de estructura (se ejecuta en TU computador, con tu Chrome).
