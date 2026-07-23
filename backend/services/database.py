"""
services/database.py
SQLite connection manager dan semua fungsi query database lokal.
"""
import sqlite3
import json
import logging
import secrets as secrets_lib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config.settings import (
    DATABASE_PATH, MACHINE_ID, TZ_SQL_MODIFIER, TIMEZONE_OFFSET_HOURS,
    MACHINE_OFFLINE_TIMEOUT_SEC, MACHINE_SECRET
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# Connection Manager
# ─────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_cursor():
    """Context manager: auto commit/rollback + close."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        conn.close()


def init_database():
    """
    Jalankan SEMUA migration SQL secara berurutan dan inisialisasi database.

    CATATAN (perbaikan):
    Versi sebelumnya HANYA mengeksekusi 001_init.sql, sehingga tabel-tabel
    dari migration 002/003/004 (termasuk tabel `admins` yang dipakai login
    admin IoT dashboard) TIDAK PERNAH dibuat di database runtime.

    Sekarang semua file .sql di folder database/ (001_init.sql) dan
    database/migrations/ (002, 003, 004, dst.) dijalankan berurutan
    berdasarkan nama file. Tabel `schema_migrations` dipakai untuk mencatat
    migration mana yang sudah pernah diterapkan, supaya:
      1. Server bisa restart berkali-kali tanpa mencoba re-apply migration
         yang sama (penting karena beberapa migration pakai `ALTER TABLE
         ADD COLUMN` yang TIDAK idempotent — akan error jika dijalankan
         dua kali).
      2. Migration baru yang ditambahkan di kemudian hari otomatis
         terdeteksi dan diterapkan saat startup berikutnya.
    """
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    base_dir = Path(__file__).parent.parent.parent
    database_dir = base_dir / "database"

    # Kumpulkan file migration: 001_init.sql (root) + semua *.sql di migrations/
    migration_files = []
    root_init = database_dir / "001_init.sql"
    if root_init.exists():
        migration_files.append(root_init)

    migrations_subdir = database_dir / "migrations"
    if migrations_subdir.is_dir():
        migration_files += sorted(migrations_subdir.glob("*.sql"))

    if not migration_files:
        logger.warning(f"Tidak ada file migration ditemukan di {database_dir}")
        return

    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename    TEXT PRIMARY KEY,
                applied_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        already_applied = {
            row[0] for row in conn.execute(
                "SELECT filename FROM schema_migrations"
            ).fetchall()
        }

        for path in migration_files:
            if path.name in already_applied:
                logger.debug(f"Migration dilewati (sudah diterapkan): {path.name}")
                continue

            try:
                with open(path, "r") as f:
                    conn.executescript(f.read())
                conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (?)",
                    (path.name,)
                )
                conn.commit()
                logger.info(f"Migration diterapkan: {path.name}")

            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                # Migration non-idempotent (mis. ALTER TABLE ADD COLUMN) yang
                # pernah dijalankan manual sebelum fix ini ada — tandai selesai
                # dan lanjut, jangan crash seluruh startup karenanya.
                #
                # "no such column" ditambahkan khusus untuk kasus migration
                # 010_migrate_to_xendit.sql: file itu isinya RENAME COLUMN
                # midtrans_trx_id -> gateway_trx_id, untuk database LAMA yang
                # dibuat sebelum 001_init.sql diupdate. Tapi kalau database-nya
                # baru dibuat dari 001_init.sql versi terbaru, kolom sudah
                # bernama gateway_trx_id sejak awal — jadi RENAME dari kolom
                # yang tidak ada itu bukan error sungguhan, cuma tanda migrasi
                # itu sudah "ketinggalan zaman" untuk skema fresh. Aman dilewati.
                if "duplicate column" in msg or "already exists" in msg or "no such column" in msg:
                    logger.warning(
                        f"Migration {path.name} tampaknya sudah pernah "
                        f"diterapkan sebelumnya ({e}). Menandai sebagai selesai."
                    )
                    conn.rollback()
                    conn.execute(
                        "INSERT OR IGNORE INTO schema_migrations (filename) VALUES (?)",
                        (path.name,)
                    )
                    conn.commit()
                else:
                    conn.rollback()
                    logger.error(f"Migration gagal: {path.name} -> {e}")
                    raise

        logger.info(f"Database initialized ({len(migration_files)} migration file diperiksa)")

    except Exception as e:
        logger.error(f"Database init error: {e}")
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────
# Machine
# ─────────────────────────────────────────

def get_machine_secret(machine_id: str) -> str:
    """
    Ambil HMAC secret KHUSUS mesin ini (kolom `machines.secret`, migration 006).

    PERBAIKAN (keamanan): sebelumnya SEMUA mesin memakai satu MACHINE_SECRET
    global yang sama (dari .env) untuk menurunkan key HMAC
    (key = f"{machine_id}:{MACHINE_SECRET}"). Karena machine_id itu publik
    (ada di topic MQTT), siapa pun yang berhasil membongkar firmware SATU
    unit ESP32 saja bisa menghitung HMAC valid untuk MENGAKU jadi mesin lain
    — termasuk memalsukan command STOP/DISPENSE.

    Sekarang tiap mesin BISA punya secret sendiri (di-generate otomatis saat
    registrasi lewat create_machine() / POST /api/iot/machines). Fallback
    ke MACHINE_SECRET global kalau mesin belum punya secret sendiri (mis.
    TYM-001 yang didaftarkan sebelum fitur ini ada, atau memang belum
    sempat di-upgrade firmware-nya) — supaya mesin lama yang sudah online
    tidak tiba-tiba putus komunikasi.
    """
    with db_cursor() as cur:
        cur.execute("SELECT secret FROM machines WHERE machine_id = ?", (machine_id,))
        row = cur.fetchone()
    if row and row["secret"]:
        return row["secret"]
    return MACHINE_SECRET


def get_machine(machine_id: str = MACHINE_ID) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM machines WHERE machine_id = ?", (machine_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_machines(include_inactive: bool = False) -> list[dict]:
    """
    Daftar mesin terdaftar (tabel `machines`), terlepas online/offline.

    Default hanya mesin aktif (`is_active = 1`) — mesin yang sudah
    di-soft-delete lewat menu Location tidak akan muncul di sini.
    Set `include_inactive=True` kalau butuh semua baris, mis. untuk
    laporan/histori transaksi lama.
    """
    with db_cursor() as cur:
        if include_inactive:
            cur.execute("SELECT * FROM machines ORDER BY machine_id")
        else:
            cur.execute("SELECT * FROM machines WHERE is_active = 1 ORDER BY machine_id")
        return [dict(r) for r in cur.fetchall()]


def create_machine(machine_id: str, name: str, admin_pin_hash: str,
                    location: str = None, price_per_liter: int = 500,
                    mode: str = "RO", secret: str = None) -> dict:
    """
    Daftarkan mesin baru ke armada (mis. TYM-002, TYM-003, ...).

    Menambahkan row ke `machines` DAN seed row di `machine_state_cache`
    (dengan status default UNKNOWN/offline sampai ESP32-nya pertama kali
    kirim status MQTT) supaya langsung muncul di dashboard IoT meski
    mesinnya belum online. Juga menyalin default machine_config yang sama
    seperti seed TYM-001 di 001_init.sql.

    `secret`: HMAC secret KHUSUS mesin ini (kolom `machines.secret`,
    lihat get_machine_secret()). Kalau tidak diisi, di-generate otomatis
    pakai `secrets.token_hex(16)` (32 karakter hex, acak kriptografis) —
    ini yang direkomendasikan; jangan pakai secret yang sama untuk banyak
    mesin. Nilai ini HARUS disalin persis ke `MACHINE_SECRET` di firmware
    unit tersebut sebelum di-flash.
    """
    # Ambil default dari app_config
    default_price = int(get_app_config('default_price', '500'))
    default_mode = get_app_config('default_mode', 'RO')
    
    # Override jika parameter diberikan, fallback ke default global
    if price_per_liter is None:
        price_per_liter = default_price
    if mode is None:
        mode = default_mode

    if get_machine(machine_id):
        raise ValueError(f"machine_id '{machine_id}' sudah terdaftar")

    if not secret:
        secret = secrets_lib.token_hex(16)

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO machines
                (machine_id, name, location, mode, price_per_liter, admin_pin_hash, secret)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (machine_id, name, location, mode, price_per_liter, admin_pin_hash, secret))

        cur.execute("""
            INSERT OR IGNORE INTO machine_state_cache (machine_id)
            VALUES (?)
        """, (machine_id,))

        defaults = {
            "slide_duration_ms":   "5000",
            "standby_timeout_sec": "30",
            "signage_enabled":     "1",
            "ticker_text":         "TOYAMAS · Air RO Bersih · Buka 24 Jam",
        }
        for key, value in defaults.items():
            cur.execute("""
                INSERT OR IGNORE INTO machine_config (machine_id, key, value)
                VALUES (?, ?, ?)
            """, (machine_id, key, value))

    logger.info(f"Mesin baru terdaftar: {machine_id} ({name})")
    return get_machine(machine_id)


def get_machine_config(machine_id: str = MACHINE_ID) -> dict:
    """Return semua config sebagai dict {key: value}."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT key, value FROM machine_config WHERE machine_id = ?",
            (machine_id,)
        )
        return {row["key"]: row["value"] for row in cur.fetchall()}


def set_machine_config(machine_id: str, key: str, value: str):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO machine_config (machine_id, key, value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(machine_id, key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (machine_id, key, value))


def update_machine_online(machine_id: str, online: bool):
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute("""
            UPDATE machines
            SET online = ?, last_seen = ?
            WHERE machine_id = ?
        """, (1 if online else 0, now, machine_id))


# ─────────────────────────────────────────
# Machine State Cache (dari MQTT)
# ─────────────────────────────────────────

def update_state_cache(machine_id: str, payload: dict):
    """
    Update cache status ESP32 terbaru.
    Dipanggil setiap MQTT status/flow masuk.
    """
    galon = payload.get("galon", {})
    g1 = galon.get("g1_level_pct", 0)
    g2 = galon.get("g2_level_pct", 0)
    total = ((g1 / 100) + (g2 / 100)) * 19.0   # masing-masing max 19L

    # Simpan raw_json LENGKAP termasuk actuators dan system
    raw_json = json.dumps(payload)

    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO machine_state_cache (
                machine_id, state, mode,
                g1_level_pct, g2_level_pct, g1_level_cm, g2_level_cm,
                g1_status, g2_status, active_galon, total_available_liters,
                online, last_seen, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(machine_id) DO UPDATE SET
                state                  = excluded.state,
                mode                   = excluded.mode,
                g1_level_pct           = excluded.g1_level_pct,
                g2_level_pct           = excluded.g2_level_pct,
                g1_level_cm            = excluded.g1_level_cm,
                g2_level_cm            = excluded.g2_level_cm,
                g1_status              = excluded.g1_status,
                g2_status              = excluded.g2_status,
                active_galon           = excluded.active_galon,
                total_available_liters = excluded.total_available_liters,
                online                 = 1,
                last_seen              = CURRENT_TIMESTAMP,
                raw_json               = excluded.raw_json
        """, (
            machine_id,
            payload.get("state", "UNKNOWN"),
            payload.get("mode", "RO"),
            g1, g2,
            galon.get("g1_level_cm", 0),
            galon.get("g2_level_cm", 0),
            galon.get("g1_status", "UNKNOWN"),
            galon.get("g2_status", "UNKNOWN"),
            galon.get("active_galon", 1),
            round(total, 2),
            json.dumps(payload),
        ))


def get_state_cache(machine_id: str = MACHINE_ID) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM machine_state_cache WHERE machine_id = ?",
            (machine_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────
# Transactions
# ─────────────────────────────────────────

def create_transaction(order_id: str, machine_id: str, session_id: str,
                        source: str, volume_requested: float,
                        amount: Optional[int] = None,
                        payment_method: Optional[str] = None,
                        ticket_code: Optional[str] = None) -> dict:
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO transactions (
                order_id, machine_id, session_id, source,
                volume_requested, amount, payment_method, ticket_code,
                payment_status, dispense_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, machine_id, session_id, source,
            volume_requested, amount, payment_method, ticket_code,
            "PENDING" if source == "PAYMENT" else "PAID",
            "WAITING"
        ))
    return get_transaction(order_id)


def get_transaction(order_id: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_payment_status(order_id: str, status: str,
                           gateway_trx_id: Optional[str] = None,
                           gateway_raw: Optional[dict] = None):
    """Update status pembayaran setelah webhook Xendit."""
    paid_at = None
    if status == "PAID":
        paid_at = datetime.now(timezone.utc).isoformat()

    with db_cursor() as cur:
        cur.execute("""
            UPDATE transactions SET
                payment_status   = ?,
                gateway_trx_id   = COALESCE(?, gateway_trx_id),
                gateway_raw_json = COALESCE(?, gateway_raw_json),
                paid_at          = COALESCE(?, paid_at)
            WHERE order_id = ?
        """, (
            status,
            gateway_trx_id,
            json.dumps(gateway_raw) if gateway_raw else None,
            paid_at,
            order_id
        ))


def set_xendit_payment_request_id(order_id: str, payment_request_id: str):
    """Simpan id payment_request Xendit (format 'pr-xxxx') saat transaksi
    dibuat — dipakai belakangan untuk GET /payment_requests/{id} saat
    polling status (beda dari order_id kita yang jadi reference_id)."""
    with db_cursor() as cur:
        cur.execute(
            "UPDATE transactions SET xendit_payment_request_id = ? WHERE order_id = ?",
            (payment_request_id, order_id)
        )


def get_active_transaction_for_machine(machine_id: str) -> Optional[dict]:
    """
    Cari transaksi yang MASIH AKTIF di mesin ini — artinya sudah PAID
    tapi air belum selesai terisi (dispense_status WAITING/DISPENSING).

    Dipakai untuk mencegah /api/payment/create membuat order kedua saat
    galon pelanggan sebelumnya di mesin yang sama belum selesai terisi.
    PENDING (belum bayar) sengaja TIDAK dianggap "aktif" di sini — kalau
    user A generate QR tapi tidak jadi bayar, user B tetap harus bisa
    coba bayar (order lama A nanti expired sendiri lewat cron/QR timer).
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM transactions
            WHERE machine_id = ?
              AND payment_status = 'PAID'
              AND dispense_status IN ('WAITING', 'DISPENSING')
            ORDER BY paid_at DESC
            LIMIT 1
        """, (machine_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_dispense_status(order_id: str, dispense_status: str,
                            volume_actual: Optional[float] = None):
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        if dispense_status == "DISPENSING":
            cur.execute("""
                UPDATE transactions SET
                    dispense_status     = ?,
                    dispense_started_at = ?
                WHERE order_id = ?
            """, (dispense_status, now, order_id))
        elif dispense_status in ("COMPLETE", "ABORTED"):
            cur.execute("""
                UPDATE transactions SET
                    dispense_status       = ?,
                    volume_actual         = COALESCE(?, volume_actual),
                    dispense_completed_at = ?
                WHERE order_id = ?
            """, (dispense_status, volume_actual, now, order_id))
        else:
            cur.execute("""
                UPDATE transactions SET dispense_status = ?
                WHERE order_id = ?
            """, (dispense_status, order_id))


def get_pending_transactions_old(minutes: int = 15) -> list[dict]:
    """Return transaksi PENDING lebih dari N menit (untuk cron check)."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM transactions
            WHERE payment_status = 'PENDING'
              AND source = 'PAYMENT'
              AND created_at < datetime('now', ? )
        """, (f"-{minutes} minutes",))
        return [dict(r) for r in cur.fetchall()]


def mark_unsynced_transactions() -> list[dict]:
    """Return transaksi COMPLETE yang belum disinkronkan ke cloud."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM transactions
            WHERE synced_to_cloud = 0
              AND payment_status IN ('PAID', 'FAILED', 'EXPIRED')
              AND dispense_status IN ('COMPLETE', 'ABORTED', 'WAITING')
        """)
        return [dict(r) for r in cur.fetchall()]


def mark_synced(order_ids: list[str]):
    with db_cursor() as cur:
        placeholders = ",".join("?" * len(order_ids))
        cur.execute(
            f"UPDATE transactions SET synced_to_cloud = 1 WHERE order_id IN ({placeholders})",
            order_ids
        )


# ─────────────────────────────────────────
# Sensor Logs
# ─────────────────────────────────────────

def log_sensor_data(machine_id: str, payload: dict):
    """Simpan snapshot sensor ke log (dipanggil setiap MQTT status masuk)."""
    galon = payload.get("galon", {})
    act   = payload.get("actuators", {})
    sys   = payload.get("system", {})
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO sensor_logs (
                machine_id, state, mode,
                g1_level_pct, g2_level_pct, g1_level_cm, g2_level_cm,
                g1_status, g2_status, active_galon,
                pump_dc, uv_lamp, solenoid_ro1, solenoid_ro2,
                solenoid_pump1, solenoid_pump2,
                wifi_rssi, uptime_sec
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            machine_id,
            payload.get("state"),
            payload.get("mode"),
            galon.get("g1_level_pct"),
            galon.get("g2_level_pct"),
            galon.get("g1_level_cm"),
            galon.get("g2_level_cm"),
            galon.get("g1_status"),
            galon.get("g2_status"),
            galon.get("active_galon"),
            1 if act.get("pump_dc") else 0,
            1 if act.get("uv_lamp") else 0,
            1 if act.get("solenoid_ro1") else 0,
            1 if act.get("solenoid_ro2") else 0,
            1 if act.get("solenoid_pump1") else 0,
            1 if act.get("solenoid_pump2") else 0,
            sys.get("wifi_rssi"),
            sys.get("uptime_sec"),
        ))


def cleanup_old_sensor_logs(days: int = 7):
    """Hapus log sensor lebih dari N hari (cron harian)."""
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM sensor_logs WHERE logged_at < datetime('now', ?)",
            (f"-{days} days",)
        )
        deleted = cur.rowcount
    logger.info(f"Sensor log cleanup: {deleted} rows deleted")


# ─────────────────────────────────────────
# Alarms
# ─────────────────────────────────────────

def log_alarm(machine_id: str, alarm_type: str, severity: str, detail: dict):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO alarms (machine_id, alarm_type, severity, detail_json)
            VALUES (?, ?, ?, ?)
        """, (machine_id, alarm_type, severity, json.dumps(detail)))


# ─────────────────────────────────────────
# Kiosk Sessions
# ─────────────────────────────────────────

def save_kiosk_session(token: str, machine_id: str, expires_at: datetime):
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO kiosk_sessions (session_token, machine_id, expires_at)
            VALUES (?, ?, ?)
        """, (token, machine_id, expires_at.isoformat()))


def mark_session_used(token: str) -> bool:
    """Tandai session sebagai sudah dipakai. Return False jika sudah dipakai."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE kiosk_sessions
            SET used = 1, used_at = CURRENT_TIMESTAMP
            WHERE session_token = ?
              AND used = 0
              AND expires_at > CURRENT_TIMESTAMP
        """, (token,))
        return cur.rowcount > 0


def cleanup_expired_sessions():
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM kiosk_sessions WHERE expires_at < datetime('now', '-1 hour')"
        )


# ─────────────────────────────────────────
# Reports
# ─────────────────────────────────────────

def get_daily_report(machine_id: str = MACHINE_ID, date: str = None) -> dict:
    """Laporan transaksi hari ini untuk panel admin."""
    if not date:
        # Hitung tanggal "hari ini" berdasarkan waktu lokal (TZ_SQL_MODIFIER),
        # bukan tanggal UTC server — supaya konsisten dengan DATE(created_at, ...)
        # di query di bawah.
        date = (datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET_HOURS)).strftime("%Y-%m-%d")

    with db_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_transactions,
                COALESCE(SUM(volume_actual), 0) as volume_liters,
                COALESCE(SUM(CASE WHEN source='PAYMENT' THEN amount ELSE 0 END), 0) as revenue_gross,
                COUNT(CASE WHEN source='PAYMENT' THEN 1 END) as payment_count,
                COUNT(CASE WHEN source='TICKET'  THEN 1 END) as ticket_count
            FROM transactions
            WHERE machine_id = ?
              AND DATE(created_at, ?) = ?
              AND payment_status IN ('PAID')
              AND dispense_status = 'COMPLETE'
        """, (machine_id, TZ_SQL_MODIFIER, date))
        row = cur.fetchone()
        data = dict(row)

    # Net revenue = gross - estimasi fee QRIS (MDR) 0.7%.
    # Ini estimasi generik dari aturan MDR QRIS Bank Indonesia, bukan angka
    # spesifik Xendit — cek dashboard Xendit untuk angka MDR aktual per akun.
    gross = data.get("revenue_gross", 0)
    fee   = round(gross * 0.007)
    data["revenue_net"]  = gross - fee
    data["gateway_fee"]  = fee
    data["date"]         = date
    return data


# ─────────────────────────────────────────
# LOCATION
# ─────────────────────────────────────────

def update_machine_location(machine_id: str, lat: float, lng: float, 
                            address: str = None, source: str = "admin_manual"):
    """Update lokasi mesin di database (selalu input manual dari admin)."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE machines SET
                latitude = COALESCE(?, latitude),
                longitude = COALESCE(?, longitude),
                address = COALESCE(?, address),
                location_source = ?,
                last_location_update = CURRENT_TIMESTAMP
            WHERE machine_id = ?
        """, (lat, lng, address, source, machine_id))


def get_machine_location(machine_id: str) -> Optional[dict]:
    """Ambil lokasi mesin dari database."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT 
                machine_id,
                latitude,
                longitude,
                address,
                location_source,
                last_location_update
            FROM machines 
            WHERE machine_id = ?
        """, (machine_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_machines_locations() -> list[dict]:
    """
    Ambil lokasi semua mesin AKTIF (is_active = 1).

    Sengaja tidak difilter berdasarkan ada/tidaknya koordinat — mesin
    yang baru didaftarkan lewat POST /api/iot/machines akan langsung
    ikut muncul di sini (dengan latitude/longitude/address NULL) supaya
    menu Location bisa menampilkannya sebagai "Belum diatur" sampai
    admin mengisi lokasinya secara manual.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT 
                machine_id,
                name,
                latitude,
                longitude,
                address,
                location_source,
                last_location_update,
                online
            FROM machines 
            WHERE is_active = 1
            ORDER BY machine_id
        """)
        return [dict(r) for r in cur.fetchall()]


def soft_delete_machine(machine_id: str) -> bool:
    """
    Soft-delete mesin: tandai `is_active = 0` + catat `deleted_at`,
    TIDAK menghapus baris/riwayat transaksi fisiknya.

    Dipakai dari tombol "Hapus" di menu Location. Mesin akan langsung
    hilang dari /api/iot/machines, dropdown lokasi, dan peta — tapi
    baris `machines` serta seluruh riwayat transaksi/laporan yang
    menunjuk ke machine_id ini tetap utuh di database.

    machine_id yang sudah non-aktif otomatis "terkunci" (tidak bisa
    dipakai ulang untuk mesin baru) karena create_machine() menolak
    machine_id yang masih ada baris-nya di tabel `machines`, aktif
    ataupun tidak.

    Return False kalau machine_id tidak ditemukan sama sekali.
    """
    with db_cursor() as cur:
        cur.execute("""
            UPDATE machines SET
                is_active = 0,
                deleted_at = CURRENT_TIMESTAMP
            WHERE machine_id = ? AND is_active = 1
        """, (machine_id,))
        return cur.rowcount > 0


# ─────────────────────────────────────────
# TRANSACTIONS — Extended
# ─────────────────────────────────────────

def get_transactions_filtered(
    machine_id: str = None,
    start_date: str = None,
    end_date: str = None,
    status: str = None,
    source: str = None,
    limit: int = 20,
    offset: int = 0
) -> tuple[list[dict], int]:
    """
    Ambil transaksi dengan filter.
    Return: (transactions, total_count)
    """
    conditions = []
    params = []

    if machine_id:
        conditions.append("machine_id = ?")
        params.append(machine_id)

    if start_date:
        conditions.append("DATE(created_at, ?) >= ?")
        params.append(TZ_SQL_MODIFIER)
        params.append(start_date)

    if end_date:
        conditions.append("DATE(created_at, ?) <= ?")
        params.append(TZ_SQL_MODIFIER)
        params.append(end_date)

    if status:
        if status.upper() in ("PAID", "PENDING", "FAILED", "EXPIRED"):
            conditions.append("payment_status = ?")
            params.append(status.upper())
        elif status.upper() in ("COMPLETE", "DISPENSING", "ABORTED", "WAITING"):
            conditions.append("dispense_status = ?")
            params.append(status.upper())

    if source:
        conditions.append("source = ?")
        params.append(source.upper())

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with db_cursor() as cur:
        # Hitung total
        cur.execute(f"""
            SELECT COUNT(*) as total
            FROM transactions
            WHERE {where_clause}
        """, params)
        total = cur.fetchone()["total"]

        # Ambil data
        cur.execute(f"""
            SELECT 
                order_id,
                machine_id,
                session_id,
                source,
                ticket_code,
                volume_requested,
                volume_actual,
                amount,
                payment_method,
                payment_status,
                dispense_status,
                paid_at,
                dispense_started_at,
                dispense_completed_at,
                created_at
            FROM transactions
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset])

        rows = [dict(r) for r in cur.fetchall()]

    return rows, total


def get_sales_summary(machine_id: str = None, period: str = "today") -> dict:
    """
    Ambil ringkasan penjualan.
    period: today | week | month

    CATATAN (timezone): created_at disimpan UTC. TZ_SQL_MODIFIER (default
    '+8 hours' / WITA, lihat config/settings.py) menggeser perhitungan
    tanggal ke waktu lokal supaya batas "hari ini" tidak meleset sampai
    jam 08:00 pagi seperti sebelumnya.
    """
    date_condition = {
        "today": f"DATE(created_at, '{TZ_SQL_MODIFIER}') = DATE('now', '{TZ_SQL_MODIFIER}')",
        "week": f"created_at >= DATETIME('now', '{TZ_SQL_MODIFIER}', '-7 days')",
        "month": f"created_at >= DATETIME('now', '{TZ_SQL_MODIFIER}', '-30 days')",
    }.get(period, f"DATE(created_at, '{TZ_SQL_MODIFIER}') = DATE('now', '{TZ_SQL_MODIFIER}')")

    # PERBAIKAN (SQL injection): machine_id dulu ditempel langsung ke teks
    # SQL lewat f-string ("AND machine_id = '{machine_id}'"), jadi kalau ada
    # karakter quote (') di dalamnya, string itu bisa "kabur" dari literal
    # dan mengubah struktur query (mis. UNION SELECT untuk membaca tabel lain
    # termasuk admins/PIN hash mesin lain). Sekarang machine_filter cuma
    # berisi teks TETAP ("AND machine_id = ?" atau kosong) — nilai asli
    # machine_id dikirim lewat parameter terikat (params), bukan digabung ke
    # teks query. Pola sama seperti yang sudah benar di get_transactions_filtered().
    machine_filter = "AND machine_id = ?" if machine_id else ""
    params = [machine_id] if machine_id else []

    with db_cursor() as cur:
        cur.execute(f"""
            SELECT 
                COUNT(*) as transactions,
                COALESCE(SUM(volume_actual), 0) as volume_liters,
                COALESCE(SUM(amount), 0) as revenue,
                COUNT(CASE WHEN source='PAYMENT' THEN 1 END) as payment_count,
                COUNT(CASE WHEN source='TICKET' THEN 1 END) as ticket_count
            FROM transactions
            WHERE {date_condition}
              AND payment_status = 'PAID'
              AND dispense_status = 'COMPLETE'
              {machine_filter}
        """, params)
        row = cur.fetchone()
        data = dict(row)

    # Tambahkan info period
    data["period"] = period

    # Hitung rata-rata per transaksi
    if data["transactions"] > 0:
        data["avg_volume_per_trx"] = round(data["volume_liters"] / data["transactions"], 2)
        data["avg_revenue_per_trx"] = round(data["revenue"] / data["transactions"], 2)
    else:
        data["avg_volume_per_trx"] = 0
        data["avg_revenue_per_trx"] = 0

    return data


def get_hourly_sales(machine_id: str = None, date: str = None) -> list[dict]:
    """
    Ambil data penjualan per jam untuk grafik.
    Jika date tidak diberikan, pakai hari ini (berdasarkan waktu lokal,
    lihat TZ_SQL_MODIFIER di config/settings.py — tabel sales_hourly sudah
    diisi trigger dengan tanggal/jam yang sudah dikonversi ke waktu lokal).
    """
    if not date:
        date = (datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET_HOURS)).strftime("%Y-%m-%d")

    machine_filter = "AND machine_id = ?" if machine_id else ""
    params = [date] + ([machine_id] if machine_id else [])

    with db_cursor() as cur:
        cur.execute(f"""
            SELECT 
                hour,
                volume_liters,
                transactions,
                revenue
            FROM sales_hourly
            WHERE date = ?
              {machine_filter}
            ORDER BY hour
        """, params)
        rows = [dict(r) for r in cur.fetchall()]

    # Pastikan semua 24 jam ada (isi 0 jika tidak ada)
    hours_map = {r["hour"]: r for r in rows}
    result = []
    for h in range(24):
        if h in hours_map:
            result.append(hours_map[h])
        else:
            result.append({
                "hour": h,
                "volume_liters": 0,
                "transactions": 0,
                "revenue": 0
            })

    return result


def get_daily_sales(machine_id: str = None, days: int = 30) -> list[dict]:
    """
    Ambil data penjualan harian untuk grafik mingguan/bulanan.
    Dikelompokkan berdasarkan tanggal waktu lokal (TZ_SQL_MODIFIER), bukan
    tanggal UTC — lihat catatan timezone di get_sales_summary().
    """
    machine_filter = "AND machine_id = ?" if machine_id else ""
    params = [f"-{days} days"] + ([machine_id] if machine_id else [])

    with db_cursor() as cur:
        cur.execute(f"""
            SELECT 
                DATE(created_at, '{TZ_SQL_MODIFIER}') as date,
                COALESCE(SUM(volume_actual), 0) as volume_liters,
                COUNT(*) as transactions,
                COALESCE(SUM(amount), 0) as revenue
            FROM transactions
            WHERE created_at >= DATETIME('now', '{TZ_SQL_MODIFIER}', ?)
              AND payment_status = 'PAID'
              AND dispense_status = 'COMPLETE'
              {machine_filter}
            GROUP BY DATE(created_at, '{TZ_SQL_MODIFIER}')
            ORDER BY date
        """, params)
        return [dict(r) for r in cur.fetchall()]


# ─────────────────────────────────────────
# MACHINE STATUS — Extended
# ─────────────────────────────────────────

def get_all_machines_status() -> list[dict]:
    """
    Ambil status semua mesin dari cache.

    CATATAN (perbaikan): kolom `machine_state_cache.online` cuma di-set 1
    setiap ada pesan status MQTT masuk, dan TIDAK PERNAH otomatis di-set 0
    kalau ESP32 mati/dicabut begitu saja (beda dengan disconnect graceful
    ke broker, yang ditangani terpisah di mqtt_bridge._on_disconnect).
    Akibatnya dashboard selalu bilang "Online" walau mesin sudah lama mati.

    Di sini status online dihitung ULANG berdasarkan selisih waktu sejak
    `last_seen` dibanding sekarang (lihat MACHINE_OFFLINE_TIMEOUT_SEC di
    config/settings.py) — jadi kalau lebih dari 30 detik tidak ada status
    baru masuk, mesin otomatis dianggap offline di response berikutnya,
    tanpa perlu task/polling terpisah (loop broadcast WebSocket di
    routes/websocket.py sudah manggil fungsi ini tiap beberapa detik).
    """
    with db_cursor() as cur:
        cur.execute(f"""
            SELECT 
                s.machine_id,
                m.name,
                m.latitude,
                m.longitude,
                m.address,
                m.location_source,
                s.state,
                s.mode,
                s.g1_level_pct,
                s.g2_level_pct,
                s.g1_status,
                s.g2_status,
                s.active_galon,
                s.total_available_liters,
                CASE
                    WHEN s.online = 1
                         AND s.last_seen IS NOT NULL
                         AND (strftime('%s', 'now') - strftime('%s', s.last_seen)) <= {MACHINE_OFFLINE_TIMEOUT_SEC}
                    THEN 1 ELSE 0
                END AS online,
                s.last_seen,
                s.raw_json
            FROM machine_state_cache s
            LEFT JOIN machines m ON m.machine_id = s.machine_id
            WHERE COALESCE(m.is_active, 1) = 1
            ORDER BY s.machine_id
        """)
        return [dict(r) for r in cur.fetchall()]


def get_machine_online_status(machine_id: str) -> dict:
    """
    Cek status online/offline mesin.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT 
                online,
                last_seen,
                strftime('%s', 'now') - strftime('%s', last_seen) as seconds_since_last_seen
            FROM machine_state_cache
            WHERE machine_id = ?
        """, (machine_id,))
        row = cur.fetchone()
        if not row:
            return {"online": False, "last_seen": None, "seconds_since_last_seen": None}

        data = dict(row)
        # Jika lebih dari MACHINE_OFFLINE_TIMEOUT_SEC detik tidak ada update, anggap offline
        if data["seconds_since_last_seen"] and data["seconds_since_last_seen"] > MACHINE_OFFLINE_TIMEOUT_SEC:
            data["online"] = False

        return data


# ─────────────────────────────────────────
# IOT DASHBOARD — Aggregated Data
# ─────────────────────────────────────────

def get_iot_dashboard_data(machine_id: str = None) -> dict:
    """
    Ambil semua data yang dibutuhkan dashboard IoT dalam satu panggilan.
    """
    # 1. Status semua mesin
    machines = get_all_machines_status()

    # Filter jika machine_id spesifik
    if machine_id:
        machines = [m for m in machines if m["machine_id"] == machine_id]

    # 2. Ringkasan hari ini
    summary = get_sales_summary(machine_id, "today")

    # 3. Grafik per jam (hari ini)
    hourly = get_hourly_sales(machine_id)

    # 4. Transaksi terbaru (10)
    transactions, _ = get_transactions_filtered(
        machine_id=machine_id,
        limit=10,
        offset=0
    )

    # 5. Lokasi mesin
    locations = get_all_machines_locations()

    return {
        "machines": machines,
        "summary": summary,
        "hourly_sales": hourly,
        "recent_transactions": transactions,
        "locations": locations,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def get_iot_chart_data(machine_id: str = None, chart_type: str = "daily") -> dict:
    """
    Ambil data grafik.
    chart_type: hourly | weekly | monthly
    """
    if chart_type == "hourly":
        data = get_hourly_sales(machine_id)
        return {
            "type": "hourly",
            "labels": [f"{d['hour']:02d}:00" for d in data],
            "datasets": {
                "volume": [d["volume_liters"] for d in data],
                "transactions": [d["transactions"] for d in data],
                "revenue": [d["revenue"] for d in data]
            }
        }

    elif chart_type == "weekly":
        data = get_daily_sales(machine_id, days=7)
        return {
            "type": "weekly",
            "labels": [d["date"] for d in data],
            "datasets": {
                "volume": [d["volume_liters"] for d in data],
                "transactions": [d["transactions"] for d in data],
                "revenue": [d["revenue"] for d in data]
            }
        }

    else:  # monthly
        data = get_daily_sales(machine_id, days=30)
        return {
            "type": "monthly",
            "labels": [d["date"] for d in data],
            "datasets": {
                "volume": [d["volume_liters"] for d in data],
                "transactions": [d["transactions"] for d in data],
                "revenue": [d["revenue"] for d in data]
            }
        }
    
# ─────────────────────────────────────────
# MACHINE SETTINGS (config + signage)
# ─────────────────────────────────────────

def get_machine_settings(machine_id: str) -> dict:
    """Ambil semua config + daftar slide untuk mesin.

    Catatan: dashboard admin butuh melihat SEMUA slide (termasuk yang
    nonaktif) supaya tombol toggle aktif/nonaktif bisa dibalik lagi —
    kalau cuma slide aktif yang dikirim, begitu dinonaktifkan slide akan
    hilang dari daftar dan tidak bisa diaktifkan ulang dari UI.
    """
    config = get_machine_config(machine_id)
    slides = get_signage_slides(machine_id, active_only=False)
    base_url = "/media/signage/"
    slides = [
        {**s, "url": f"{base_url}{s['file_path']}"}
        for s in slides
    ]
    return {
        "config": config,
        "slides": slides,
    }

def update_machine_settings(machine_id: str, config_dict: dict) -> dict:
    """
    Update satu atau lebih key di machine_config.
    config_dict: {key: value, ...}
    """
    with db_cursor() as cur:
        for key, value in config_dict.items():
            cur.execute("""
                INSERT INTO machine_config (machine_id, key, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(machine_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (machine_id, key, str(value)))
    return get_machine_config(machine_id)

def get_signage_slides(machine_id: str, active_only: bool = True) -> list[dict]:
    """Ambil daftar slide signage untuk mesin."""
    with db_cursor() as cur:
        sql = """
            SELECT id, machine_id, slide_order, media_type, file_path, caption, is_active, created_at
            FROM machine_signage_slides
            WHERE machine_id = ?
        """
        if active_only:
            sql += " AND is_active = 1"
        sql += " ORDER BY slide_order ASC, id ASC"
        cur.execute(sql, (machine_id,))
        return [dict(r) for r in cur.fetchall()]

def add_signage_slide(machine_id: str, media_type: str, file_path: str, caption: str = None, order: int = None) -> int:
    """Tambah slide baru. Jika order tidak diberikan, letakkan di akhir."""
    with db_cursor() as cur:
        if order is None:
            cur.execute("SELECT MAX(slide_order) FROM machine_signage_slides WHERE machine_id = ?", (machine_id,))
            max_order = cur.fetchone()[0]
            order = (max_order or 0) + 1
        cur.execute("""
            INSERT INTO machine_signage_slides (machine_id, media_type, file_path, caption, slide_order)
            VALUES (?, ?, ?, ?, ?)
        """, (machine_id, media_type, file_path, caption, order))
        return cur.lastrowid

def update_signage_slide(slide_id: int, **kwargs) -> bool:
    """Update field slide (slide_order, is_active, caption)."""
    allowed = {"slide_order", "is_active", "caption"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [slide_id]
    with db_cursor() as cur:
        cur.execute(f"UPDATE machine_signage_slides SET {set_clause} WHERE id = ?", values)
        return cur.rowcount > 0

def delete_signage_slide(slide_id: int) -> bool:
    """Hapus slide dari database (file fisik harus dihapus terpisah)."""
    with db_cursor() as cur:
        cur.execute("DELETE FROM machine_signage_slides WHERE id = ?", (slide_id,))
        return cur.rowcount > 0

def get_signage_slide(slide_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM machine_signage_slides WHERE id = ?", (slide_id,))
        row = cur.fetchone()
        return dict(row) if row else None

# ─────────────────────────────────────────
# APP GLOBAL CONFIG
# ─────────────────────────────────────────

def get_app_config(key: str, default: str = None) -> str:
    """Ambil nilai konfigurasi global."""
    with db_cursor() as cur:
        cur.execute("SELECT value FROM app_config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

def set_app_config(key: str, value: str) -> bool:
    """Set nilai konfigurasi global."""
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        """, (key, value))
        return True
    
# ─────────────────────────────────────────
# APP TICKETS (simulasi database aplikasi)
# ─────────────────────────────────────────

def get_ticket_by_suffix(suffix: str, machine_id: str) -> Optional[dict]:
    """
    Cari tiket berdasarkan 6 digit terakhir (suffix).
    Hanya yang status ACTIVE dan belum expired.
    Return None jika tidak ditemukan, expired, atau sudah dipakai.

    PERBAIKAN: sebelumnya pakai `ticket_code LIKE '%-' || suffix`, dengan
    `suffix` masuk mentah ke pattern LIKE. Karakter SQL wildcard di LIKE
    ('%' dan '_') tidak di-escape, jadi kalau suffix yang diinput kebetulan
    mengandung salah satu karakter itu, artinya berubah jadi "cocok apa saja"
    bukan literal — bisa memicu false-positive match di luar 6 karakter yang
    sebenarnya diketik user. Sekarang pakai SUBSTR + perbandingan exact
    (case-insensitive lewat UPPER di kedua sisi), tidak ada semantik
    wildcard sama sekali.
    """
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM app_tickets
            WHERE UPPER(SUBSTR(ticket_code, -6)) = UPPER(?)
              AND status = 'ACTIVE'
              AND expires_at > ?
        """, (suffix, now))
        rows = cur.fetchall()
    
    # Ambiguous: lebih dari 1 cocok → tolak (keamanan)
    if len(rows) == 0:
        return None
    if len(rows) > 1:
        # Logging untuk investigasi, tapi jangan bocorkan ke response
        logger.warning(f"Ambiguous ticket suffix: {suffix} -> {len(rows)} matches")
        return None
    return dict(rows[0])


def create_verify_session(ticket_code: str, machine_id: str) -> str:
    """Buat verify_session token untuk QR kiosk (expires 3 menit)."""
    import secrets
    token = f"vts_{secrets.token_hex(16)}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=3)
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ticket_verify_sessions (verify_token, ticket_code, machine_id, expires_at)
            VALUES (?, ?, ?, ?)
        """, (token, ticket_code, machine_id, expires_at.isoformat()))
    return token


def get_verify_session(token: str) -> Optional[dict]:
    """
    Ambil data verify_session, cek belum expired & belum dipakai.

    PERBAIKAN: sebelumnya bandingnya `expires_at > CURRENT_TIMESTAMP`.
    expires_at disimpan lewat Python `datetime.isoformat()` (format
    "2026-07-23T04:14:00.123456+00:00", ada 'T' dan offset zona waktu),
    sedangkan CURRENT_TIMESTAMP bawaan SQLite formatnya beda
    ("2026-07-23 04:14:00", pakai spasi, tanpa offset). Dibandingkan
    sebagai TEKS, karakter 'T' (0x54) selalu > spasi (0x20) di posisi yang
    sama, jadi expires_at HAMPIR SELALU dianggap "belum lewat" walau
    faktanya sudah lama kedaluwarsa — sudah dites langsung dan terbukti
    session yang sengaja dibuat expired 10 menit lalu tetap lolos filter.
    Sekarang dua sisinya dinormalisasi lewat datetime() SQLite supaya
    dibandingkan sebagai waktu sungguhan, bukan string mentah.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT * FROM ticket_verify_sessions
            WHERE verify_token = ?
              AND used = 0
              AND datetime(expires_at) > datetime('now')
        """, (token,))
        row = cur.fetchone()
        return dict(row) if row else None


def mark_verify_session_used(token: str) -> bool:
    """Tandai session sudah dipakai (atomic). Return True jika berhasil."""
    with db_cursor() as cur:
        cur.execute("""
            UPDATE ticket_verify_sessions
            SET used = 1
            WHERE verify_token = ? AND used = 0
        """, (token,))
        return cur.rowcount > 0


def mark_ticket_used(ticket_code: str, order_id: str) -> bool:
    """
    Tandai tiket sebagai USED dan catat used_at.
    Return True jika berhasil.
    """
    now = datetime.now(timezone.utc).isoformat()
    with db_cursor() as cur:
        cur.execute("""
            UPDATE app_tickets
            SET status = 'USED', used_at = ?
            WHERE ticket_code = ? AND status = 'ACTIVE'
        """, (now, ticket_code))
        return cur.rowcount > 0


def get_ticket_by_code(ticket_code: str) -> Optional[dict]:
    """Ambil tiket berdasarkan kode lengkap (untuk keperluan internal)."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM app_tickets WHERE ticket_code = ?", (ticket_code,))
        row = cur.fetchone()
        return dict(row) if row else None


def count_failed_verify_attempts(machine_id: str, window_minutes: int = 10) -> int:
    """
    Hitung jumlah percobaan verify-code yang GAGAL dari machine_id dalam
    N menit terakhir — dipakai buat rate limiting brute-force kode 6 digit.

    PERBAIKAN: fungsi lama (count_verify_attempts) menghitung baris di
    ticket_verify_sessions, padahal tabel itu CUMA keisi kalau kode yang
    dimasukkan BENAR (create_verify_session dipanggil setelah tiket
    ketemu). Akibatnya percobaan kode yang SALAH tidak pernah tercatat di
    manapun, jadi brute-force tebak kode tidak pernah kena limit sama
    sekali — limiter-nya baru "aktif" justru kalau orangnya berhasil
    nebak berkali-kali, kebalikan dari yang seharusnya dicegah. Sekarang
    dihitung dari tabel ticket_verify_attempts yang mencatat SETIAP
    percobaan (lihat record_verify_attempt), dan yang dihitung khusus
    yang GAGAL — supaya user yang kebetulan salah ketik sekali lalu benar
    tidak ikut kena limit.
    """
    with db_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) as total FROM ticket_verify_attempts
            WHERE machine_id = ? AND success = 0
              AND created_at > datetime('now', ?)
        """, (machine_id, f'-{window_minutes} minutes'))
        return cur.fetchone()['total']


def record_verify_attempt(machine_id: str, code: str, success: bool):
    """Catat SETIAP percobaan verify-code (berhasil maupun gagal)."""
    with db_cursor() as cur:
        cur.execute("""
            INSERT INTO ticket_verify_attempts (machine_id, code_attempted, success)
            VALUES (?, ?, ?)
        """, (machine_id, code, 1 if success else 0))

def apply_global_default_to_all_machines(key: str, value: str) -> int:
    """
    Terapkan nilai default ke semua mesin aktif.
    - Jika key = 'default_price' → update machine_config price_per_liter.
    - Jika key = 'default_mode' → update machines.mode.
    Kembalikan jumlah mesin yang terkena dampak.
    """
    if key == 'default_price':
        with db_cursor() as cur:
            cur.execute("""
                INSERT OR REPLACE INTO machine_config (machine_id, key, value, updated_at)
                SELECT machine_id, 'price_per_liter', ?, CURRENT_TIMESTAMP
                FROM machines
                WHERE is_active = 1
            """, (value,))
            # Broadcast ke semua mesin yang aktif
            cur.execute("SELECT machine_id FROM machines WHERE is_active = 1")
            rows = cur.fetchall()
            from services.mqtt_bridge import broadcast_config_update
            for row in rows:
                broadcast_config_update(row["machine_id"])
            return len(rows)

    elif key == 'default_mode':
        # PERBAIKAN: sebelumnya fungsi ini cuma UPDATE machines.mode di DB lalu
        # broadcast_config_update() (WebSocket ke kiosk saja). Perintah MQTT
        # SET_MODE ke ESP32 TIDAK pernah dikirim, jadi mode mesin fisik baru
        # benar-benar berubah kalau admin buka Settings per-mesin dan klik
        # Simpan Pengaturan lagi satu-satu. Sekarang tombol "Default Mode"
        # global langsung mengirim SET_MODE ke tiap mesin aktif, dan DB hanya
        # di-update untuk mesin yang publish-nya sukses (konsisten dengan
        # perilaku endpoint per-mesin di routes/iot_settings.py).
        from services.mqtt_bridge import publish_set_mode_command, broadcast_config_update
        with db_cursor() as cur:
            cur.execute("SELECT machine_id FROM machines WHERE is_active = 1")
            rows = cur.fetchall()
        applied = 0
        for row in rows:
            mid = row["machine_id"]
            if publish_set_mode_command(mid, value):
                with db_cursor() as cur:
                    cur.execute("UPDATE machines SET mode = ? WHERE machine_id = ?", (value, mid))
                broadcast_config_update(mid)
                applied += 1
            else:
                logger.error(f"Global default_mode: SET_MODE gagal dikirim ke {mid}, mesin ini dilewati (mode tidak diubah).")
        return applied

    return 0