-- ============================================================
-- 001_init.sql
-- Inisialisasi database SQLite lokal Toyamas
-- Jalankan: sqlite3 toyamas_local.db < 001_init.sql
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ──────────────────────────────────────────
-- machines: identitas & konfigurasi mesin
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS machines (
    machine_id          TEXT PRIMARY KEY,
    name                TEXT NOT NULL DEFAULT 'Toyamas Dispenser',
    location            TEXT,
    mode                TEXT NOT NULL DEFAULT 'RO'
                            CHECK(mode IN ('RO', 'MANUAL')),
    price_per_liter     INTEGER NOT NULL DEFAULT 500,
    admin_pin_hash      TEXT NOT NULL,
    firmware_ver        TEXT,
    last_seen           DATETIME,
    online              INTEGER NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Seed data mesin default
INSERT OR IGNORE INTO machines (machine_id, name, admin_pin_hash)
VALUES (
    'TYM-001',
    'Toyamas Kiosk Utama',
    '03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4'
    -- SHA256("1234") — WAJIB diganti saat produksi
);

-- ──────────────────────────────────────────
-- machine_config: key-value settings per mesin
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS machine_config (
    machine_id  TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (machine_id, key),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

-- Default config values
INSERT OR IGNORE INTO machine_config (machine_id, key, value) VALUES
    ('TYM-001', 'slide_duration_ms',  '5000'),
    ('TYM-001', 'standby_timeout_sec','30'),
    ('TYM-001', 'signage_enabled',    '1'),
    ('TYM-001', 'ticker_text',        'TOYAMAS · Air RO Bersih · 0812-3456-7890 · Harga Rp 500/Liter · Buka 24 Jam');

-- ──────────────────────────────────────────
-- transactions: semua sesi transaksi
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id                TEXT UNIQUE NOT NULL,
    machine_id              TEXT NOT NULL,
    session_id              TEXT,
    source                  TEXT NOT NULL
                                CHECK(source IN ('PAYMENT', 'TICKET')),
    ticket_code             TEXT,
    volume_requested        REAL NOT NULL,
    volume_actual           REAL,
    amount                  INTEGER,
    payment_method          TEXT,
    payment_status          TEXT NOT NULL DEFAULT 'PENDING'
                                CHECK(payment_status IN ('PENDING','PAID','FAILED','EXPIRED')),
    gateway_provider        TEXT NOT NULL DEFAULT 'xendit',
    gateway_trx_id          TEXT,
    gateway_raw_json        TEXT,
    xendit_payment_request_id TEXT,
    paid_at                 DATETIME,
    dispense_status         TEXT NOT NULL DEFAULT 'WAITING'
                                CHECK(dispense_status IN ('WAITING','DISPENSING','COMPLETE','ABORTED')),
    dispense_started_at     DATETIME,
    dispense_completed_at   DATETIME,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_to_cloud         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_machine    ON transactions(machine_id);
CREATE INDEX IF NOT EXISTS idx_transactions_status     ON transactions(payment_status);
CREATE INDEX IF NOT EXISTS idx_transactions_created    ON transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_transactions_synced     ON transactions(synced_to_cloud);

-- ──────────────────────────────────────────
-- sensor_logs: riwayat status sensor (1 baris per 10 detik)
-- Auto-cleanup: data > 7 hari dihapus via cron
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sensor_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id          TEXT NOT NULL,
    logged_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state               TEXT,
    mode                TEXT,
    g1_level_pct        REAL,
    g2_level_pct        REAL,
    g1_level_cm         REAL,
    g2_level_cm         REAL,
    g1_status           TEXT,
    g2_status           TEXT,
    active_galon        INTEGER,
    pump_dc             INTEGER DEFAULT 0,
    uv_lamp             INTEGER DEFAULT 0,
    solenoid_ro1        INTEGER DEFAULT 0,
    solenoid_ro2        INTEGER DEFAULT 0,
    solenoid_pump1      INTEGER DEFAULT 0,
    solenoid_pump2      INTEGER DEFAULT 0,
    flow_liters         REAL DEFAULT 0,
    wifi_rssi           INTEGER,
    uptime_sec          INTEGER,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE INDEX IF NOT EXISTS idx_sensor_machine  ON sensor_logs(machine_id);
CREATE INDEX IF NOT EXISTS idx_sensor_logged   ON sensor_logs(logged_at);

-- ──────────────────────────────────────────
-- alarms: log semua alarm dari ESP32
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alarms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id      TEXT NOT NULL,
    alarm_type      TEXT NOT NULL,
    severity        TEXT NOT NULL
                        CHECK(severity IN ('INFO','WARNING','ERROR')),
    detail_json     TEXT,
    triggered_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME,
    notified        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE INDEX IF NOT EXISTS idx_alarms_machine   ON alarms(machine_id);
CREATE INDEX IF NOT EXISTS idx_alarms_type      ON alarms(alarm_type);
CREATE INDEX IF NOT EXISTS idx_alarms_severity  ON alarms(severity);

-- ──────────────────────────────────────────
-- kiosk_sessions: QR session token untuk metode tiket
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kiosk_sessions (
    session_token   TEXT PRIMARY KEY,
    machine_id      TEXT NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0,
    used_at         DATETIME,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_machine  ON kiosk_sessions(machine_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires  ON kiosk_sessions(expires_at);

-- ──────────────────────────────────────────
-- machine_state_cache: cache status terakhir ESP32
-- Satu baris per machine_id, di-UPDATE setiap MQTT masuk
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS machine_state_cache (
    machine_id          TEXT PRIMARY KEY,
    state               TEXT DEFAULT 'UNKNOWN',
    mode                TEXT DEFAULT 'RO',
    g1_level_pct        REAL DEFAULT 0,
    g2_level_pct        REAL DEFAULT 0,
    g1_level_cm         REAL DEFAULT 0,
    g2_level_cm         REAL DEFAULT 0,
    g1_status           TEXT DEFAULT 'UNKNOWN',
    g2_status           TEXT DEFAULT 'UNKNOWN',
    active_galon        INTEGER DEFAULT 1,
    total_available_liters REAL DEFAULT 0,
    online              INTEGER DEFAULT 0,
    last_seen           DATETIME,
    raw_json            TEXT,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

INSERT OR IGNORE INTO machine_state_cache (machine_id)
VALUES ('TYM-001');
