-- ============================================================
-- TOYAMAS — Migration 012: Ticket account_email + verify attempts
-- ============================================================
-- Dua perubahan digabung di migration ini karena satu tema (hardening
-- alur tiket kode 6 digit):
--
-- 1. account_email di app_tickets — sebelumnya sempat ditambahkan dengan
--    cara mengedit migration 011 langsung. Itu salah: migration tracking
--    di services/database.py berbasis NAMA FILE (tabel schema_migrations),
--    bukan isi filenya. Karena 011 sudah pernah diterapkan ke database
--    yang sudah berjalan, mengedit isinya TIDAK akan pernah ter-apply ulang
--    — kolom baru harus lewat migration file baru, makanya ditaruh di sini.
--
-- 2. ticket_verify_attempts — tabel BARU untuk rate limiting yang benar.
--    Sebelumnya count_verify_attempts() menghitung baris di
--    ticket_verify_sessions, padahal tabel itu CUMA keisi kalau kode yang
--    dimasukkan BENAR (create_verify_session dipanggil setelah tiket
--    ketemu). Akibatnya percobaan kode yang SALAH tidak pernah tercatat
--    sama sekali, jadi brute-force tebak kode 6 karakter tidak pernah kena
--    limit. Tabel ini mencatat SETIAP percobaan verify-code (berhasil
--    maupun gagal) supaya bisa di-rate-limit berdasarkan jumlah percobaan
--    GAGAL per machine_id dalam window waktu tertentu.

-- Urutan statement SENGAJA: CREATE TABLE (idempotent, aman diulang) taruh
-- SEBELUM ALTER TABLE (satu-satunya statement yang bisa gagal kalau kolom
-- sudah pernah ada di sebagian database). executescript() menjalankan
-- statement satu-satu dan berhenti di statement pertama yang error — kalau
-- ALTER TABLE ditaruh duluan dan gagal, CREATE TABLE di bawahnya jadi tidak
-- pernah kejalan padahal migration ini sudah kadung ditandai selesai oleh
-- exception handler di init_database(). Menaruh CREATE TABLE duluan
-- memastikan tabel baru tetap terbuat di kedua skenario.

CREATE TABLE IF NOT EXISTS ticket_verify_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id      TEXT NOT NULL,
    code_attempted  TEXT,                            -- disimpan buat audit, bukan rahasia
    success         INTEGER NOT NULL DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verify_attempts_machine_time
    ON ticket_verify_attempts(machine_id, created_at);

ALTER TABLE app_tickets ADD COLUMN account_email TEXT NOT NULL DEFAULT '';
