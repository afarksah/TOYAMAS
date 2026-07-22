"""
routes/ticket.py
Endpoint verifikasi dan pencairan tiket dari aplikasi user (ALUR BARU).

Alur:
1. Kiosk: user input 6 digit terakhir tiket → POST /api/ticket/verify-code
2. Backend: cari di app_tickets, valid, buat verify_session, return token ke kiosk
3. Kiosk: tampilkan QR (isi verify_session) + info tiket (nama, volume)
4. User buka app HP → scan QR → app panggil POST /api/ticket/confirm-scan
5. Backend: validasi verify_session + user_jwt → tandai tiket USED
   → buat transaksi → broadcast WS 'ticket_verified' → kiosk pindah ke guide
6. User klik "Siap" → jalur confirm-dispense / start-dispense (sama seperti payment)
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, validator

from config.settings import (
    MACHINE_ID, DEBUG,
    CF_TICKET_REDEEM_URL, CF_API_TOKEN,
    GALON_EMPTY_PCT
)
from middleware.auth import (
    verify_kiosk_session_token,
    verify_user_jwt,
    create_demo_user_jwt,
)
from services.database import (
    get_ticket_by_suffix,
    create_verify_session,
    get_verify_session,
    mark_verify_session_used,
    mark_ticket_used,
    get_ticket_by_code,
    count_verify_attempts,
    create_transaction,
    get_state_cache,
    get_machine,
)
from services.mqtt_bridge import publish_dispense_command, ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Ticket"])


# ─────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────

class VerifyCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="6 digit terakhir tiket")
    machine_id: str = Field(default=MACHINE_ID)

class VerifyCodeResponse(BaseModel):
    success: bool
    verify_session: Optional[str] = None
    account_name: Optional[str] = None   # Nama LENGKAP (tidak dimasking)
    volume_liter: Optional[float] = None
    ticket_code_masked: Optional[str] = None
    expires_in: int = 180
    error: Optional[str] = None

class ConfirmScanRequest(BaseModel):
    verify_session: str = Field(...)
    user_jwt: str = Field(...)

class ConfirmScanResponse(BaseModel):
    success: bool
    order_id: Optional[str] = None
    volume_liter: Optional[float] = None
    error: Optional[str] = None


# ─────────────────────────────────────────
# ENDPOINT 1: Kiosk input 6 digit → verify-code
# ─────────────────────────────────────────

@router.post("/api/ticket/verify-code", response_model=VerifyCodeResponse)
async def verify_ticket_code(req: VerifyCodeRequest):
    """
    Dipanggil kiosk setelah user memasukkan 6 digit terakhir tiket.
    Jika valid, buat verify_session dan return ke kiosk untuk di-QR-kan.
    """
    machine_id = req.machine_id

    # 1. Cek apakah mesin terdaftar
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")

    # 2. Rate limiting (5 percobaan / 10 menit)
    attempts = count_verify_attempts(machine_id, window_minutes=10)
    if attempts >= 5:
        logger.warning(f"Rate limit exceeded for machine {machine_id}")
        return VerifyCodeResponse(
            success=False,
            error="RATE_LIMITED",
            expires_in=0
        )

    # 3. Cari tiket di DB berdasarkan suffix
    ticket = get_ticket_by_suffix(req.code, machine_id)
    if not ticket:
        # Jangan bedakan "not found" vs "expired" di response publik
        return VerifyCodeResponse(
            success=False,
            error="CODE_NOT_FOUND",
            expires_in=0
        )

    # 4. Cek apakah tiket ini valid untuk mesin ini? (opsional)
    #    Kita bisa tambahkan kolom allowed_machine_id nanti, tapi untuk sekarang
    #    tiket berlaku di semua mesin (kecuali diatur lain).

    # 5. Buat verify_session (short-lived, single-use)
    token = create_verify_session(ticket["ticket_code"], machine_id)

    # 6. Siapkan data untuk UI
    volume_liter = ticket["volume_ml"] / 1000.0
    # Masking ticket code untuk tampilan: TKT-01KTWDXX2K...MPH6GV
    full_code = ticket["ticket_code"]
    if len(full_code) > 16:
        masked_code = full_code[:8] + "..." + full_code[-6:]
    else:
        masked_code = full_code

    return VerifyCodeResponse(
        success=True,
        verify_session=token,
        account_name=ticket["account_name"],  # Nama lengkap (tidak dimasking)
        volume_liter=volume_liter,
        ticket_code_masked=masked_code,
        expires_in=180,  # 3 menit
        error=None
    )


# ─────────────────────────────────────────
# ENDPOINT 2: App HP scan QR → confirm-scan
# ─────────────────────────────────────────

@router.post("/api/ticket/confirm-scan", response_model=ConfirmScanResponse)
async def confirm_ticket_scan(req: ConfirmScanRequest):
    """
    Dipanggil oleh APLIKASI HP setelah user melakukan scan QR di kiosk.
    Verify_session + user_jwt wajib valid.
    """
    # 1. Verifikasi verify_session
    session = get_verify_session(req.verify_session)
    if not session:
        return ConfirmScanResponse(
            success=False,
            error="SESSION_INVALID_OR_EXPIRED"
        )

    # 2. Verifikasi user_jwt (pastikan user login & cocok dengan pemilik tiket)
    try:
        user_payload = verify_user_jwt(req.user_jwt)
    except HTTPException:
        return ConfirmScanResponse(
            success=False,
            error="USER_AUTH_INVALID"
        )

    user_id = user_payload.get("sub") or user_payload.get("user_id")
    if not user_id:
        return ConfirmScanResponse(
            success=False,
            error="USER_AUTH_INVALID"
        )

    # 3. Ambil data tiket dari DB
    ticket_code = session["ticket_code"]
    ticket = get_ticket_by_code(ticket_code)
    if not ticket:
        return ConfirmScanResponse(
            success=False,
            error="TICKET_NOT_FOUND"
        )

    # 4. Cocokkan account_id di tiket dengan user_id dari JWT
    if ticket["account_id"] != user_id:
        logger.warning(f"Ticket {ticket_code} belongs to {ticket['account_id']}, but scanned by {user_id}")
        return ConfirmScanResponse(
            success=False,
            error="USER_MISMATCH"
        )

    # 5. Cek status & expire (re-check untuk keamanan)
    if ticket["status"] != "ACTIVE":
        return ConfirmScanResponse(
            success=False,
            error="TICKET_ALREADY_USED"
        )
    if datetime.now(timezone.utc) > datetime.fromisoformat(ticket["expires_at"]):
        return ConfirmScanResponse(
            success=False,
            error="TICKET_EXPIRED"
        )

    # 6. Ambil machine_id dari session
    machine_id = session["machine_id"]

    # 7. Cek kapasitas galon
    cache = get_state_cache(machine_id)
    volume_liter = ticket["volume_ml"] / 1000.0
    if cache:
        available = cache.get("total_available_liters", 0)
        if available < volume_liter:
            return ConfirmScanResponse(
                success=False,
                error="GALON_INSUFFICIENT"
            )

    # ─── ATOMIC BLOCK: tandai session & tiket used, buat transaksi ───
    # Gunakan transaction atomic di database (SQLite)
    from services.database import db_cursor

    try:
        with db_cursor() as cur:
            # 8a. Mark session used
            cur.execute("""
                UPDATE ticket_verify_sessions
                SET used = 1
                WHERE verify_token = ? AND used = 0
            """, (req.verify_session,))
            if cur.rowcount == 0:
                return ConfirmScanResponse(
                    success=False,
                    error="SESSION_ALREADY_USED"
                )

            # 8b. Mark tiket used
            now_iso = datetime.now(timezone.utc).isoformat()
            cur.execute("""
                UPDATE app_tickets
                SET status = 'USED', used_at = ?
                WHERE ticket_code = ? AND status = 'ACTIVE'
            """, (now_iso, ticket_code))
            if cur.rowcount == 0:
                # Rollback akan otomatis terjadi karena exception
                raise ValueError("Ticket already used")

            # 8c. Buat transaksi di tabel transactions (source=TICKET)
            order_id = f"TKT-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:4].upper()}"
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

            cur.execute("""
                INSERT INTO transactions (
                    order_id, machine_id, session_id, source,
                    volume_requested, amount, ticket_code,
                    payment_status, dispense_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PAID', 'WAITING')
            """, (
                order_id, machine_id, session_id, "TICKET",
                volume_liter, ticket["amount"], ticket_code
            ))

            transaction = {
                "order_id": order_id,
                "machine_id": machine_id,
                "session_id": session_id,
                "volume_liter": volume_liter,
                "ticket_code": ticket_code
            }

    except Exception as e:
        logger.error(f"Atomic transaction failed: {e}")
        return ConfirmScanResponse(
            success=False,
            error="INTERNAL_ERROR"
        )

    # 9. Broadcast ke kiosk via WS (event ticket_verified)
    await ws_manager.broadcast(
        machine_id,
        "ticket_verified",
        {
            "ticket_code":  ticket_code,
            "volume_liter": volume_liter,
            "issued_at":    ticket.get("created_at", ""),
            "redeemed_at":  now_iso,
            "user_name":    ticket["account_name"],
            "order_id":     order_id,
            "session_id":   session_id,
        }
    )

    logger.info(
        f"Ticket redeemed: {ticket_code} vol={volume_liter}L "
        f"user={user_id} machine={machine_id}"
    )

    # ⚠️ NOTE: MQTT DISPENSE TIDAK LANGSUNG DIKIRIM DI SINI!
    # Ikut pola payment: user harus klik "Siap" di guide page dulu.
    # confirm-dispense dan start-dispense (di payment.py) akan dipanggil
    # nanti dan akan mengirim MQTT.

    return ConfirmScanResponse(
        success=True,
        order_id=order_id,
        volume_liter=volume_liter,
        error=None
    )


# ─────────────────────────────────────────
# (Opsional) Simulasi Dev — HAPUS / NONAKTIFKAN di production
# ─────────────────────────────────────────

@router.post("/api/ticket/dev-simulate-redeem")
async def dev_simulate_ticket_redeem(request: Request):
    """
    [DEV ONLY] Endpoint ini TIDAK DIPAKAI LAGI di alur baru.
    Dipertahankan untuk kompatibilitas mundur, tapi akan return 404
    jika APP_ENV=production. Sebaiknya dihapus setelah migrasi.
    """
    if not DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "success": False,
        "message": "Endpoint deprecated. Gunakan verify-code + confirm-scan.",
        "deprecated": True
    }