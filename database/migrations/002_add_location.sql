-- ============================================================
-- TOYAMAS — Migration 002: Add Location Columns
-- ============================================================

-- Tambah kolom lokasi ke tabel machines
ALTER TABLE machines ADD COLUMN latitude REAL;
ALTER TABLE machines ADD COLUMN longitude REAL;
ALTER TABLE machines ADD COLUMN address TEXT;
ALTER TABLE machines ADD COLUMN location_source TEXT DEFAULT 'database';

-- Tambah kolom ip_address untuk deteksi lokasi otomatis
ALTER TABLE machines ADD COLUMN ip_address TEXT;

-- Tambah kolom last_location_update
ALTER TABLE machines ADD COLUMN last_location_update DATETIME;

-- Index untuk query cepat
CREATE INDEX idx_machines_location ON machines(latitude, longitude);

-- Update data existing dengan default (jika ada)
UPDATE machines SET 
    latitude = -5.147665,
    longitude = 119.432731,
    address = 'Jl. Merpati No.12, Makassar',
    location_source = 'database'
WHERE latitude IS NULL;