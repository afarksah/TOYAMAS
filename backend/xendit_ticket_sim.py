#!/usr/bin/env python3
"""
xendit_ticket_sim.py
=====================
Simulasi aplikasi HP scan QR kiosk untuk alur tiket BARU.

Alur:
1. Kiosk sudah menampilkan QR (berisi verify_session) setelah user input 6 digit.
2. Skrip ini dapat menerima --suffix (6 digit) untuk otomatis panggil verify-code,
   atau --verify-session langsung.
3. Skrip generate user_jwt (menggunakan JWT_SECRET dari .env) untuk akun yang cocok.
4. Skrip panggil POST /api/ticket/confirm-scan dengan payload {verify_session, user_jwt}.

Cara pakai:
    # Dengan suffix (otomatis ambil verify_session dan account_id)
    python xendit_ticket_sim.py --suffix MPH6GV

    # Langsung tentukan verify_session dan user_id (email)
    python xendit_ticket_sim.py --verify-session vts_8f3a1c9b... --user-id budi@gmail.com

    # Mode interaktif (minta verify_session manual)
    python xendit_ticket_sim.py
"""

import argparse
import sys
import json
import time
import jwt
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install dulu: pip install requests")
    sys.exit(1)

# ════════════════════════════════════════════════════════
# KONFIGURASI
# ════════════════════════════════════════════════════════

BACKEND_URL = "http://localhost:8000"

ENV_CANDIDATES = [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / "backend" / ".env",
    Path(".env"),
]

def load_env_value(key: str) -> str:
    """Baca satu nilai dari backend/.env tanpa python-dotenv."""
    for env_path in ENV_CANDIDATES:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

JWT_SECRET = load_env_value("JWT_SECRET")
JWT_ALGORITHM = "HS256"

if not JWT_SECRET:
    print("❌ JWT_SECRET tidak ditemukan di .env. Pastikan backend/.env ada dan terisi.")
    sys.exit(1)

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════

def colorize(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def extract_error(body: dict) -> tuple:
    """
    Ambil (error_code, message) dari body respons, mendukung DUA bentuk:
    - Rejection bisnis biasa (200, success:false): {"error": "...", "message"?: "..."}
    - Error sistem (4xx/5xx via HTTPException): {"detail": {"error": "...", "message": "..."}}
    Tanpa ini, kasus 500 INTERNAL_ERROR salah kebaca sebagai "UNKNOWN_ERROR"
    karena error code-nya ada di dalam body["detail"], bukan di top-level.
    """
    if not isinstance(body, dict):
        return "UNKNOWN_ERROR", str(body)
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("error", "UNKNOWN_ERROR"), detail.get("message", "Tidak ada detail")
    if isinstance(detail, str):
        return "UNKNOWN_ERROR", detail
    return body.get("error", "UNKNOWN_ERROR"), body.get("message", "Tidak ada detail")

def build_user_jwt(user_id: str) -> str:
    """Buat JWT untuk user (harus sama dengan account_id di tiket)."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "type": "user_auth",
        "iat": now,
        "exp": now + 300,  # 5 menit
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def call_verify_code(suffix: str, machine_id: str = "TYM-001") -> dict:
    """Panggil POST /api/ticket/verify-code untuk mendapatkan verify_session dan info tiket."""
    resp = requests.post(
        f"{BACKEND_URL}/api/ticket/verify-code",
        json={"code": suffix, "machine_id": machine_id},
        timeout=10,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"error": "Invalid JSON response", "raw": resp.text}
    return {
        "status_code": resp.status_code,
        "body": body,
        "ok": resp.status_code == 200 and body.get("success") is True,
    }

def confirm_scan(verify_session: str, user_jwt: str) -> dict:
    """Panggil POST /api/ticket/confirm-scan ke backend."""
    resp = requests.post(
        f"{BACKEND_URL}/api/ticket/confirm-scan",
        json={
            "verify_session": verify_session,
            "user_jwt": user_jwt,
        },
        timeout=10,
    )
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {"error": "Invalid JSON response", "raw": resp.text}
    return {
        "status_code": resp.status_code,
        "body": body,
        "ok": resp.status_code == 200 and body.get("success") is True,
    }

# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════

def run_with_suffix(suffix: str, machine_id: str = "TYM-001"):
    """Alur dengan suffix: panggil verify-code dulu, lalu confirm-scan."""
    print()
    print("═" * 62)
    print("  TOYAMAS — Simulasi Scan Tiket (via suffix)")
    print("═" * 62)

    # 1. Cek backend
    print(f"\n  Mengecek backend {BACKEND_URL} ...")
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"  {colorize('✅ Backend online', '32')} (status {r.status_code})")
    except requests.exceptions.ConnectionError:
        print(f"  {colorize('❌ Backend tidak bisa dijangkau', '31')}")
        print("     Pastikan backend sudah jalan: uvicorn main:app --reload")
        sys.exit(1)

    # 2. Panggil verify-code
    print(f"\n  Mencari tiket dengan suffix: {colorize(suffix, '36')} ...")
    result = call_verify_code(suffix, machine_id)
    if not result["ok"]:
        error, msg = extract_error(result["body"])
        print(f"  {colorize('❌ Gagal verifikasi kode:', '31')} {error}")
        print(f"  Pesan: {msg}")
        sys.exit(1)

    data = result["body"]
    verify_session = data.get("verify_session")
    account_name = data.get("account_name")
    volume_liter = data.get("volume_liter")
    ticket_code_masked = data.get("ticket_code_masked")

    if not verify_session:
        print(f"  {colorize('❌ verify_session tidak ditemukan dalam response', '31')}")
        sys.exit(1)

    print(f"\n  {colorize('✅ Tiket ditemukan:', '32')}")
    print(f"     Nama: {account_name}")
    print(f"     Volume: {int(volume_liter * 1000)} ml")
    print(f"     Kode: {ticket_code_masked}")
    print(f"     verify_session: {colorize(verify_session, '36')}")

    # 3. Gunakan account_name sebagai user_id (atau email? Kita butuh email untuk JWT)
    # Karena di generate_fake_tickets.py, account_id = email. Kita perlu email.
    # Tapi di response verify-code tidak ada email. Kita minta user input email.
    print("\n  Untuk melanjutkan, masukkan email pemilik tiket (account_id):")
    user_id = input("  Email: ").strip()
    if not user_id:
        print("  Email tidak boleh kosong. Gunakan email yang sesuai dengan tiket.")
        sys.exit(1)

    # 4. Build JWT
    user_jwt = build_user_jwt(user_id)
    print(f"  user_jwt generated (exp 5 menit)")

    # 5. Konfirmasi
    ans = input("\n  Kirim confirm-scan sekarang? (Y/n): ").strip().lower()
    if ans == "n":
        print("  Dibatalkan.")
        return

    # 6. Kirim confirm-scan
    print(f"\n  Mengirim ke {BACKEND_URL}/api/ticket/confirm-scan ...")
    result2 = confirm_scan(verify_session, user_jwt)

    print()
    print("─" * 62)
    if result2["ok"]:
        print(f"  {colorize('✅ TIKET BERHASIL DIREDEEM', '32')}")
        print(f"  order_id:      {result2['body'].get('order_id')}")
        print(f"  volume_liter:  {result2['body'].get('volume_liter')}")
        print()
        print("  Selanjutnya OTOMATIS:")
        print("    → WS 'ticket_verified' terkirim ke kiosk")
        print("    → Kiosk pindah ke halaman guide")
        print("    → User klik 'Siap' → countdown → air mengalir")
        print("  Cek Serial Monitor ESP32 untuk konfirmasi command DISPENSE diterima.")
    else:
        status = result2["status_code"]
        body = result2["body"]
        error, msg = extract_error(body)
        error_map = {
            "SESSION_INVALID_OR_EXPIRED": "Session sudah expired atau tidak ditemukan.",
            "USER_AUTH_INVALID": "user_jwt tidak valid. Cek JWT_SECRET di .env.",
            "USER_MISMATCH": "Akun yang scan bukan pemilik tiket ini.",
            "TICKET_ALREADY_USED": "Tiket sudah pernah digunakan.",
            "TICKET_EXPIRED": "Tiket sudah melewati batas berlaku.",
            "GALON_INSUFFICIENT": "Stok air tidak mencukupi untuk volume tiket ini.",
            "INTERNAL_ERROR": "Terjadi kesalahan internal di server.",
        }
        print(f"  {colorize(f'❌ GAGAL (HTTP {status})', '31')}")
        print(f"  error:   {error}")
        print(f"  message: {error_map.get(error, msg)}")
    print("─" * 62)


def run_manual(verify_session: str, user_id: str):
    """Alur manual (seperti sebelumnya)."""
    print()
    print("═" * 62)
    print("  TOYAMAS — Simulasi Scan Tiket dari HP (confirm-scan)")
    print("═" * 62)

    # 1. Cek backend
    print(f"\n  Mengecek backend {BACKEND_URL} ...")
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        print(f"  {colorize('✅ Backend online', '32')} (status {r.status_code})")
    except requests.exceptions.ConnectionError:
        print(f"  {colorize('❌ Backend tidak bisa dijangkau', '31')}")
        print("     Pastikan backend sudah jalan: uvicorn main:app --reload")
        sys.exit(1)

    if not verify_session:
        print("\n  ⚠️  verify_session tidak diberikan.")
        verify_session = input("  Masukkan verify_session dari QR kiosk: ").strip()
        if not verify_session:
            print("  ❌ verify_session wajib diisi.")
            sys.exit(1)

    print(f"\n  verify_session: {colorize(verify_session, '36')}")
    print(f"  user_id (account_id tiket): {colorize(user_id, '36')}")

    # 2. Build JWT
    user_jwt = build_user_jwt(user_id)
    print(f"  user_jwt generated (exp 5 menit)")

    # 3. Konfirmasi
    ans = input("\n  Kirim confirm-scan sekarang? (Y/n): ").strip().lower()
    if ans == "n":
        print("  Dibatalkan.")
        return

    # 4. Panggil endpoint
    print(f"\n  Mengirim ke {BACKEND_URL}/api/ticket/confirm-scan ...")
    result = confirm_scan(verify_session, user_jwt)

    print()
    print("─" * 62)
    if result["ok"]:
        print(f"  {colorize('✅ TIKET BERHASIL DIREDEEM', '32')}")
        print(f"  order_id:      {result['body'].get('order_id')}")
        print(f"  volume_liter:  {result['body'].get('volume_liter')}")
        print()
        print("  Selanjutnya OTOMATIS:")
        print("    → WS 'ticket_verified' terkirim ke kiosk")
        print("    → Kiosk pindah ke halaman guide")
        print("    → User klik 'Siap' → countdown → air mengalir")
        print("  Cek Serial Monitor ESP32 untuk konfirmasi command DISPENSE diterima.")
    else:
        status = result["status_code"]
        body = result["body"]
        error, msg = extract_error(body)
        error_map = {
            "SESSION_INVALID_OR_EXPIRED": "Session sudah expired atau tidak ditemukan.",
            "USER_AUTH_INVALID": "user_jwt tidak valid. Cek JWT_SECRET di .env.",
            "USER_MISMATCH": "Akun yang scan bukan pemilik tiket ini.",
            "TICKET_ALREADY_USED": "Tiket sudah pernah digunakan.",
            "TICKET_EXPIRED": "Tiket sudah melewati batas berlaku.",
            "GALON_INSUFFICIENT": "Stok air tidak mencukupi untuk volume tiket ini.",
            "INTERNAL_ERROR": "Terjadi kesalahan internal di server.",
        }
        print(f"  {colorize(f'❌ GAGAL (HTTP {status})', '31')}")
        print(f"  error:   {error}")
        print(f"  message: {error_map.get(error, msg)}")
    print("─" * 62)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simulasi HP scan QR + confirm-scan untuk alur tiket baru"
    )
    parser.add_argument("--suffix", default=None,
                        help="6 digit suffix (misal MPH6GV) - otomatis panggil verify-code")
    parser.add_argument("--verify-session", default=None,
                        help="verify_session dari QR (manual mode)")
    parser.add_argument("--user-id", default="budi@gmail.com",
                        help="User ID (email) untuk manual mode")
    parser.add_argument("--machine-id", default="TYM-001",
                        help="Machine ID untuk verify-code (default: TYM-001)")
    parser.add_argument("--backend", default="http://localhost:8000",
                        help="URL backend")
    args = parser.parse_args()
    BACKEND_URL = args.backend

    if args.suffix:
        run_with_suffix(args.suffix, args.machine_id)
    elif args.verify_session:
        run_manual(args.verify_session, args.user_id)
    else:
        # Mode interaktif: tanya mau pakai suffix atau verify_session
        print()
        print("Pilih metode:")
        print("  1. Masukkan 6 digit suffix (otomatis ambil verify_session)")
        print("  2. Masukkan verify_session manual")
        choice = input("Pilih [1/2]: ").strip()
        if choice == "1":
            suffix = input("Masukkan 6 digit suffix: ").strip().upper()
            if len(suffix) != 6:
                print("❌ Suffix harus 6 karakter.")
                sys.exit(1)
            run_with_suffix(suffix, args.machine_id)
        else:
            verify_session = input("Masukkan verify_session: ").strip()
            user_id = input("Masukkan email pemilik tiket (account_id): ").strip() or "budi@gmail.com"
            run_manual(verify_session, user_id)