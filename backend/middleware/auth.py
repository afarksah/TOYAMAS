"""
middleware/auth.py
Semua logika keamanan: HMAC-SHA256, JWT, bcrypt, admin session
"""
import hashlib
import hmac
import json
import time
import logging
import bcrypt
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional
import jwt
from fastapi import Request, HTTPException, Header, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.settings import (
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MIN,
    MACHINE_ID, XENDIT_CALLBACK_TOKEN, BCRYPT_ROUNDS
)
from services.database import db_cursor, get_machine_secret

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────
# BCRYPT - Password Hashing
# ─────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash password dengan bcrypt."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verifikasi password terhadap hash bcrypt."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


# ─────────────────────────────────────────
# HMAC — ESP32 ↔ Backend
# ─────────────────────────────────────────

def compute_mqtt_hmac(payload_dict: dict, machine_id: str = MACHINE_ID) -> str:
    """
    Hitung HMAC-SHA256 untuk payload MQTT.
    Payload harus berupa dict TANPA field 'hmac'.
    """
    key = f"{machine_id}:{get_machine_secret(machine_id)}".encode()
    payload_bytes = json.dumps(payload_dict, separators=(",", ":"),
                               ensure_ascii=False).encode()
    return hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()


def verify_mqtt_hmac(payload_dict: dict, received_hmac: str,
                     machine_id: str = MACHINE_ID,
                     raw_bytes: bytes = None) -> bool:
    """
    Verifikasi HMAC dari payload MQTT yang masuk dari ESP32.
    """
    try:
        key = f"{machine_id}:{get_machine_secret(machine_id)}".encode()

        if raw_bytes is not None:
            import re
            raw_str = raw_bytes.decode("utf-8")
            cleaned = re.sub(r',\s*"hmac"\s*:\s*"[0-9a-fA-F]+"', '', raw_str)
            cleaned = re.sub(r'"hmac"\s*:\s*"[0-9a-fA-F]+"\s*,\s*', '', cleaned)
            cleaned = re.sub(r'"hmac"\s*:\s*"[0-9a-fA-F]+"', '', cleaned)
            body_bytes = cleaned.encode("utf-8")
            expected = hmac.new(key, body_bytes, hashlib.sha256).hexdigest()
        else:
            clean = {k: v for k, v in payload_dict.items() if k != "hmac"}
            body_bytes = json.dumps(clean, separators=(",", ":"),
                                    ensure_ascii=False).encode()
            expected = hmac.new(key, body_bytes, hashlib.sha256).hexdigest()

        return hmac.compare_digest(expected, received_hmac)

    except Exception as e:
        logger.warning(f"HMAC verification error: {e}")
        return False


def compute_command_hmac(cmd: str, session_id: str,
                         volume: float, issued_at: int,
                         machine_id: str = MACHINE_ID) -> str:
    """
    HMAC untuk perintah backend → ESP32.
    Format: HMAC("{cmd}:{session_id}:{volume}:{issued_at}")
    """
    key = f"{machine_id}:{get_machine_secret(machine_id)}".encode()
    message = f"{cmd}:{session_id}:{volume:.3f}:{issued_at}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


# ─────────────────────────────────────────
# JWT — Admin Session
# ─────────────────────────────────────────

def create_admin_session(user_data: dict) -> str:
    """
    Buat JWT session untuk admin yang sudah login.
    user_data = {'username': ..., 'name': ..., 'role': ...}
    """
    now = int(time.time())
    payload = {
        "sub": user_data["username"],
        "name": user_data.get("name", user_data["username"]),
        "role": user_data.get("role", "admin"),
        "type": "admin_session",
        "iat": now,
        "exp": now + (JWT_EXPIRE_MIN * 60),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_admin_session(token: str) -> dict:
    """
    Verifikasi JWT session admin.
    Raise HTTPException jika tidak valid / expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "admin_session":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan session admin"
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session sudah kedaluwarsa, login ulang"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token tidak valid: {e}"
        )


# ─────────────────────────────────────────
# FastAPI Dependency: require admin
# ─────────────────────────────────────────

async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    FastAPI dependency — require admin session.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required"
        )

    token = credentials.credentials
    payload = verify_admin_session(token)

    # Cek di database apakah masih aktif
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, is_active FROM admins WHERE username = ?",
            (payload["sub"],)
        )
        admin = cur.fetchone()
        if not admin or not admin["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun admin tidak aktif"
            )

    return payload


# ─────────────────────────────────────────
# Kiosk Session Token (untuk tiket)
# ─────────────────────────────────────────

def create_kiosk_session_token(machine_id: str = MACHINE_ID) -> tuple[str, datetime]:
    """
    Generate JWT session token untuk QR kiosk (metode tiket).
    Return: (token_string, expires_at_datetime)
    """
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(minutes=JWT_EXPIRE_MIN)
    payload = {
        "sub": machine_id,
        "type": "kiosk_session",
        "machine_id": machine_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, expires_at


def verify_kiosk_session_token(token: str) -> dict:
    """
    Verifikasi JWT kiosk session.
    Raise HTTPException jika tidak valid / expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "kiosk_session":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan session kiosk"
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session kiosk sudah kedaluwarsa"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token tidak valid: {e}"
        )


# ─────────────────────────────────────────
# Admin PIN (tetap dipakai untuk kiosk admin)
# ─────────────────────────────────────────

def hash_admin_pin(pin: str) -> str:
    """SHA256 hash PIN admin (4 digit)."""
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_admin_pin(pin: str, stored_hash: str) -> bool:
    """Verifikasi PIN admin dengan compare_digest (anti timing attack)."""
    computed = hash_admin_pin(pin)
    return hmac.compare_digest(computed, stored_hash)


# ─────────────────────────────────────────
# XENDIT — Webhook Token Verification
# ─────────────────────────────────────────
# Beda konsep dari Midtrans: Xendit TIDAK mengirim signature yang harus
# dihitung ulang. Xendit cukup mengirim token statis (didapat sekali dari
# dashboard, sama untuk semua webhook) di header X-CALLBACK-TOKEN. Kita
# tinggal compare token itu dengan XENDIT_CALLBACK_TOKEN kita — bukan
# meng-hash apapun dari body.

def _mask_token(t: str) -> str:
    """Tampilkan cuma 4 karakter awal+akhir token, buat debug tanpa bocorin secret."""
    if not t:
        return "(kosong)"
    if len(t) <= 8:
        return t[0] + "***"
    return f"{t[:4]}...{t[-4:]} (len={len(t)})"


def validate_xendit_webhook(callback_token: Optional[str], body: dict) -> bool:
    """
    Validasi webhook Xendit.
    callback_token: nilai header X-CALLBACK-TOKEN dari request.
    Return True jika valid, False jika ada yang mencurigakan.
    """
    if not callback_token:
        logger.error(
            "[XENDIT-WEBHOOK] DITOLAK — header X-CALLBACK-TOKEN tidak ada sama sekali "
            "di request. Cek apakah URL webhook di dashboard Xendit memang mengirim "
            "header ini (mis. jangan-jangan yang terdaftar bukan endpoint /api/payment/notify)."
        )
        return False

    if not hmac.compare_digest(callback_token, XENDIT_CALLBACK_TOKEN):
        logger.error(
            "[XENDIT-WEBHOOK] DITOLAK — X-CALLBACK-TOKEN TIDAK COCOK.\n"
            f"    diterima dari Xendit : {_mask_token(callback_token)}\n"
            f"    dikonfigurasi di .env: {_mask_token(XENDIT_CALLBACK_TOKEN)}\n"
            "    → Buka dashboard.xendit.co > Settings > Webhooks, pastikan "
            "'Verification Token' sama persis dengan XENDIT_CALLBACK_TOKEN di .env "
            "(tidak ada spasi/kutip nyangkut, dan bukan token yang sudah di-regenerate)."
        )
        return False

    reference_id = (body.get("data") or {}).get("reference_id", "")
    if reference_id and not reference_id.startswith("TYM-"):
        logger.error(f"[XENDIT-WEBHOOK] DITOLAK — reference_id format aneh: {reference_id}")
        return False

    logger.info("[XENDIT-WEBHOOK] Token X-CALLBACK-TOKEN valid ✓")
    return True


# ─────────────────────────────────────────
# User JWT (untuk aplikasi tiket)
# ─────────────────────────────────────────

def create_demo_user_jwt(user_id: str = "user_demo_kiosk") -> str:
    """
    JWT user PALSU khusus buat testing/simulasi lokal (tombol "Simulasi Deteksi
    Scan Tiket HP" di kiosk & xendit_ticket_sim.py). BUKAN untuk alur produksi
    sungguhan — token ini valid karena ditandatangani JWT_SECRET yang sama
    persis seperti token asli dari sistem login aplikasi user, jadi HANYA
    dipanggil dari sisi server (lihat routes/ticket.py dev-simulate-redeem),
    supaya JWT_SECRET tidak pernah terkirim ke browser/kiosk.
    """
    now = int(time.time())
    payload = {
        "sub":  user_id,
        "type": "user_auth",
        "iat":  now,
        "exp":  now + 300,   # 5 menit, cukup untuk sekali redeem simulasi
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_user_jwt(user_jwt: str) -> dict:
    """
    Verifikasi JWT user dari aplikasi.
    Di produksi: verifikasi dengan public key Cloudflare / auth provider.
    """
    try:
        payload = jwt.decode(user_jwt, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") not in ("user_auth", "user"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan user token"
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User session kedaluwarsa, silakan login ulang"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User token tidak valid: {e}"
        )


# ─────────────────────────────────────────
# FastAPI Dependency: kiosk token
# ─────────────────────────────────────────

async def require_kiosk_token(
    x_kiosk_token: str = Header(None, alias="X-Kiosk-Token")
) -> dict:
    """
    FastAPI dependency — require header X-Kiosk-Token.
    Dipakai di endpoint yang hanya bisa dipanggil dari UI kiosk.
    """
    if not x_kiosk_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Kiosk-Token header wajib ada"
        )
    return verify_kiosk_session_token(x_kiosk_token)