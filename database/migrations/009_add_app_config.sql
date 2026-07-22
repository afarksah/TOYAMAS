-- Migration 009: Konfigurasi global aplikasi (default price, default mode, dll)
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Seed default values
INSERT OR IGNORE INTO app_config (key, value) VALUES ('default_price', '500');
INSERT OR IGNORE INTO app_config (key, value) VALUES ('default_mode', 'RO');