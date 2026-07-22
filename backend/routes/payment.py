"""
routes/payment.py
Endpoint pembayaran via Xendit QRIS (Payment Requests API).
POST /api/payment/create  — UI request buat transaksi baru
POST /api/payment/notify  — Webhook dari Xendit (server-to-server)
GET  /api/payment/status/{order_id} — Polling fallback
"""
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, validator

from config.settings import (
    XENDIT_PAYMENT_REQUEST_URL, XENDIT_PAYMENT_REQUEST_STATUS_URL,
    XENDIT_HEADERS, XENDIT_SUCCESS_STATUS, XENDIT_FAILED_STATUS,
    MACHINE_ID, DEFAULT_PRICE_PER_LITER,
    MIN_VOLUME_LITER, MAX_VOLUME_LITER,
    GALON_EMPTY_PCT
)
from middleware.auth import validate_xendit_webhook
from services.database import (
    create_transaction, get_transaction, update_payment_status,
    get_state_cache, get_machine_config, set_xendit_payment_request_id,
    get_active_transaction_for_machine
)
from services.mqtt_bridge import publish_dispense_command, ws_manager

logger   = logging.getLogger(__name__)
router   = APIRouter(prefix="/api/payment", tags=["Payment"])


# ─────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────

class PaymentCreateRequest(BaseModel):
    volume_liter:   float  = Field(..., ge=MIN_VOLUME_LITER, le=MAX_VOLUME_LITER)
    payment_method: str    = Field(default="qris")
    wallet_name:    str    = Field(default="QRIS Universal")
    machine_id:     str    = Field(default=MACHINE_ID)
    kiosk_token:    str    = Field(...)

    @validator("volume_liter")
    def round_volume(cls, v):
        return round(v, 2)


class PaymentCreateResponse(BaseModel):
    order_id:   str
    amount:     int
    qr_string:  str
    qr_url:     str
    expired_at: str
    session_id: str


# ─────────────────────────────────────────
# POST /api/payment/create
# ─────────────────────────────────────────

@router.post("/create", response_model=PaymentCreateResponse)
async def create_payment(req: PaymentCreateRequest):
    """
    Buat transaksi baru dan generate QR Xendit.
    Dipanggil UI kiosk saat user tekan tombol Bayar.
    """
    machine_id = req.machine_id

    # ── 0. Cek mesin sedang tidak dipakai order lain yang belum tuntas ──
    # (sudah PAID tapi galonnya belum selesai terisi/dikonfirmasi). Tanpa
    # ini, order kedua bisa dibuat sementara pelanggan pertama masih di
    # page-guide/page-filling — berpotensi dua sesi dispensing bentrok.
    active = get_active_transaction_for_machine(machine_id)
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error":   "MACHINE_BUSY",
                "message": "Mesin sedang memproses transaksi lain. Silakan tunggu sebentar.",
                "order_id_aktif": active["order_id"],
                "dispense_status": active["dispense_status"],
            }
        )

    # ── 1. Cek kapasitas galon ──
    cache = get_state_cache(machine_id)
    if cache:
        available = cache.get("total_available_liters", 0)
        if available < req.volume_liter:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error":             "GALON_INSUFFICIENT",
                    "message":           "Stok air tidak mencukupi untuk volume yang diminta",
                    "available_liters":  round(available, 2),
                    "requested_liters":  req.volume_liter,
                }
            )

    # ── 2. Hitung harga ──
    config     = get_machine_config(machine_id)
    price_per_l = int(config.get("price_per_liter", DEFAULT_PRICE_PER_LITER))
    amount     = int(req.volume_liter * price_per_l)

    # ── 3. Generate order_id & session_id ──
    ts         = int(time.time())
    order_id   = f"TYM-{ts}-{str(uuid.uuid4())[:4].upper()}"
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # ── 4. Simpan ke DB sebagai PENDING ──
    create_transaction(
        order_id        = order_id,
        machine_id      = machine_id,
        session_id      = session_id,
        source          = "PAYMENT",
        volume_requested= req.volume_liter,
        amount          = amount,
        payment_method  = req.payment_method,
    )

    # ── 5. Request Payment Request (QRIS) ke Xendit ──
    # 1 Liter = 1000 ml
    volume_ml = int(req.volume_liter * 1000)  # 500ml → 500, 750ml → 750, dll
    xendit_body = {
        "reference_id": order_id,
        "currency":     "IDR",
        "amount":       amount,
        "payment_method": {
            "type":        "QR_CODE",
            "reusability": "ONE_TIME_USE",
            "qr_code": {
                # channel_code "QRIS" (bukan nama e-wallet tertentu seperti
                # "gopay" di Midtrans) — QR yang dihasilkan bisa discan
                # semua e-wallet/m-banking yang support jaringan QRIS.
                "channel_code": "QRIS",
            },
        },
        "metadata": {
            "machine_id":   machine_id,
            "volume_liter": req.volume_liter,
            "volume_ml":    volume_ml,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                XENDIT_PAYMENT_REQUEST_URL,
                json    = xendit_body,
                headers = XENDIT_HEADERS,
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Xendit payment request error: {e.response.text}")
        update_payment_status(order_id, "FAILED")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gagal memproses pembayaran via Xendit"
        )
    except httpx.RequestError as e:
        logger.error(f"Xendit connection error: {e}")
        update_payment_status(order_id, "FAILED")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tidak dapat menghubungi Xendit"
        )

    # ── 6. Parse response Xendit ──
    payment_request_id = data.get("id", "")
    qr_code_data = (data.get("payment_method") or {}).get("qr_code") or {}
    qr_string    = (qr_code_data.get("channel_properties") or {}).get("qr_string", "")
    expired_at   = data.get("payment_method", {}).get("qr_code", {}).get(
        "channel_properties", {}
    ).get("expires_at", "")

    # Simpan payment_request_id (format "pr-xxxx") — dibutuhkan nanti untuk
    # GET /payment_requests/{id} saat polling status, karena ID ini beda
    # dari order_id/reference_id yang kita kirim.
    if payment_request_id:
        set_xendit_payment_request_id(order_id, payment_request_id)

    logger.info(f"Payment created: {order_id} amount={amount} vol={req.volume_liter}L")

    return PaymentCreateResponse(
        order_id   = order_id,
        amount     = amount,
        qr_string  = qr_string,
        qr_url     = "",  # Xendit tidak menyediakan URL gambar QR siap pakai
                           # seperti Midtrans — qr_string di-render sendiri
                           # jadi QR image di kiosk (lihat vendor_qrcode.js).
        expired_at = expired_at,
        session_id = session_id,
    )


# ─────────────────────────────────────────
# POST /api/payment/notify  (Xendit Webhook)
# ─────────────────────────────────────────

@router.post("/notify")
async def payment_notify(request: Request):
    """
    Menerima notifikasi pembayaran dari Xendit (Payment Requests API).
    WAJIB verifikasi X-CALLBACK-TOKEN sebelum apapun dilakukan.

    Payload Xendit (event payment.succeeded / payment.failed / payment.expired):
        {
          "event": "payment.succeeded",
          "data": {
            "id": "py-xxxx",            # payment id
            "status": "SUCCEEDED",
            "reference_id": "TYM-...",  # order_id kita
            "amount": 5000,
            ...
          }
        }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body bukan JSON valid")

    callback_token = request.headers.get("x-callback-token")

    # Log payload mentah SEBELUM validasi apapun — supaya apapun hasilnya
    # (diproses / ditolak token / diabaikan status), kita selalu tahu persis
    # apa yang Xendit kirim. Ini yang paling sering hilang saat debug: 200 OK
    # di ngrok TIDAK berarti webhook-nya diproses — cuma berarti HTTP-nya
    # sampai ke FastAPI. Baris log ini yang menentukan proses atau tidak.
    logger.info(
        f"[XENDIT-WEBHOOK] Payload masuk — event={body.get('event')} "
        f"status={(body.get('data') or {}).get('status')} "
        f"reference_id={(body.get('data') or {}).get('reference_id')} "
        f"token_header_ada={'ya' if callback_token else 'TIDAK ADA'}"
    )

    # ── 1. Verifikasi X-CALLBACK-TOKEN Xendit ──
    if not validate_xendit_webhook(callback_token, body):
        logger.warning(f"Webhook Xendit INVALID: {(body.get('data') or {}).get('reference_id')}")
        # Tetap return 200 agar Xendit tidak retry terus, tapi tidak proses
        return {"status": "ignored"}

    event      = body.get("event", "")
    data       = body.get("data", {}) or {}
    order_id   = data.get("reference_id", "")
    trx_status = data.get("status", "")
    payment_id = data.get("id", "")

    if not order_id:
        logger.warning("Webhook Xendit: reference_id kosong di payload")
        return {"status": "invalid_payload"}

    # ── 2. Ambil transaksi dari DB ──
    trx = get_transaction(order_id)
    if not trx:
        logger.warning(f"Webhook: order_id tidak ditemukan: {order_id}")
        return {"status": "order_not_found"}

    # ── 3. Idempotency check — jangan proses dua kali ──
    if trx["payment_status"] == "PAID":
        logger.info(f"Webhook: order {order_id} sudah PAID sebelumnya, skip")
        return {"status": "already_paid"}

    # ── 4. Tentukan status ──
    if trx_status in XENDIT_SUCCESS_STATUS:
        # ── PEMBAYARAN BERHASIL ──
        # Simpan sebagai PAID — DISPENSE belum dikirim ke ESP32.
        # ESP32 hanya akan dispense setelah user klik "Sudah Siap" di UI
        # (endpoint POST /api/payment/confirm-dispense).
        update_payment_status(order_id, "PAID",
                              gateway_trx_id=payment_id,
                              gateway_raw=body)

        # Broadcast ke UI — tampilkan halaman guide, JANGAN dispense dulu
        await ws_manager.broadcast(
            trx["machine_id"], "payment_confirmed",
            {
                "order_id":       order_id,
                "volume_liter":   trx["volume_requested"],
                "amount_paid":    trx["amount"],
                "payment_method": "qris",
                "session_id":     trx["session_id"],
                "dispense_sent":  False,   # belum — tunggu user konfirmasi
            }
        )
        logger.info(f"Payment PAID: {order_id} — menunggu konfirmasi user di guide page")

    elif trx_status in XENDIT_FAILED_STATUS:
        update_payment_status(order_id, "FAILED",
                              gateway_trx_id=payment_id,
                              gateway_raw=body)
        await ws_manager.broadcast(
            trx["machine_id"], "payment_failed",
            {"order_id": order_id, "reason": trx_status}
        )
        logger.info(f"Payment FAILED: {order_id} status={trx_status}")

    else:
        logger.info(f"Webhook Xendit: event={event} status={trx_status} order={order_id} (diabaikan, bukan status final)")

    # Selalu return 200 ke Xendit
    return {"status": "ok"}


@router.post("/confirm-dispense")
async def confirm_dispense(request: Request):
    """
    Dipanggil UI saat user klik tombol 'Sudah Siap — Mulai Isi Air'.
    Backend baru kirim MQTT DISPENSE ke ESP32 di sini.

    Flow:
      1. Xendit webhook → payment_confirmed WS event → UI tampilkan page-guide
      2. User klik tombol → POST /api/payment/confirm-dispense
      3. Backend kirim DISPENSE ke ESP32
      4. Backend broadcast dispense_started ke UI
      5. UI tampilkan page-filling dengan countdown realtime
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body bukan JSON valid")

    order_id = body.get("order_id", "").strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id wajib diisi")

    # Ambil transaksi dari DB
    trx = get_transaction(order_id)
    if not trx:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    # Hanya izinkan jika status PAID dan belum dispense
    if trx["payment_status"] != "PAID":
        raise HTTPException(
            status_code=400,
            detail=f"Transaksi belum PAID (status: {trx['payment_status']})"
        )
    if trx.get("dispense_status") == "DISPENSED":
        raise HTTPException(status_code=409, detail="Sudah di-dispense sebelumnya")

    # Hanya validasi — DISPENSE belum dikirim ke ESP32.
    # Frontend akan memanggil /start-dispense setelah countdown selesai.
    logger.info(f"Confirm guide: {order_id} vol={trx['volume_requested']}L — countdown dimulai di UI")
    return {
        "status":       "ok",
        "order_id":     order_id,
        "volume_liter": trx["volume_requested"],
        "message":      "Siap — mulai countdown di UI"
    }


@router.post("/start-dispense")
async def start_dispense(request: Request):
    """
    Dipanggil frontend setelah countdown 10 detik selesai.
    Baru di sini DISPENSE dikirim ke ESP32.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body bukan JSON valid")

    order_id = body.get("order_id", "").strip()
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id wajib diisi")

    trx = get_transaction(order_id)
    if not trx:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")

    if trx["payment_status"] != "PAID":
        raise HTTPException(status_code=400, detail=f"Status tidak valid: {trx['payment_status']}")

    if trx.get("dispense_status") == "DISPENSED":
        raise HTTPException(status_code=409, detail="Sudah di-dispense sebelumnya")

    # Sekarang baru kirim DISPENSE ke ESP32
    ok = publish_dispense_command(
        order_id     = order_id,
        session_id   = trx["session_id"],
        volume_liter = trx["volume_requested"],
        source       = "PAYMENT",
        machine_id   = trx["machine_id"],
    )

    if not ok:
        raise HTTPException(status_code=503, detail="Mesin tidak terhubung, coba lagi")

    # Broadcast ke UI — halaman filling sudah tampil, ini memulai animasi realtime
    await ws_manager.broadcast(
        trx["machine_id"], "dispense_started",
        {
            "order_id":      order_id,
            "session_id":    trx["session_id"],
            "target_liters": trx["volume_requested"],
            "source":        "PAYMENT",
        }
    )

    logger.info(f"Start dispense: {order_id} vol={trx['volume_requested']}L → ESP32")
    return {
        "status":       "ok",
        "order_id":     order_id,
        "volume_liter": trx["volume_requested"],
        "message":      "DISPENSE dikirim ke ESP32"
    }


# ─────────────────────────────────────────
# GET /api/payment/status/{order_id}
# ─────────────────────────────────────────

@router.get("/status/{order_id}")
async def get_payment_status(order_id: str):
    """
    Polling fallback jika WebSocket terputus.
    UI memanggil ini secara berkala untuk cek status.
    """
    trx = get_transaction(order_id)
    if not trx:
        raise HTTPException(status_code=404, detail="Order tidak ditemukan")

    # Jika masih PENDING, coba query langsung ke Xendit lewat payment_request_id
    # yang disimpan saat /create (ID ini beda dari order_id/reference_id kita).
    payment_request_id = trx.get("xendit_payment_request_id")
    if trx["payment_status"] == "PENDING" and payment_request_id:
        try:
            url = XENDIT_PAYMENT_REQUEST_STATUS_URL.format(payment_request_id=payment_request_id)
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=XENDIT_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                # Status pembayaran ada di payments[-1].status kalau sudah ada
                # yang bayar, atau data.status (mis. "REQUIRES_ACTION") kalau
                # belum. Lihat field "payments" (list) yang muncul setelah
                # QR di-scan dan dibayar.
                payments = data.get("payments") or []
                latest_status = payments[-1]["status"] if payments else data.get("status", "")
                payment_id    = payments[-1].get("id") if payments else data.get("id", "")

                if latest_status in XENDIT_SUCCESS_STATUS and trx["payment_status"] != "PAID":
                    update_payment_status(order_id, "PAID",
                                          gateway_trx_id=payment_id,
                                          gateway_raw=data)
                elif latest_status in XENDIT_FAILED_STATUS and trx["payment_status"] != "PAID":
                    update_payment_status(order_id, "FAILED",
                                          gateway_trx_id=payment_id,
                                          gateway_raw=data)
        except Exception as e:
            logger.warning(f"Xendit status check error: {e}")

    trx = get_transaction(order_id)  # re-fetch setelah potential update
    return {
        "order_id":       trx["order_id"],
        "payment_status": trx["payment_status"],
        "dispense_status": trx["dispense_status"],
        "amount":         trx["amount"],
        "paid_at":        trx["paid_at"],
    }
