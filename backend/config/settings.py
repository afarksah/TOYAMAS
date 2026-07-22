"""
config/settings.py
Konfigurasi terpusat Toyamas Backend
Semua nilai sensitif WAJIB dari environment variable di produksi
"""
import os
import base64
from pathlib import Path
from dotenv import load_dotenv

# ─────────────────────────────────────────
# BASE
# ─────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent.parent

# WAJIB dipanggil SEBELUM os.getenv() manapun di bawah ini, jika tidak
# semua nilai dari .env akan diabaikan dan fallback ke default hardcode.
load_dotenv(BASE_DIR / ".env")

DATABASE_PATH = str(BASE_DIR / "database" / "toyamas_local.db")
MACHINE_ID    = os.getenv("MACHINE_ID", "TYM-001")
APP_ENV       = os.getenv("APP_ENV", "development")   # development | production
DEBUG         = APP_ENV == "development"

# ─────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────
# Secret untuk JWT kiosk session & HMAC command signing
JWT_SECRET      = os.getenv("JWT_SECRET", "toyamas-dev-jwt-secret-ganti-di-produksi")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_MIN  = 120          # session kiosk token: 2 menit

# Shared secret antara ESP32 dan backend untuk HMAC-SHA256
MACHINE_SECRET  = os.getenv("MACHINE_SECRET", "toyamas-esp32-hmac-secret")

# Admin PIN default (hash SHA256, akan dioverride dari DB)
DEFAULT_ADMIN_PIN_HASH = os.getenv(
    "DEFAULT_ADMIN_PIN_HASH",
    "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4"  # "1234"
)

# Bcrypt rounds (semakin tinggi semakin lambat, 12 cukup)
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# ─────────────────────────────────────────
# TIMEZONE
# ─────────────────────────────────────────
# Semua timestamp di database (SQLite CURRENT_TIMESTAMP / datetime.now(timezone.utc))
# disimpan dalam UTC. TIMEZONE_OFFSET_HOURS dipakai untuk menghitung batas
# "hari ini"/"jam ini" berdasarkan kalender waktu lokal bisnis, bukan kalender
# UTC — supaya transaksi dini hari (00:00–07:59 WITA) tidak salah terhitung
# masuk ke laporan "kemarin". WITA (Sulawesi, dll) = UTC+8.
TIMEZONE_OFFSET_HOURS = int(os.getenv("TIMEZONE_OFFSET_HOURS", "8"))
TZ_SQL_MODIFIER = f"{'+' if TIMEZONE_OFFSET_HOURS >= 0 else ''}{TIMEZONE_OFFSET_HOURS} hours"

# ─────────────────────────────────────────
# MQTT (EMQX Public Broker - sandbox)
# Ganti ke broker private di produksi
# ─────────────────────────────────────────
MQTT_BROKER   = os.getenv("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_TLS  = os.getenv("MQTT_USE_TLS", "false").lower() == "true"
MQTT_QOS      = 1

# Topic templates — format: toyamas/{machine_id}/{subtopic}
MQTT_TOPIC_STATUS   = f"toyamas/{MACHINE_ID}/status"
MQTT_TOPIC_FLOW     = f"toyamas/{MACHINE_ID}/flow"
MQTT_TOPIC_ALARM    = f"toyamas/{MACHINE_ID}/alarm"
MQTT_TOPIC_COMMAND  = f"toyamas/{MACHINE_ID}/command"

# Wildcard topics — dipakai backend untuk subscribe status/flow/alarm dari
# SEMUA mesin sekaligus (satu backend pusat melayani banyak TYM-xxx), bukan
# cuma MACHINE_ID tunggal di atas. "+" = single-level MQTT wildcard, cocok
# dengan format toyamas/{machine_id}/{subtopic} (tepat 3 segmen).
MQTT_TOPIC_STATUS_WILDCARD = "toyamas/+/status"
MQTT_TOPIC_FLOW_WILDCARD   = "toyamas/+/flow"
MQTT_TOPIC_ALARM_WILDCARD  = "toyamas/+/alarm"

# ─────────────────────────────────────────
# XENDIT (Payment Requests API — QRIS)
# ─────────────────────────────────────────
# WAJIB diisi lewat .env — TIDAK ADA fallback hardcode.
# Ambil Secret Key dari dashboard.xendit.co → Settings → API Keys.
# PENTING beda dari Midtrans: sandbox/produksi Xendit BUKAN dua base URL
# berbeda — base URL-nya selalu https://api.xendit.co. Mode sandbox vs
# produksi ditentukan dari JENIS key yang dipakai:
#   - Test Secret Key  (prefix "xnd_development_...") → transaksi simulasi
#   - Live Secret Key  (prefix "xnd_production_...")  → transaksi asli
# Jadi cukup ganti key di .env untuk pindah mode, tidak perlu flag terpisah.
XENDIT_SECRET_KEY = os.getenv("XENDIT_SECRET_KEY")
if not XENDIT_SECRET_KEY:
    raise RuntimeError(
        "XENDIT_SECRET_KEY belum diisi di .env. "
        "Ambil dari dashboard.xendit.co → Settings → API Keys. "
        "Pakai key 'xnd_development_...' untuk testing, "
        "'xnd_production_...' untuk transaksi asli."
    )

# Token verifikasi webhook (BUKAN HMAC yang dihitung ulang seperti Midtrans).
# Xendit mengirim token statis ini apa adanya di header X-CALLBACK-TOKEN
# setiap webhook — cukup dibandingkan string-nya, tidak perlu hitung ulang
# signature. Ambil dari dashboard.xendit.co → Settings → Webhooks →
# "Verification Token".
XENDIT_CALLBACK_TOKEN = os.getenv("XENDIT_CALLBACK_TOKEN")
if not XENDIT_CALLBACK_TOKEN:
    raise RuntimeError(
        "XENDIT_CALLBACK_TOKEN belum diisi di .env. "
        "Ambil dari dashboard.xendit.co → Settings → Webhooks → "
        "Verification Token."
    )

# Basic auth: Base64(secret_key:) — sama pola dengan Midtrans, cuma beda key.
XENDIT_AUTH = base64.b64encode(
    f"{XENDIT_SECRET_KEY}:".encode()
).decode()

XENDIT_BASE_URL = "https://api.xendit.co"

# Payment Requests API — endpoint generik Xendit untuk semua metode bayar
# (QRIS, e-wallet, VA, dll). Kita pakai payment_method.type = "QR_CODE"
# dengan channel_code "QRIS" supaya QR-nya bisa discan semua e-wallet/
# m-banking yang support QRIS, bukan cuma satu provider seperti contoh
# lama "acquirer: gopay" di Midtrans.
XENDIT_PAYMENT_REQUEST_URL        = f"{XENDIT_BASE_URL}/payment_requests"
XENDIT_PAYMENT_REQUEST_STATUS_URL = f"{XENDIT_BASE_URL}/payment_requests/{{payment_request_id}}"

# HTTP headers untuk request ke Xendit API
XENDIT_HEADERS = {
    "Accept":        "application/json",
    "Content-Type":  "application/json",
    "Authorization": f"Basic {XENDIT_AUTH}",
}

# Status yang dianggap Xendit sebagai pembayaran berhasil / gagal.
# Ini dipakai baik untuk field top-level "status" di response create/get,
# maupun field "data.status" di payload webhook "payment.succeeded" /
# "payment.failed" / "payment.expired".
XENDIT_SUCCESS_STATUS = {"SUCCEEDED"}
XENDIT_FAILED_STATUS  = {"FAILED", "EXPIRED", "CANCELLED", "VOIDED"}

# ─────────────────────────────────────────
# CLOUDFLARE D1 (Cloud Database)
# ─────────────────────────────────────────
CF_ACCOUNT_ID  = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN   = os.getenv("CF_API_TOKEN", "")
CF_D1_DB_ID    = os.getenv("CF_D1_DB_ID", "")
CF_WORKER_URL  = os.getenv("CF_WORKER_URL", "https://toyamas-api.your-worker.workers.dev")

# Endpoint Cloudflare Worker untuk validasi tiket
CF_TICKET_VERIFY_URL = f"{CF_WORKER_URL}/api/ticket/verify"
CF_TICKET_REDEEM_URL = f"{CF_WORKER_URL}/api/ticket/redeem"

# ─────────────────────────────────────────
# WEBSOCKET
# ─────────────────────────────────────────
WS_HOST     = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT     = int(os.getenv("PORT", "8000"))
WS_ORIGINS  = os.getenv("WS_ORIGINS", "http://localhost,http://127.0.0.1").split(",")

# ─────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────
RATE_LIMIT_DEFAULT     = "60/minute"
RATE_LIMIT_PAYMENT     = "5/minute"
RATE_LIMIT_TICKET      = "10/minute"
RATE_LIMIT_WEBHOOK     = "30/minute"
RATE_LIMIT_IOT         = "120/minute"   # Dashboard polling

# ─────────────────────────────────────────
# BISNIS LOGIC
# ─────────────────────────────────────────
DEFAULT_PRICE_PER_LITER = 500        # IDR
MIN_VOLUME_LITER        = 0.1
MAX_VOLUME_LITER        = 19.0
GALON_CAPACITY_LITER    = 19.0
GALON_LOW_PCT           = 20.0       # % → trigger WARNING
GALON_CRITICAL_PCT      = 5.0        # % → trigger CRITICAL
GALON_EMPTY_PCT         = 1.0        # % → ERROR, stop semua

# Timeout order Xendit yang stuck di PENDING (menit)
ORDER_PENDING_TIMEOUT_MIN = 15

# ─────────────────────────────────────────
# CORS
# ─────────────────────────────────────────
CORS_ORIGINS = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",  # Untuk Live Server
    "http://127.0.0.1:5500",
    "http://localhost:5173",  # Untuk Vite
    "http://127.0.0.1:5173",
]

# Izinkan semua subdomain ngrok (mis. https://nama-kamu.ngrok-free.app,
# https://xxxx-xx-xx-xx-xx.ngrok-free.app) tanpa perlu hardcode satu-satu.
# Cuma relevan kalau frontend & backend diakses dari origin BERBEDA (mis.
# dua tunnel ngrok terpisah) — kalau kios & dashboard IoT disajikan lewat
# tunnel yang SAMA seperti biasanya (satu `ngrok http 8000` ke backend ini),
# ini tidak akan pernah dipakai karena request-nya sudah same-origin.
CORS_ORIGIN_REGEX = r"https://.*\.ngrok-free\.(app|dev)|https://.*\.ngrok\.io"

# ─────────────────────────────────────────
# IOT DASHBOARD
# ─────────────────────────────────────────
IOT_WS_REFRESH_STATUS_SEC = int(os.getenv("IOT_WS_REFRESH_STATUS_SEC", "2"))
IOT_WS_REFRESH_SALES_SEC = int(os.getenv("IOT_WS_REFRESH_SALES_SEC", "5"))
IOT_WS_REFRESH_LOCATION_HOURS = 1
IOT_TRANSACTIONS_PER_PAGE = 20

# Batas waktu (detik) tanpa pesan status MQTT dari ESP32 sebelum mesin
# dianggap OFFLINE oleh dashboard. Firmware mengirim status tiap 10 detik,
# jadi 30 detik (~3x interval) cukup toleran terhadap jitter jaringan tapi
# tetap responsif. Sebelumnya mesin_state_cache.online cuma di-set 1 saat
# ada pesan masuk dan TIDAK PERNAH direset ke 0 saat ESP32 mati begitu saja
# (beda dengan disconnect graceful broker), jadi dashboard selalu bilang
# "Online" walau mesin sudah mati.
MACHINE_OFFLINE_TIMEOUT_SEC = int(os.getenv("MACHINE_OFFLINE_TIMEOUT_SEC", "30"))