"""
routes/hardware.py
Endpoint informasi mesin dan panel admin.
GET  /api/machine/status      — status mesin terkini (dari cache) + settings + slides
GET  /api/admin/report/today  — laporan harian
POST /api/admin/config        — update konfigurasi mesin
POST /api/admin/command       — kirim perintah ke ESP32
POST /api/admin/verify-pin    — verifikasi PIN admin (dipakai kiosk)
"""
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional

from config.settings import (
    MACHINE_ID, DEFAULT_PRICE_PER_LITER,
    MIN_VOLUME_LITER, MAX_VOLUME_LITER
)
from middleware.auth import verify_admin_pin, hash_admin_pin
from services.database import (
    get_state_cache, get_machine, get_machine_config,
    set_machine_config, get_daily_report,
    get_machine_settings, get_signage_slides
)
from services.mqtt_bridge import publish_dispense_command, publish_stop_command

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Hardware & Admin"])


# ─────────────────────────────────────────
# GET /api/machine/status
# ─────────────────────────────────────────

@router.get("/api/machine/status")
async def machine_status(machine_id: str = MACHINE_ID):
    """
    Status mesin terkini dari cache MQTT + settings + signage slides.
    UI memanggil ini saat pertama load untuk inisialisasi tampilan.
    """
    cache  = get_state_cache(machine_id)
    config = get_machine_config(machine_id)

    # Base response
    response = {
        "machine_id":     machine_id,
        "online":         False,
        "state":          "UNKNOWN",
        "mode":           "RO",
        "last_seen":      None,
        "galon": {
            "g1_level_pct": 0, "g2_level_pct": 0,
            "g1_status": "UNKNOWN", "g2_status": "UNKNOWN",
            "total_available_liters": 0,
        },
        "price_per_liter": int(config.get("price_per_liter", DEFAULT_PRICE_PER_LITER)),
        "settings": config,
        "signage_slides": [],
    }

    if cache:
        response.update({
            "online":      bool(cache.get("online")),
            "state":       cache.get("state", "UNKNOWN"),
            "mode":        cache.get("mode", "RO"),
            "last_seen":   cache.get("last_seen"),
            "galon": {
                "g1_level_pct":          cache.get("g1_level_pct", 0),
                "g2_level_pct":          cache.get("g2_level_pct", 0),
                "g1_status":             cache.get("g1_status", "UNKNOWN"),
                "g2_status":             cache.get("g2_status", "UNKNOWN"),
                "active_galon":          cache.get("active_galon", 1),
                "total_available_liters": cache.get("total_available_liters", 0),
            },
            "price_per_liter": int(config.get("price_per_liter", DEFAULT_PRICE_PER_LITER)),
        })

    # Ambil settings (config sudah diambil di atas, tapi kita ambil ulang untuk konsistensi)
    settings = get_machine_settings(machine_id)
    response["settings"] = settings.get("config", config)

    # Ambil slides aktif
    slides = get_signage_slides(machine_id, active_only=True)
    base_url = "/media/signage/"
    response["signage_slides"] = [
        {
            "id": s["id"],
            "media_type": s["media_type"],
            "url": f"{base_url}{s['file_path']}",
            "caption": s.get("caption"),
            "order": s["slide_order"],
            "is_active": s["is_active"],
        }
        for s in slides
    ]

    return response


# ─────────────────────────────────────────
# GET /api/admin/report/today
# ─────────────────────────────────────────

@router.get("/api/admin/report/today")
async def admin_report_today(machine_id: str = MACHINE_ID, admin_pin: str = ""):
    """
    Laporan transaksi hari ini untuk panel admin kiosk.
    Membutuhkan PIN admin untuk akses.
    """
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")

    if admin_pin:
        if not verify_admin_pin(admin_pin, machine["admin_pin_hash"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PIN admin salah"
            )

    report = get_daily_report(machine_id)
    return report


# ─────────────────────────────────────────
# POST /api/admin/config
# ─────────────────────────────────────────

class AdminConfigRequest(BaseModel):
    machine_id: str = Field(default=MACHINE_ID)
    admin_pin:  str = Field(..., min_length=4, max_length=4)
    key:        str = Field(...)
    value:      str = Field(...)


ALLOWED_CONFIG_KEYS = {
    "price_per_liter",
    "slide_duration_ms",
    "standby_timeout_sec",
    "signage_enabled",
    "ticker_text",
}


@router.post("/api/admin/config")
async def update_config(req: AdminConfigRequest):
    """Update konfigurasi mesin dari panel admin."""
    machine = get_machine(req.machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")

    if not verify_admin_pin(req.admin_pin, machine["admin_pin_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN admin salah"
        )

    if req.key not in ALLOWED_CONFIG_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key tidak diizinkan: {req.key}"
        )

    set_machine_config(req.machine_id, req.key, req.value)
    logger.info(f"Config updated: {req.machine_id}.{req.key} = {req.value}")
    return {"success": True, "key": req.key, "value": req.value}


# ─────────────────────────────────────────
# POST /api/admin/pin
# ─────────────────────────────────────────

class ChangePinRequest(BaseModel):
    machine_id:  str = Field(default=MACHINE_ID)
    old_pin:     str = Field(..., min_length=4, max_length=4)
    new_pin:     str = Field(..., min_length=4, max_length=4)
    confirm_pin: str = Field(..., min_length=4, max_length=4)


@router.post("/api/admin/pin")
async def change_admin_pin(req: ChangePinRequest):
    """Ganti PIN admin via API (sinkron dengan DB)."""
    if req.new_pin != req.confirm_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Konfirmasi PIN tidak cocok"
        )

    from services.database import db_cursor
    with db_cursor() as cur:
        cur.execute(
            "SELECT admin_pin_hash FROM machines WHERE machine_id = ?",
            (req.machine_id,)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")

    if not verify_admin_pin(req.old_pin, row["admin_pin_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN lama salah"
        )

    new_hash = hash_admin_pin(req.new_pin)
    with db_cursor() as cur:
        cur.execute(
            "UPDATE machines SET admin_pin_hash = ? WHERE machine_id = ?",
            (new_hash, req.machine_id)
        )

    logger.info(f"Admin PIN changed for {req.machine_id}")
    return {"success": True, "message": "PIN admin berhasil diubah"}


# ─────────────────────────────────────────
# POST /api/admin/command
# ─────────────────────────────────────────

class AdminCommandRequest(BaseModel):
    machine_id:  str   = Field(default=MACHINE_ID)
    admin_pin:   str   = Field(..., min_length=4, max_length=4)
    cmd:         str   = Field(...)
    volume_liter: Optional[float] = Field(default=None)


@router.post("/api/admin/command")
async def send_admin_command(req: AdminCommandRequest):
    """
    Kirim perintah manual ke ESP32 dari panel admin.
    Cmd yang diizinkan: STOP, RESET, PING
    """
    machine = get_machine(req.machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")

    if not verify_admin_pin(req.admin_pin, machine["admin_pin_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN admin salah"
        )

    allowed_cmds = {"STOP", "RESET", "PING"}
    if req.cmd not in allowed_cmds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Perintah tidak diizinkan: {req.cmd}"
        )

    if req.cmd == "STOP":
        publish_stop_command(req.machine_id)
        return {"success": True, "cmd": "STOP", "message": "Perintah stop dikirim"}

    # Untuk RESET dan PING — publish via MQTT command topic
    from services.mqtt_bridge import _mqtt_client
    from middleware.auth import compute_command_hmac
    import json, time
    if _mqtt_client and _mqtt_client.is_connected():
        issued_at = int(time.time())
        payload = {
            "cmd":          req.cmd,
            "session_id":   "",
            "volume_liter": 0.0,
            "issued_at":    issued_at,
            "hmac":         compute_command_hmac(
                req.cmd, "", 0.0, issued_at, req.machine_id
            ),
        }
        _mqtt_client.publish(
            f"toyamas/{req.machine_id}/command",
            json.dumps(payload), qos=1
        )
        return {"success": True, "cmd": req.cmd}

    return {"success": False, "message": "MQTT tidak terhubung"}


# ─────────────────────────────────────────
# POST /api/admin/verify-pin
# ─────────────────────────────────────────

class VerifyPinRequest(BaseModel):
    machine_id: str = Field(default=MACHINE_ID)
    pin: str = Field(..., min_length=4, max_length=4)


@router.post("/api/admin/verify-pin")
async def verify_pin(req: VerifyPinRequest):
    """
    Validasi PIN admin mesin (dipanggil oleh kiosk).
    Digunakan untuk login admin di kiosk tanpa perlu PIN di frontend.
    """
    machine = get_machine(req.machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")
    if not verify_admin_pin(req.pin, machine["admin_pin_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN salah"
        )
    return {"success": True, "message": "PIN valid"}