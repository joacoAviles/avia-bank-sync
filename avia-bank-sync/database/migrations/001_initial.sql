-- AVIA Bank Sync — esquema inicial.
-- PostgreSQL es la fuente de verdad del proceso de sincronización.
-- Montos: NUMERIC exacto (nunca float). La moneda original siempre se conserva.

CREATE TABLE banks (
    id           TEXT PRIMARY KEY,                 -- 'banco-chile', 'itau', 'ripley', 'sandbox'
    name         TEXT NOT NULL,
    country      CHAR(2) NOT NULL DEFAULT 'CL',
    connector    TEXT NOT NULL,                    -- clave en el registro de conectores
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE connections (
    id           UUID PRIMARY KEY,
    bank_id      TEXT NOT NULL REFERENCES banks(id),
    label        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'connected'
                 CHECK (status IN ('connected','authorization_required','error','disconnected')),
    last_error   TEXT,
    last_success_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX connections_active_idx ON connections (status) WHERE deleted_at IS NULL;

-- Secretos/tokens SIEMPRE cifrados (Fernet). Nunca texto plano.
CREATE TABLE credentials (
    connection_id UUID PRIMARY KEY REFERENCES connections(id) ON DELETE CASCADE,
    ciphertext    BYTEA NOT NULL,
    key_id        TEXT NOT NULL,                   -- permite rotación de llaves
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at    TIMESTAMPTZ
);

CREATE TABLE bank_accounts (
    id            UUID PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    external_id   TEXT NOT NULL,
    name          TEXT NOT NULL,
    account_type  TEXT NOT NULL
                  CHECK (account_type IN ('checking','vista','savings','credit_card','line_of_credit','other')),
    currency      CHAR(3) NOT NULL,
    masked_number TEXT,
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (connection_id, external_id)
);

-- Cuentas de Actual vistas por AVIA (id = UUID interno de la cuenta en Actual).
CREATE TABLE actual_accounts (
    id            TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Relación estable cuenta bancaria <-> cuenta Actual (1 a 1).
CREATE TABLE account_mappings (
    bank_account_id   UUID PRIMARY KEY REFERENCES bank_accounts(id) ON DELETE CASCADE,
    actual_account_id TEXT NOT NULL REFERENCES actual_accounts(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX account_mappings_actual_idx ON account_mappings (actual_account_id);

CREATE TABLE sync_runs (
    id           UUID PRIMARY KEY,
    trigger      TEXT NOT NULL CHECK (trigger IN ('schedule','manual','actual_open','actual_pull','startup_recovery')),
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','succeeded','partial','failed','interrupted','skipped')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    stats        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error        TEXT
);
CREATE INDEX sync_runs_started_idx ON sync_runs (started_at DESC);

CREATE TABLE transactions (
    id              UUID PRIMARY KEY,
    bank_account_id UUID NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    -- ID estable entregado a Actual (imported_id). Se mantiene cuando un
    -- movimiento pasa de pendiente a contabilizado => Actual lo actualiza, no lo duplica.
    lineage_id      TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL
                    CHECK (status IN ('pending','booked','reversed','deleted')),
    booked_date     DATE,
    value_date      DATE NOT NULL,
    amount          NUMERIC(20,4) NOT NULL,        -- signo: negativo = salida de dinero
    currency        CHAR(3) NOT NULL,
    description     TEXT NOT NULL,
    counterparty    TEXT,
    kind            TEXT NOT NULL DEFAULT 'other'
                    CHECK (kind IN ('purchase','installment','payment','card_payment','interest','fee',
                                    'refund','cash_advance','transfer_in','transfer_out','deposit','withdrawal','other')),
    installment_number INT,
    installment_total  INT,
    original_amount    NUMERIC(20,4),
    original_currency  CHAR(3),
    fx_rate            NUMERIC(20,8),
    fx_date            DATE,
    transfer_peer_id   UUID REFERENCES transactions(id),
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    review_reason   TEXT,
    first_run_id    UUID REFERENCES sync_runs(id),
    last_run_id     UUID REFERENCES sync_runs(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'booked' OR booked_date IS NOT NULL),
    CHECK ((fx_rate IS NULL) = (fx_date IS NULL))
);
CREATE INDEX transactions_account_date_idx ON transactions (bank_account_id, value_date DESC);
CREATE INDEX transactions_pending_idx ON transactions (bank_account_id) WHERE status = 'pending';
CREATE INDEX transactions_review_idx ON transactions (needs_review) WHERE needs_review;

-- Identificadores bancarios por movimiento. Un movimiento puede tener varios
-- (id del pendiente + id del contabilizado + referencia).
CREATE TABLE transaction_identifiers (
    id              BIGSERIAL PRIMARY KEY,
    transaction_id  UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    bank_account_id UUID NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    scheme          TEXT NOT NULL CHECK (scheme IN ('bank_id','bank_reference','fingerprint')),
    value           TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bank_account_id, scheme, value)
);
CREATE INDEX transaction_identifiers_tx_idx ON transaction_identifiers (transaction_id);

-- Último cursor CONFIRMADO por cuenta. Solo avanza dentro de la misma
-- transacción SQL que persiste los movimientos => recuperación segura.
CREATE TABLE sync_cursors (
    bank_account_id  UUID PRIMARY KEY REFERENCES bank_accounts(id) ON DELETE CASCADE,
    last_booked_date DATE,
    confirmed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id           UUID REFERENCES sync_runs(id)
);

CREATE TABLE balance_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    bank_account_id  UUID NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
    snapshot_date    DATE NOT NULL,
    booked           NUMERIC(20,4),                -- saldo contable bancario
    available        NUMERIC(20,4),                -- saldo disponible (informativo)
    actual_calculated NUMERIC(20,4),               -- saldo calculado por Actual
    difference       NUMERIC(20,4),                -- booked - actual_calculated
    currency         CHAR(3) NOT NULL,
    captured_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bank_account_id, snapshot_date)
);

CREATE TABLE sync_events (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID REFERENCES sync_runs(id),
    connection_id   UUID REFERENCES connections(id) ON DELETE SET NULL,
    bank_account_id UUID REFERENCES bank_accounts(id) ON DELETE SET NULL,
    level           TEXT NOT NULL CHECK (level IN ('info','warning','error')),
    event_type      TEXT NOT NULL,
    message         TEXT NOT NULL,
    data            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sync_events_created_idx ON sync_events (created_at DESC);
CREATE INDEX sync_events_run_idx ON sync_events (run_id);

CREATE TABLE pending_authorizations (
    id            UUID PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    reason        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX pending_authorizations_open_idx
    ON pending_authorizations (connection_id) WHERE resolved_at IS NULL;

INSERT INTO banks (id, name, connector) VALUES
    ('sandbox',      'AVIA Sandbox (datos ficticios)', 'sandbox'),
    ('banco-chile',  'Banco de Chile',                 'banco_chile'),
    ('itau',         'Itaú Chile',                     'itau'),
    ('ripley',       'Banco Ripley',                   'ripley');
