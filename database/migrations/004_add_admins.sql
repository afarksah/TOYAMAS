-- ============================================================
-- TOYAMAS — Migration 004: Admin Users (username + password bcrypt)
-- ============================================================

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT,               -- bcrypt hash, bisa NULL sampai diisi
    role TEXT DEFAULT 'admin',        -- admin | super_admin
    is_active INTEGER DEFAULT 1,
    last_login DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Insert default admin (username: admin, password belum diset)
INSERT OR IGNORE INTO admins (username, name, role)
VALUES ('admin', 'Administrator', 'super_admin');

-- Index untuk performa
CREATE INDEX idx_admins_username ON admins(username);
CREATE INDEX idx_admins_role ON admins(role);