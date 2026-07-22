-- ============================================================
-- TOYAMAS — Migration 007: Soft Delete Mesin
-- ============================================================
-- Latar belakang: menghapus mesin secara permanen (hard delete)
-- akan melanggar FOREIGN KEY dari transactions/sensor_logs/alarms/
-- kiosk_sessions/machine_config/machine_state_cache -> machines.
-- Karena riwayat transaksi (termasuk Midtrans) harus tetap utuh
-- untuk laporan, mesin yang "dihapus" dari menu Location cukup
-- ditandai non-aktif (is_active = 0), bukan dihapus fisik.
--
-- Efeknya:
--   * Mesin hilang dari /api/iot/machines, dropdown, peta lokasi,
--     dan semua daftar mesin aktif.
--   * Baris di tabel machines TETAP ADA -> laporan/histori
--     transaksi lama tetap tampil apa adanya tanpa perlu tautan
--     balik ke detail mesin.
--   * machine_id yang sudah non-aktif dianggap "terkunci" (tidak
--     dipakai ulang untuk mesin baru) supaya data lama tidak
--     tercampur dengan mesin fisik pengganti.

ALTER TABLE machines ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;
ALTER TABLE machines ADD COLUMN deleted_at DATETIME;

CREATE INDEX IF NOT EXISTS idx_machines_is_active ON machines(is_active);
