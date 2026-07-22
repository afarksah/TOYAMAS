"""
main.py
Entry point FastAPI — Toyamas Vending Dispenser Backend
"""
import asyncio
import logging
import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from config.settings import (
    DEBUG, APP_ENV, MACHINE_ID, CORS_ORIGINS, CORS_ORIGIN_REGEX,
    ORDER_PENDING_TIMEOUT_MIN
)
from services.database import (
    init_database, get_pending_transactions_old,
    update_payment_status, cleanup_old_sensor_logs,
    mark_unsynced_transactions
)
from services.mqtt_bridge import start_mqtt_client, stop_mqtt_client
from routes.payment   import router as payment_router
from routes.ticket    import router as ticket_router
from routes.hardware  import router as hardware_router
from routes.websocket import router as ws_router
from routes.auth import router as auth_router
from routes.iot import router as iot_router
from routes.iot_settings import router as iot_settings_router
from config.settings import BASE_DIR

logging.basicConfig(
    level   = logging.DEBUG if DEBUG else logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# Background Tasks
# ─────────────────────────────────────────

async def _cron_check_pending_orders():
    """Cron: cek order PENDING yang sudah terlalu lama."""
    import httpx
    from config.settings import XENDIT_PAYMENT_REQUEST_STATUS_URL, XENDIT_HEADERS, \
                                 XENDIT_SUCCESS_STATUS, XENDIT_FAILED_STATUS
    from services.mqtt_bridge import publish_dispense_command, ws_manager
    from services.database import get_transaction

    while True:
        await asyncio.sleep(300)
        try:
            stale = get_pending_transactions_old(ORDER_PENDING_TIMEOUT_MIN)
            for trx in stale:
                order_id = trx["order_id"]
                payment_request_id = trx.get("xendit_payment_request_id")
                if not payment_request_id:
                    # Belum sempat dapat payment_request_id dari Xendit
                    # (gagal total saat /create) — tidak ada yang bisa dicek.
                    continue

                logger.info(f"Cron: cek status pending order {order_id}")
                try:
                    url = XENDIT_PAYMENT_REQUEST_STATUS_URL.format(
                        payment_request_id=payment_request_id
                    )
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        resp = await client.get(url, headers=XENDIT_HEADERS)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    # Status pembayaran aktual muncul di payments[-1] setelah
                    # QR di-scan; data.status sendiri cuma status payment
                    # request-nya (mis. "REQUIRES_ACTION"), bukan hasil bayar.
                    payments = data.get("payments") or []
                    latest_status = payments[-1]["status"] if payments else data.get("status", "")
                    payment_id    = payments[-1].get("id") if payments else data.get("id", "")

                    if latest_status in XENDIT_SUCCESS_STATUS:
                        update_payment_status(order_id, "PAID",
                                              gateway_trx_id=payment_id, gateway_raw=data)
                        publish_dispense_command(
                            trx["order_id"], trx["session_id"],
                            trx["volume_requested"], "PAYMENT", trx["machine_id"]
                        )
                        await ws_manager.broadcast(
                            trx["machine_id"], "payment_confirmed",
                            {"order_id": order_id, "volume_liter": trx["volume_requested"]}
                        )
                    elif latest_status in XENDIT_FAILED_STATUS:
                        update_payment_status(order_id, "EXPIRED",
                                              gateway_trx_id=payment_id, gateway_raw=data)
                        await ws_manager.broadcast(
                            trx["machine_id"], "payment_failed",
                            {"order_id": order_id, "reason": "expired"}
                        )
                except Exception as e:
                    logger.error(f"Cron check order {order_id} error: {e}")
        except Exception as e:
            logger.error(f"Cron pending orders error: {e}")


async def _cron_cleanup():
    """Cron: cleanup data lama dari DB."""
    while True:
        await asyncio.sleep(86400)
        try:
            cleanup_old_sensor_logs(days=7)
            from services.database import cleanup_expired_sessions
            cleanup_expired_sessions()
            logger.info("Daily cleanup done")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


async def _cron_sync_to_cloud():
    """Cron: sinkronkan transaksi selesai ke Cloudflare D1."""
    from config.settings import CF_API_TOKEN, CF_WORKER_URL
    import httpx

    while True:
        await asyncio.sleep(600)
        if not CF_API_TOKEN:
            continue
        try:
            rows = mark_unsynced_transactions()
            if not rows:
                continue

            payload = [
                {
                    "order_id":       r["order_id"],
                    "machine_id":     r["machine_id"],
                    "source":         r["source"],
                    "ticket_code":    r["ticket_code"],
                    "volume_requested": r["volume_requested"],
                    "volume_actual":  r["volume_actual"],
                    "amount":         r["amount"],
                    "payment_method": r["payment_method"],
                    "payment_status": r["payment_status"],
                    "dispense_status":r["dispense_status"],
                    "created_at":     r["created_at"],
                }
                for r in rows
            ]

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{CF_WORKER_URL}/api/sync/transactions",
                    json    = {"transactions": payload},
                    headers = {"Authorization": f"Bearer {CF_API_TOKEN}"}
                )

            if resp.status_code == 200:
                from services.database import mark_synced
                mark_synced([r["order_id"] for r in rows])
                logger.info(f"Synced {len(rows)} transactions to cloud")
        except Exception as e:
            logger.error(f"Cloud sync error: {e}")


# ─────────────────────────────────────────
# Lifespan (startup + shutdown)
# ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Toyamas Backend starting — machine={MACHINE_ID} env={APP_ENV}")

    init_database()

    loop = asyncio.get_event_loop()
    start_mqtt_client(loop)

    asyncio.create_task(_cron_check_pending_orders())
    asyncio.create_task(_cron_cleanup())
    asyncio.create_task(_cron_sync_to_cloud())

    logger.info("Backend ready ✓")
    yield

    stop_mqtt_client()
    logger.info("Backend shutdown selesai")


# ─────────────────────────────────────────
# App Instance
# ─────────────────────────────────────────

app = FastAPI(
    title       = "Toyamas Dispenser API",
    description = "Backend API untuk mesin vending dispenser air Toyamas",
    version     = "1.0.0",
    debug       = DEBUG,
    lifespan    = lifespan,
    docs_url    = "/docs" if DEBUG else None,
    redoc_url   = None,
)


# ─────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins      = CORS_ORIGINS,
    allow_origin_regex = CORS_ORIGIN_REGEX,
    allow_credentials  = True,
    allow_methods      = ["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers      = ["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 1)
    logger.debug(
        f"{request.method} {request.url.path} "
        f"→ {response.status_code} ({duration}ms)"
    )
    return response


# ─────────────────────────────────────────
# ─── ROUTERS (HARUS DI ATAS STATIC FILES) ───
# ─────────────────────────────────────────

app.include_router(payment_router)
app.include_router(ticket_router)
app.include_router(hardware_router)
app.include_router(ws_router)
app.include_router(auth_router)      # ⚠️ HARUS sebelum StaticFiles
app.include_router(iot_router)       # ⚠️ HARUS sebelum StaticFiles
app.include_router(iot_settings_router)  # ⚠️ HARUS sebelum StaticFiles


# ─────────────────────────────────────────
# ─── SERVE STATIC FILES ───
# ─────────────────────────────────────────

# === 1. IOT DASHBOARD ===
IOT_DIR = "iot"
if os.path.isdir(IOT_DIR):
    app.mount("/iot", StaticFiles(directory=IOT_DIR, html=True), name="iot")
    
    @app.get("/iot-dashboard", include_in_schema=False)
    async def serve_iot_dashboard():
        index_path = os.path.join(IOT_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=404, content={"error": "IoT Dashboard not found"})
    
    logger.info("IoT Dashboard served at /iot-dashboard")
else:
    logger.warning("Folder 'iot' tidak ditemukan")


# === 2. SIGNAGE MEDIA FILES (uploads) ===
# ⚠️ HARUS di-mount SEBELUM SPA fallback kiosk di bawah — Starlette mencocokkan
# route berdasarkan urutan registrasi, jadi kalau '/{ui_path:path}' didaftarkan
# lebih dulu, ia akan "menangkap" request /media/signage/... duluan (dan skip_prefixes
# di bawah cuma bikin 404 sendiri, bukan lanjut ke mount ini).
UPLOAD_DIR = str(BASE_DIR / "uploads" / "signage")
# Buat folder jika belum ada
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if os.name == 'posix':
        os.chmod(UPLOAD_DIR, 0o755)
    logger.info(f"Created signage upload directory: {UPLOAD_DIR}")

app.mount("/media/signage", StaticFiles(directory=UPLOAD_DIR), name="signage")
logger.info(f"Signage media served from /media/signage (folder: {UPLOAD_DIR})")


# === 3. FRONTEND KIOSK ===
FRONTEND_DIR = "frontend"

# ─────────────────────────────────────────
# Health check — HARUS didaftarkan SEBELUM catch-all '/{ui_path:path}'
# di bawah, karena FastAPI mencocokkan route berdasar urutan registrasi.
# Sebelumnya /health ada di bawah catch-all sehingga selalu ketangkap
# duluan oleh serve_kiosk_spa() dan balas 404.
# ─────────────────────────────────────────

@app.get("/health")
async def health():
    from services.mqtt_bridge import _mqtt_client
    return {
        "status":     "ok",
        "machine_id": MACHINE_ID,
        "mqtt":       _mqtt_client.is_connected() if _mqtt_client else False,
        "env":        APP_ENV,
    }

if os.path.isdir(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    
    @app.get("/", include_in_schema=False)
    async def serve_kiosk_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    
    # ⚠️ SPA Fallback — HARUS PALING BAWAH, setelah semua router dan static files
    @app.get("/{ui_path:path}", include_in_schema=False)
    async def serve_kiosk_spa(ui_path: str):
        """SPA fallback untuk frontend kiosk."""
        # Skip jika path sudah ditangani router lain
        skip_prefixes = ("api/", "ws/", "auth/", "iot-dashboard", "iot/", "health", "docs", "frontend/", "static/", "media/")
        if ui_path.startswith(skip_prefixes):
            raise HTTPException(status_code=404)
        
        file_path = os.path.join(FRONTEND_DIR, ui_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    
    logger.info("Frontend Kiosk served at /")
else:
    logger.warning("Folder 'frontend' tidak ditemukan")


# ─────────────────────────────────────────
# Error handlers
# ─────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return JSONResponse(status_code=404,
                        content={"error": "Endpoint tidak ditemukan"})


@app.exception_handler(500)
async def server_error(request: Request, exc):
    logger.error(f"Internal error: {exc}")
    return JSONResponse(status_code=500,
                        content={"error": "Internal server error"})