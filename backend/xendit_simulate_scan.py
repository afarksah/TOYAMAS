"""
xendit_simulate_scan.py
========================
Simulasi SCAN BARCODE QRIS memakai endpoint resmi Xendit (test mode):

    POST https://api.xendit.co/v3/payment_requests/{payment_request_id}/simulate

Beda dengan xendit_webhook_sim.py:
  - xendit_webhook_sim.py  → BOHONG-BOHONGAN, langsung kirim payload palsu
    ke /api/payment/notify kita sendiri. Tidak menyentuh Xendit sama sekali.
  - xendit_simulate_scan.py (skrip ini) → MEMANGGIL XENDIT SUNGGUHAN.
    Xendit yang akan memproses "pembayaran" itu lalu Xendit SENDIRI yang
    mengirim webhook payment.succeeded ke URL ngrok Anda. Ini uji end-to-end
    paling realistis — persis seperti kalau ada orang betulan scan QR pakai
    e-wallet, hanya saja tanpa perlu app e-wallet sungguhan.

⚠️ HANYA JALAN dengan API key test mode (xnd_development_...).
   Endpoint /simulate akan ditolak Xendit kalau dipanggil pakai key produksi.

Cara pakai:
    # Mode interaktif — pilih dari daftar transaksi PENDING terbaru
    python xendit_simulate_scan.py

    # Langsung pakai order_id
    python xendit_simulate_scan.py TYM-1784416304-60F3

    # Override jumlah yang disimulasikan (default: ambil dari DB)
    python xendit_simulate_scan.py TYM-1784416304-60F3 --amount 2500

Setelah dijalankan:
  1. Skrip memanggil Xendit, dapat balasan {"status": "PENDING", ...}
     (ini NORMAL — artinya permintaan simulasi diterima, hasil aslinya
     menyusul lewat webhook async, bukan di respons ini).
  2. Dalam beberapa detik, Xendit mengirim webhook payment.succeeded ke
     URL yang terdaftar di dashboard Anda (mis. https://xxx.ngrok-free.dev/api/payment/notify).
  3. Cek terminal backend uvicorn — harus muncul log "Payment PAID: ...".
  4. Layar kiosk (kalau sedang terbuka di halaman QR) akan otomatis
     pindah ke halaman guide.
"""

import argparse
import base64
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ════════════════════════════════════════════════════════
# Load XENDIT_SECRET_KEY dari backend/.env (tanpa perlu dependency dotenv,
# supaya skrip ini bisa jalan standalone walau dotenv belum ke-install)
# ════════════════════════════════════════════════════════

def load_secret_key_from_env() -> str:
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
            if line.startswith("XENDIT_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


XENDIT_SECRET_KEY = load_secret_key_from_env()
XENDIT_API_VERSION = "2024-11-11"

DB_CANDIDATES = [
    Path(__file__).parent / "database" / "toyamas_local.db",
    Path("database") / "toyamas_local.db",
]


def colorize(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def find_db() -> Path:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    return None


def get_transaction(order_id: str) -> dict:
    db_path = find_db()
    if not db_path:
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM transactions WHERE order_id = ? OR order_id LIKE ?",
        (order_id, f"%{order_id}%")
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_pending_transactions(limit: int = 10) -> list:
    db_path = find_db()
    if not db_path:
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT order_id, amount, volume_requested, payment_status,
                  xendit_payment_request_id, created_at
           FROM transactions
           WHERE payment_status = 'PENDING'
             AND xendit_payment_request_id IS NOT NULL
           ORDER BY created_at DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def call_xendit_simulate(payment_request_id: str, amount: float) -> dict:
    """
    Panggil POST /v3/payment_requests/{id}/simulate ke Xendit sungguhan.
    Pakai urllib bawaan Python — tidak perlu install 'requests'.
    """
    url = f"https://api.xendit.co/v3/payment_requests/{payment_request_id}/simulate"
    body = json.dumps({"amount": amount}).encode("utf-8")

    auth_raw = f"{XENDIT_SECRET_KEY}:".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type":  "application/json",
            "api-version":   XENDIT_API_VERSION,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {
                "status_code": resp.status,
                "body": json.loads(resp.read().decode("utf-8")),
            }
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return {"status_code": e.code, "body": parsed}
    except urllib.error.URLError as e:
        return {"status_code": 0, "body": {"error": str(e.reason)}}


def run(order_id: str, amount_override: float = None):
    print()
    print("═" * 60)
    print("  TOYAMAS — Simulasi SCAN BARCODE via Xendit (test mode)")
    print("═" * 60)

    if not XENDIT_SECRET_KEY:
        print(f"\n  {colorize('❌ XENDIT_SECRET_KEY tidak ditemukan', '31')}")
        print("     Pastikan backend/.env ada dan sudah diisi XENDIT_SECRET_KEY,")
        print("     atau jalankan skrip ini dari dalam folder backend/.")
        sys.exit(1)

    if not XENDIT_SECRET_KEY.startswith("xnd_development"):
        print(f"\n  {colorize('⚠️  Peringatan:', '33')} key yang terbaca sepertinya bukan key TEST MODE")
        print(f"     ({XENDIT_SECRET_KEY[:20]}...). Endpoint /simulate hanya jalan di sandbox.")
        ans = input("  Lanjutkan? (y/N): ").strip().lower()
        if ans != "y":
            sys.exit(1)

    trx = get_transaction(order_id)
    if not trx:
        print(f"\n  {colorize('❌ Order tidak ditemukan di database lokal:', '31')} {order_id}")
        sys.exit(1)

    payment_request_id = trx.get("xendit_payment_request_id")
    if not payment_request_id:
        print(f"\n  {colorize('❌ Order ini belum punya xendit_payment_request_id', '31')}")
        print("     Kemungkinan order dibuat sebelum QR sempat digenerate,")
        print("     atau /api/payment/create gagal sebelum sampai simpan ID-nya.")
        sys.exit(1)

    amount = amount_override if amount_override is not None else trx.get("amount", 0)

    print(f"\n  Order ID:            {trx['order_id']}")
    print(f"  Volume:              {trx.get('volume_requested', '-')} liter")
    print(f"  Status pembayaran:   {trx.get('payment_status')}")
    print(f"  payment_request_id:  {colorize(payment_request_id, '36')}")
    print(f"  Amount disimulasikan: Rp {int(amount):,}")

    if trx.get("payment_status") == "PAID":
        print(f"\n  {colorize('⚠️  Order ini sudah PAID sebelumnya.', '33')}")
        ans = input("  Simulasikan scan tetap? (y/N): ").strip().lower()
        if ans != "y":
            print("  Dibatalkan.")
            return

    print()
    ans = input("  Simulasikan scan & bayar sekarang? (Y/n): ").strip().lower()
    if ans == "n":
        print("  Dibatalkan.")
        return

    print(f"\n  Mengirim ke Xendit: POST /v3/payment_requests/{payment_request_id}/simulate ...")
    result = call_xendit_simulate(payment_request_id, amount)

    print()
    print("─" * 60)
    if result["status_code"] == 200:
        body = result["body"]
        print(f"  {colorize('✅ Diterima Xendit', '32')} — status: {body.get('status')}")
        print(f"  {body.get('message', '')}")
        print()
        print("  Selanjutnya OTOMATIS (tanpa aksi tambahan dari Anda):")
        print("    1. Xendit memproses simulasi pembayaran di baliknya")
        print("    2. Xendit kirim webhook 'payment.succeeded' ke URL ngrok Anda")
        print("    3. Cek terminal backend uvicorn → cari log 'Payment PAID: " + order_id + "'")
        print("    4. Kalau kiosk sedang buka halaman QR untuk order ini,")
        print("       layar akan otomatis pindah ke halaman guide")
        print()
        print("  Kalau dalam ~10 detik tidak ada perubahan, cek:")
        print("    - Terminal ngrok: apakah ada baris 'POST /api/payment/notify'?")
        print("    - XENDIT_CALLBACK_TOKEN di .env cocok dengan token di dashboard Xendit?")
        print("    - Webhook 'PAYMENT REQUESTS V3 → Payment Status' sudah diisi URL ngrok?")
    elif result["status_code"] == 404:
        print(f"  {colorize('❌ 404 Not Found', '31')} — payment_request_id tidak ditemukan di Xendit")
        print(f"     Body: {result['body']}")
        print("     Kemungkinan payment_request_id di DB lokal sudah tidak valid/expired.")
    elif result["status_code"] == 403:
        print(f"  {colorize('❌ 403 Forbidden', '31')} — API key tidak punya izin")
        print(f"     Body: {result['body']}")
        print("     Cek permission API key di dashboard Xendit (perlu Money-In Write).")
    else:
        code = result["status_code"]
        print(f"  {colorize(f'❌ HTTP {code}', '31')}")
        print(f"     Body: {result['body']}")
    print("─" * 60)


def interactive_mode():
    print()
    print("═" * 60)
    print("  TOYAMAS — Simulasi SCAN BARCODE via Xendit (test mode)")
    print("═" * 60)

    pending = list_pending_transactions(10)
    if not pending:
        print("\n  Tidak ada transaksi PENDING dengan payment_request_id di database.")
        order_id = input("  Masukkan order_id manual: ").strip()
        if not order_id:
            sys.exit(1)
        run(order_id)
        return

    print(f"\n  Transaksi PENDING terbaru (dari {find_db()}):\n")
    print(f"  {'No':<4} {'Order ID':<28} {'Amount':>10} {'Vol':>6} {'Waktu'}")
    print("  " + "─" * 62)
    for i, t in enumerate(pending, 1):
        created = (t.get("created_at") or "")[:16]
        print(
            f"  {i:<4} {t['order_id']:<28} "
            f"Rp {int(t['amount'] or 0):>7,} "
            f"{t.get('volume_requested', 0):>4.1f}L "
            f"{created}"
        )
    print()

    choice = input("  Pilih nomor (atau ketik order_id langsung): ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(pending):
        order_id = pending[int(choice) - 1]["order_id"]
    else:
        order_id = choice

    if not order_id:
        print("  Order ID tidak boleh kosong.")
        sys.exit(1)

    run(order_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulasi scan barcode QRIS lewat endpoint resmi Xendit (test mode)"
    )
    parser.add_argument("order_id", nargs="?", help="Order ID (kosongkan untuk mode interaktif)")
    parser.add_argument("--amount", type=float, default=None,
                        help="Override jumlah yang disimulasikan (default: ambil dari DB)")

    args = parser.parse_args()

    if args.order_id:
        run(args.order_id, args.amount)
    else:
        interactive_mode()
