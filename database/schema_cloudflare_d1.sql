-- ============================================================
-- schema_cloudflare_d1.sql
-- Schema database cloud Cloudflare D1
-- Deploy: wrangler d1 execute toyamas-db --file=schema_cloudflare_d1.sql
-- ============================================================

-- ──────────────────────────────────────────
-- users: akun pengguna aplikasi Toyamas
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,        -- UUID v4
    name            TEXT NOT NULL,
    phone           TEXT UNIQUE NOT NULL,    -- +62xxxxxxxxxx
    email           TEXT,
    password_hash   TEXT NOT NULL,           -- bcrypt
    balance         INTEGER NOT NULL DEFAULT 0,  -- IDR (untuk topup saldo)
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT,
    fcm_token       TEXT                     -- untuk push notification
);

-- ──────────────────────────────────────────
-- tickets: tiket refill air yang diterbitkan
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tickets (
    ticket_code     TEXT PRIMARY KEY,        -- "TYM-ABCD-1234"
    user_id         TEXT NOT NULL,
    machine_id      TEXT,                    -- NULL = berlaku di semua mesin
    volume_liter    REAL NOT NULL,
    issued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    expired_at      TEXT NOT NULL,           -- batas berlaku
    status          TEXT NOT NULL DEFAULT 'UNUSED'
                        CHECK(status IN ('UNUSED','USED','EXPIRED','CANCELLED')),
    used_at         TEXT,
    used_machine_id TEXT,
    order_ref       TEXT,                    -- referensi pembelian tiket
    notes           TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_tickets_user    ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status  ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_exp     ON tickets(expired_at);

-- ──────────────────────────────────────────
-- transactions_sync: mirror dari SQLite lokal
-- Disinkronkan dari kiosk ke cloud secara berkala
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions_sync (
    order_id            TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    source              TEXT NOT NULL,
    ticket_code         TEXT,
    volume_requested    REAL,
    volume_actual       REAL,
    amount              INTEGER,
    payment_method      TEXT,
    payment_status      TEXT,
    dispense_status     TEXT,
    created_at          TEXT,
    synced_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ──────────────────────────────────────────
-- machines_registry: registry semua mesin aktif
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS machines_registry (
    machine_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    location        TEXT,
    owner_id        TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    registered_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync       TEXT
);
