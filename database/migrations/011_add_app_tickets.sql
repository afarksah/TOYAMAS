-- ============================================================
-- TOYAMAS — Migration 011: App Tickets & Verify Sessions
-- ============================================================
-- Tabel ini mensimulasikan database aplikasi HP (tiket yang sudah
-- dibeli user). Nanti jika aplikasi sudah terintegrasi dengan
-- Cloudflare D1, tabel ini bisa diganti dengan query ke Worker,
-- tapi endpoint API-nya tetap sama.

CREATE TABLE IF NOT EXISTS app_tickets (
    ticket_code     TEXT PRIMARY KEY,               -- TKT-01KTWDXX2K...MPH6GV
    account_id      TEXT NOT NULL,                  -- ID akun (misal UUID atau email)
    account_name    TEXT NOT NULL,                  -- Nama lengkap pemilik
    account_email   TEXT NOT NULL,                  -- Email (untuk verifikasi/referensi)
    transaction_id  TEXT NOT NULL,                  -- ID transaksi pembelian di app
    volume_ml       INTEGER NOT NULL,               -- Volume dalam ml (misal 750)
    amount          INTEGER NOT NULL,               -- Harga dalam Rupiah
    status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','USED','EXPIRED')),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME NOT NULL,              -- Batas berlaku tiket
    used_at         DATETIME
);

CREATE INDEX idx_app_tickets_status ON app_tickets(status);
CREATE INDEX idx_app_tickets_expires ON app_tickets(expires_at);
CREATE INDEX idx_app_tickets_account ON app_tickets(account_id);

-- ============================================================
-- Tabel verify_session — token sementara yang di-QR-kan ke kiosk
-- ============================================================

CREATE TABLE IF NOT EXISTS ticket_verify_sessions (
    verify_token    TEXT PRIMARY KEY,               -- vts_8f3a1c9b...
    ticket_code     TEXT NOT NULL REFERENCES app_tickets(ticket_code),
    machine_id      TEXT NOT NULL,                  -- Mesin tujuan
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME NOT NULL,              -- 3 menit
    used            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_verify_sessions_token ON ticket_verify_sessions(verify_token);
CREATE INDEX idx_verify_sessions_machine ON ticket_verify_sessions(machine_id);