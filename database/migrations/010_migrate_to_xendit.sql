-- 010_migrate_to_xendit.sql
-- Migrasi payment gateway: Midtrans → Xendit
--
-- Kolom midtrans_trx_id / midtrans_raw_json di-rename jadi nama generik
-- gateway_trx_id / gateway_raw_json, supaya kalau suatu saat ganti PSP lagi
-- (mis. dari Xendit ke yang lain) tidak perlu migrasi kolom lagi.
--
-- gateway_provider dipakai untuk menandai baris lama (dibuat saat masih
-- pakai Midtrans) vs baris baru (Xendit), berguna untuk keperluan audit/
-- rekonsiliasi kalau ada transaksi lama yang belum lunas saat migrasi.

ALTER TABLE transactions RENAME COLUMN midtrans_trx_id   TO gateway_trx_id;
ALTER TABLE transactions RENAME COLUMN midtrans_raw_json TO gateway_raw_json;

ALTER TABLE transactions ADD COLUMN gateway_provider TEXT NOT NULL DEFAULT 'xendit';

-- Tandai transaksi lama (yang sudah py gateway_trx_id terisi sebelum migrasi
-- ini dijalankan) sebagai berasal dari Midtrans, supaya histori tetap akurat.
UPDATE transactions
SET gateway_provider = 'midtrans'
WHERE gateway_trx_id IS NOT NULL;

-- Xendit qr_id (id payment_request, format "pr-xxxxxxxx") dipakai untuk
-- GET /payment_requests/{id} saat polling status — beda dari order_id kita
-- (yang dipakai sebagai reference_id di sisi Xendit).
ALTER TABLE transactions ADD COLUMN xendit_payment_request_id TEXT;

CREATE INDEX IF NOT EXISTS idx_transactions_xendit_pr_id
    ON transactions(xendit_payment_request_id);
