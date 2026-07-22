"""
xendit_webhook_sim.py
======================
Simulasi webhook Xendit (Payment Requests API) untuk testing lokal Toyamas.

Beda penting dari simulator Midtrans lama:
  - TIDAK ada signature yang dihitung ulang. Xendit cukup kirim token statis
    di header X-CALLBACK-TOKEN, jadi skrip ini tinggal menempelkan
    XENDIT_CALLBACK_TOKEN yang sama seperti di .env backend.
  - Payload webhook Xendit berbentuk {"event": ..., "data": {...}}, bukan
    field flat seperti Midtrans (order_id, status_code, dst di top-level).
  - "reference_id" (bukan "order_id") yang jadi field pencocok transaksi.

Cara pakai:
    python xendit_webhook_sim.py
    → Masukkan order_id / pilih dari daftar transaksi terbaru

Atau langsung via argumen:
    python xendit_webhook_sim.py TYM-1782780237-F596
    python xendit_webhook_sim.py TYM-1782780237-F596 --status expired
    python xendit_webhook_sim.py TYM-1782780237-F596 --status failed

Status yang tersedia (mengikuti nilai "status" Xendit):
    succeeded  → pembayaran berhasil (default)
    failed     → gagal
    expired    → kadaluarsa
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

import sqlite3

# ════════════════════════════════════════════════════════
# KONFIGURASI — sesuaikan jika berbeda
# ════════════════════════════════════════════════════════

BACKEND_URL  = "http://localhost:8000"
WEBHOOK_PATH = "/api/payment/notify"

# Dibaca langsung dari backend/.env (SAMA seperti cara xendit_simulate_scan.py
# baca XENDIT_SECRET_KEY) — supaya kalau XENDIT_CALLBACK_TOKEN di-regenerate
# di dashboard Xendit dan .env di-update, skrip ini otomatis ikut, TANPA
# perlu diedit manual. Sebelumnya token di-hardcode langsung di sini, jadi
# gampang basi (nyangkut token lama) begitu token di .env diganti — sumber
# bug klasik: skrip bilang "berhasil" test lokal padahal token beda dari
# yang aktif, atau sebaliknya token lama nyangkut ke repo/history git.
def load_env_value(key: str) -> str:
    env_candidates = [
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent / "backend" / ".env",
        Path(".env"),
    ]
    for env_path in env_candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


CALLBACK_TOKEN = load_env_value("XENDIT_CALLBACK_TOKEN")

# Path database SQLite relatif dari folder backend/
DB_CANDIDATES = [
    Path(__file__).parent / "backend" / "database" / "toyamas_local.db",
    Path(__file__).parent / "database" / "toyamas_local.db",
    Path("database") / "toyamas_local.db",
    Path("backend") / "database" / "toyamas_local.db",
]

SUCCESS_STATUSES = {"succeeded"}
FAILED_STATUSES  = {"failed", "expired", "cancelled", "voided"}

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════

def find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    return None


def get_transaction_from_db(order_id: str):
    """Ambil data transaksi dari SQLite lokal."""
    db_path = find_db()
    if not db_path:
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM transactions WHERE order_id = ? OR order_id LIKE ?",
            (order_id, f"%{order_id}%")
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"  [DB] Error: {e}")
        return None


def list_recent_transactions(limit: int = 10):
    """Ambil transaksi terbaru dari DB untuk pilihan interaktif."""
    db_path = find_db()
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT order_id, amount, volume_requested, payment_status,
                      payment_method, created_at
               FROM transactions
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def build_webhook_payload(order_id: str, gross_amount: float, status: str) -> dict:
    """
    Bangun payload webhook Xendit Payment Requests API yang valid.
    Format persis seperti dokumentasi Xendit:
      {"event": "payment.succeeded", "data": {"id":..., "status":..., "reference_id":...}}
    """
    event_map = {
        "succeeded": "payment.succeeded",
        "failed":    "payment.failed",
        "expired":   "payment.expired",
    }
    event = event_map.get(status, "payment.succeeded")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    return {
        "event": event,
        "business_id": "sim-business-id",
        "created": now_iso,
        "data": {
            "id":           f"py-sim-{uuid.uuid4().hex[:12]}",
            "amount":       gross_amount,
            "status":       status.upper() if status != "succeeded" else "SUCCEEDED",
            "currency":     "IDR",
            "reference_id": order_id,
            "payment_method": {"type": "QR_CODE"},
            "created":      now_iso,
            "updated":      now_iso,
        },
    }


def send_webhook(payload: dict) -> dict:
    """Kirim webhook ke backend lokal, lengkap dengan header X-CALLBACK-TOKEN."""
    url = f"{BACKEND_URL}{WEBHOOK_PATH}"
    resp = requests.post(
        url,
        json=payload,
        headers={"X-CALLBACK-TOKEN": CALLBACK_TOKEN},
        timeout=10,
    )
    return {
        "status_code": resp.status_code,
        "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
    }


def print_separator(char="─", width=60):
    print(char * width)


def print_result(label: str, value, color_code: str = ""):
    reset = "\033[0m"
    print(f"  {color_code}{label:<22}{reset} {value}")


def colorize(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


# ════════════════════════════════════════════════════════
# MAIN FLOW
# ════════════════════════════════════════════════════════

def run_simulation(order_id: str, status: str):
    print()
    print_separator("═")
    print("  TOYAMAS — Simulasi Webhook Xendit")
    print_separator("═")

    if not CALLBACK_TOKEN:
        print(f"\n  {colorize('⚠️  XENDIT_CALLBACK_TOKEN tidak ditemukan di .env!', '33')}")
        print("     Pastikan backend/.env ada dan sudah diisi XENDIT_CALLBACK_TOKEN,")
        print("     atau jalankan skrip ini dari dalam folder backend/.")
        ans = input("  Lanjutkan tetap (webhook akan DITOLAK backend)? (y/N): ").strip().lower()
        if ans != "y":
            sys.exit(1)

    # ── 1. Cek koneksi backend ──
    print(f"\n  Mengecek backend {BACKEND_URL} ...")
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"  {colorize('✅ Backend online', '32')} (status {r.status_code})")
    except requests.exceptions.ConnectionError:
        print(f"  {colorize('❌ Backend tidak bisa dijangkau', '31')}")
        print("     Pastikan backend sudah jalan: uvicorn main:app --reload")
        sys.exit(1)

    # ── 2. Cari transaksi di DB ──
    print(f"\n  Mencari order: {colorize(order_id, '36')} ...")
    trx = get_transaction_from_db(order_id)

    if trx:
        gross_amount = float(trx.get("amount", 500))
        volume       = trx.get("volume_requested", 0)
        pay_status   = trx.get("payment_status", "PENDING")
        print(f"  {colorize('✅ Transaksi ditemukan di database', '32')}")
        print_result("Order ID:",  trx["order_id"])
        print_result("Volume:",    f"{volume} liter")
        print_result("Amount:",    f"Rp {int(gross_amount):,}")
        print_result("Status DB:", pay_status)

        if pay_status == "PAID":
            print()
            print(f"  {colorize('⚠️  Transaksi ini sudah PAID sebelumnya.', '33')}")
            ans = input("  Kirim webhook tetap? (y/N): ").strip().lower()
            if ans != "y":
                print("  Dibatalkan.")
                return
    else:
        print(f"  {colorize('⚠️  Order tidak ditemukan di database lokal.', '33')}")
        try:
            gross_input = input("  Masukkan amount (IDR, contoh: 500): ").strip()
            gross_amount = float(gross_input) if gross_input else 500.0
        except ValueError:
            gross_amount = 500.0
        print(f"  Amount: Rp {int(gross_amount):,}")

    # ── 3. Build payload ──
    payload = build_webhook_payload(order_id=order_id, gross_amount=gross_amount, status=status)

    # ── 4. Preview payload ──
    print()
    print_separator()
    print("  Payload webhook yang akan dikirim:")
    print_separator()
    print_result("event:", payload["event"])
    for k, v in payload["data"].items():
        print_result(f"data.{k}:", v)
    print_separator()

    # ── 5. Konfirmasi ──
    status_label = {
        "succeeded": colorize("✅ SUCCEEDED (sukses)", "32"),
        "failed":    colorize("❌ FAILED (gagal)", "31"),
        "expired":   colorize("❌ EXPIRED (kadaluarsa)", "31"),
    }.get(status, status)

    print(f"\n  Status yang akan disimulasikan: {status_label}")
    ans = input("  Kirim webhook sekarang? (Y/n): ").strip().lower()
    if ans == "n":
        print("  Dibatalkan.")
        return

    # ── 6. Kirim ──
    print(f"\n  Mengirim ke {BACKEND_URL}{WEBHOOK_PATH} ...")
    try:
        result = send_webhook(payload)
        http_code = result["status_code"]
        body      = result["body"]

        print()
        print_separator("═")
        if http_code == 200:
            resp_status = body.get("status", "") if isinstance(body, dict) else str(body)

            if resp_status == "ok":
                print(f"  {colorize('✅ BERHASIL', '32')} — Backend menerima dan memproses webhook")
                if status in SUCCESS_STATUSES:
                    print(f"  {colorize('→ Command DISPENSE dikirim ke ESP32', '32')}")
                    print("  → Cek Serial Monitor ESP32 untuk konfirmasi")
                    print("  → UI browser seharusnya pindah ke halaman guide")
                elif status in FAILED_STATUSES:
                    print("  → Transaksi ditandai FAILED di database")
            elif resp_status == "ignored":
                print(f"  {colorize('⚠️  Webhook DITOLAK backend', '33')} — X-CALLBACK-TOKEN tidak cocok")
                print("     Cek CALLBACK_TOKEN di script ini sama dengan XENDIT_CALLBACK_TOKEN di .env")
            elif resp_status == "already_paid":
                print(f"  {colorize('ℹ️  Order sudah dibayar sebelumnya', '34')} — tidak diproses ulang")
            elif resp_status == "order_not_found":
                print(f"  {colorize('⚠️  Order tidak ditemukan di backend', '33')}")
            else:
                print(f"  Response: {resp_status}")
        else:
            print(f"  {colorize(f'❌ HTTP {http_code}', '31')} — {body}")

        print_separator("═")

    except requests.exceptions.ConnectionError:
        print(f"  {colorize('❌ Koneksi gagal', '31')} — backend tidak merespons")
    except Exception as e:
        print(f"  {colorize(f'❌ Error: {e}', '31')}")


def interactive_mode():
    print()
    print("═" * 60)
    print("  TOYAMAS — Simulasi Webhook Xendit")
    print("  Konfirmasi transaksi pembayaran secara lokal")
    print("═" * 60)

    transactions = list_recent_transactions(10)
    if transactions:
        print(f"\n  Transaksi terbaru di database ({find_db()}):\n")
        print(f"  {'No':<4} {'Order ID':<28} {'Amount':>8} {'Vol':>5} {'Status':<12} {'Waktu'}")
        print("  " + "─" * 72)
        for i, t in enumerate(transactions, 1):
            status_color = {
                "PAID":    "32",
                "PENDING": "33",
                "FAILED":  "31",
            }.get(t["payment_status"], "0")
            created = t.get("created_at", "")[:16] if t.get("created_at") else "-"
            print(
                f"  {i:<4} "
                f"{t['order_id']:<28} "
                f"Rp {int(t['amount'] or 0):>6,} "
                f"{t.get('volume_requested', 0):>4.1f}L "
                f"\033[{status_color}m{t['payment_status']:<12}\033[0m "
                f"{created}"
            )
        print()

        choice = input("  Pilih nomor (atau ketik order_id langsung): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(transactions):
            order_id = transactions[int(choice) - 1]["order_id"]
        else:
            order_id = choice
    else:
        print("\n  Database tidak ditemukan atau kosong.")
        order_id = input("  Masukkan order_id: ").strip()

    if not order_id:
        print("  Order ID tidak boleh kosong.")
        sys.exit(1)

    print()
    print("  Pilih status webhook:")
    print("    1. succeeded  — pembayaran berhasil")
    print("    2. failed     — gagal")
    print("    3. expired    — kadaluarsa")
    print()
    status_map = {"1": "succeeded", "2": "failed", "3": "expired"}
    status_choice = input("  Pilih [1-3] (default: 1 = succeeded): ").strip()
    status = status_map.get(status_choice, "succeeded")

    run_simulation(order_id, status)


# ════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulasi webhook Xendit untuk Toyamas")
    parser.add_argument(
        "order_id", nargs="?",
        help="Order ID (opsional, jika tidak diisi akan interaktif)"
    )
    parser.add_argument(
        "--status", default="succeeded",
        choices=["succeeded", "failed", "expired"],
        help="Status webhook yang disimulasikan (default: succeeded)"
    )
    parser.add_argument(
        "--backend", default="http://localhost:8000",
        help="URL backend (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--token", default=None,
        help="Override X-CALLBACK-TOKEN (jika tidak ingin edit script)"
    )

    args = parser.parse_args()
    BACKEND_URL = args.backend
    if args.token:
        CALLBACK_TOKEN = args.token

    if args.order_id:
        run_simulation(args.order_id, args.status)
    else:
        interactive_mode()
