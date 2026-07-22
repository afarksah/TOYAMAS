-- ============================================================
-- TOYAMAS — Migration 003: Hourly Sales Aggregation
-- ============================================================

-- Tabel agregasi penjualan per jam (untuk grafik cepat)
CREATE TABLE IF NOT EXISTS sales_hourly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL,
    date DATE NOT NULL,
    hour INTEGER NOT NULL,           -- 0-23
    volume_liters REAL DEFAULT 0,
    transactions INTEGER DEFAULT 0,
    revenue INTEGER DEFAULT 0,        -- IDR
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(machine_id, date, hour)
);

-- Index untuk query cepat
CREATE INDEX idx_sales_hourly_machine_date ON sales_hourly(machine_id, date);
CREATE INDEX idx_sales_hourly_date ON sales_hourly(date);

-- ============================================================
-- TRIGGER: Auto-update sales_hourly saat transaksi selesai
-- ============================================================

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
        DATE(NEW.dispense_completed_at),
        CAST(strftime('%H', NEW.dispense_completed_at) AS INTEGER),
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
-- TRIGGER: Juga update saat transaksi baru dengan status COMPLETE
-- ============================================================

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
        DATE(NEW.dispense_completed_at),
        CAST(strftime('%H', NEW.dispense_completed_at) AS INTEGER),
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