-- ============================================================
-- TOYAMAS — Migration 005: Fix timezone pada trigger sales_hourly
-- ============================================================
-- Masalah: trigger di 003_add_hourly_sales.sql menghitung DATE()/jam dari
-- `dispense_completed_at` (disimpan UTC) TANPA konversi ke waktu lokal.
-- Akibatnya bucket tanggal & jam di tabel sales_hourly meleset sampai 8 jam
-- dari waktu lokal sebenarnya (WITA = UTC+8), sehingga grafik "Per Jam" dan
-- laporan harian salah menampilkan jam/tanggal transaksi.
--
-- CATATAN: offset '+8 hours' di bawah ini di-hardcode (trigger SQL tidak
-- bisa membaca config Python). Kalau TIMEZONE_OFFSET_HOURS di
-- config/settings.py diubah dari 8, migration baru serupa perlu dibuat
-- lagi untuk menyamakan offset trigger ini.

DROP TRIGGER IF EXISTS update_sales_hourly;
DROP TRIGGER IF EXISTS insert_sales_hourly;

CREATE TRIGGER update_sales_hourly
AFTER UPDATE OF dispense_status ON transactions
WHEN NEW.dispense_status = 'COMPLETE'
    AND OLD.dispense_status != 'COMPLETE'
    AND NEW.payment_status = 'PAID'
BEGIN
    INSERT INTO sales_hourly (
        machine_id,
        date,
        hour,
        volume_liters,
        transactions,
        revenue
    )
    VALUES (
        NEW.machine_id,
        DATE(NEW.dispense_completed_at, '+8 hours'),
        CAST(strftime('%H', NEW.dispense_completed_at, '+8 hours') AS INTEGER),
        COALESCE(NEW.volume_actual, NEW.volume_requested, 0),
        1,
        COALESCE(NEW.amount, 0)
    )
    ON CONFLICT(machine_id, date, hour) DO UPDATE SET
        volume_liters = volume_liters + COALESCE(NEW.volume_actual, NEW.volume_requested, 0),
        transactions = transactions + 1,
        revenue = revenue + COALESCE(NEW.amount, 0),
        updated_at = CURRENT_TIMESTAMP;
END;

CREATE TRIGGER insert_sales_hourly
AFTER INSERT ON transactions
WHEN NEW.dispense_status = 'COMPLETE'
    AND NEW.payment_status = 'PAID'
BEGIN
    INSERT INTO sales_hourly (
        machine_id,
        date,
        hour,
        volume_liters,
        transactions,
        revenue
    )
    VALUES (
        NEW.machine_id,
        DATE(NEW.dispense_completed_at, '+8 hours'),
        CAST(strftime('%H', NEW.dispense_completed_at, '+8 hours') AS INTEGER),
        COALESCE(NEW.volume_actual, NEW.volume_requested, 0),
        1,
        COALESCE(NEW.amount, 0)
    )
    ON CONFLICT(machine_id, date, hour) DO UPDATE SET
        volume_liters = volume_liters + COALESCE(NEW.volume_actual, NEW.volume_requested, 0),
        transactions = transactions + 1,
        revenue = revenue + COALESCE(NEW.amount, 0),
        updated_at = CURRENT_TIMESTAMP;
END;

-- ============================================================
-- Perbaiki data yang sudah kadung salah bucket (dibuat oleh trigger lama)
-- Dibangun ulang dari tabel transactions (sumber kebenaran), memakai
-- offset waktu lokal yang benar.
-- ============================================================

DELETE FROM sales_hourly;

INSERT INTO sales_hourly (machine_id, date, hour, volume_liters, transactions, revenue)
SELECT
    machine_id,
    DATE(dispense_completed_at, '+8 hours')                              AS date,
    CAST(strftime('%H', dispense_completed_at, '+8 hours') AS INTEGER)   AS hour,
    SUM(COALESCE(volume_actual, volume_requested, 0))                    AS volume_liters,
    COUNT(*)                                                             AS transactions,
    SUM(COALESCE(amount, 0))                                             AS revenue
FROM transactions
WHERE payment_status = 'PAID'
  AND dispense_status = 'COMPLETE'
  AND dispense_completed_at IS NOT NULL
GROUP BY machine_id,
         DATE(dispense_completed_at, '+8 hours'),
         CAST(strftime('%H', dispense_completed_at, '+8 hours') AS INTEGER);
