"""
routes/iot_settings.py
Endpoint untuk mengelola pengaturan mesin dari IoT Dashboard (admin).
"""
import os
import shutil
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel, Field

from config.settings import BASE_DIR
from middleware.auth import require_admin, hash_admin_pin, verify_admin_pin
from services.database import (
    get_machine,
    get_machine_settings,
    update_machine_settings,
    get_signage_slides,
    add_signage_slide,
    update_signage_slide,
    delete_signage_slide,
    get_signage_slide,
    get_machine_config,
    db_cursor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/iot/settings", tags=["IoT Settings"])

# Folder untuk menyimpan file signage
SIGNAGE_UPLOAD_DIR = BASE_DIR / "uploads" / "signage"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
ALLOWED_VIDEO_TYPES = {"video/mp4"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024 # 100 MB

# ─────────────────────────────────────────
# Models
# ─────────────────────────────────────────

class SettingsUpdateRequest(BaseModel):
    price_per_liter: Optional[int] = Field(None, ge=1)
    standby_timeout_sec: Optional[int] = Field(None, ge=10, le=300)
    slide_duration_ms: Optional[int] = Field(None, ge=1000, le=60000)
    signage_enabled: Optional[int] = Field(None, ge=0, le=1)
    mode: Optional[str] = Field(None, pattern="^(RO|MANUAL)$")  # BARU

class PinChangeRequest(BaseModel):
    old_pin: str = Field(..., min_length=4, max_length=4)
    new_pin: str = Field(..., min_length=4, max_length=4)
    confirm_pin: str = Field(..., min_length=4, max_length=4)

# ─────────────────────────────────────────
# Helper: simpan file upload
# ─────────────────────────────────────────

def _save_upload_file(machine_id: str, file: UploadFile) -> str:
    """Simpan file ke disk, return path relatif terhadap uploads/signage."""
    import uuid
    # Tentukan ekstensi
    ext = Path(file.filename).suffix.lower()
    if not ext:
        ext = ".jpg"  # fallback
    # Buat nama unik
    filename = f"{uuid.uuid4().hex}{ext}"
    machine_dir = SIGNAGE_UPLOAD_DIR / machine_id
    machine_dir.mkdir(parents=True, exist_ok=True)
    file_path = machine_dir / filename
    # Tulis file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # Return path relatif
    return f"{machine_id}/{filename}"

def _delete_file(rel_path: str) -> bool:
    """Hapus file fisik berdasarkan path relatif."""
    full_path = SIGNAGE_UPLOAD_DIR / rel_path
    if full_path.exists():
        full_path.unlink()
        return True
    return False

# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────

@router.get("/{machine_id}")
async def get_settings(machine_id: str, admin: dict = Depends(require_admin)):
    """Ambil semua pengaturan + slide untuk satu mesin."""
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")
    data = get_machine_settings(machine_id)
    # Tambahkan info dasar mesin
    data["machine"] = {
        "machine_id": machine_id,
        "name": machine.get("name"),
        "mode": machine.get("mode"),
    }
    # Tambahkan mode ke config juga agar mudah di form
    data["config"]["mode"] = machine.get("mode")
    return data

@router.post("/{machine_id}")
async def update_settings(machine_id: str, req: SettingsUpdateRequest, admin: dict = Depends(require_admin)):
    """Update satu atau lebih config."""
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")
    # Filter hanya field yang dikirim
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        return {"message": "Tidak ada perubahan"}
    # Pisahkan mode (update tabel machines) dan sisanya (machine_config)
    mode = updates.pop("mode", None)
    mode_command_sent = None  # None = tidak diminta, True/False = hasil publish
    if mode:
        from services.mqtt_bridge import publish_set_mode_command
        # PERBAIKAN: sebelumnya kolom `mode` di DB langsung ditulis dan endpoint
        # selalu membalas success:true TANPA mengecek apakah perintah SET_MODE
        # benar-benar terkirim ke broker MQTT. Akibatnya kalau MQTT client
        # backend disconnect (atau publish gagal), dashboard tetap bilang
        # "berhasil" padahal ESP32 tidak pernah menerima perintahnya, dan DB
        # jadi menyimpan mode yang tidak sesuai kondisi mesin sebenarnya.
        # Sekarang: publish dulu, DB hanya di-update kalau publish sukses.
        mode_command_sent = publish_set_mode_command(machine_id, mode)
        if mode_command_sent:
            with db_cursor() as cur:
                cur.execute("UPDATE machines SET mode = ? WHERE machine_id = ?", (mode, machine_id))
        else:
            logger.error(
                f"SET_MODE gagal terkirim untuk {machine_id} (mode={mode}) — "
                f"MQTT client tidak terhubung atau publish gagal. DB tidak diubah."
            )

    # Update config lainnya
    if updates:
        new_config = update_machine_settings(machine_id, updates)
    else:
        new_config = get_machine_config(machine_id)

    # Ambil ulang data mesin untuk mendapatkan mode terbaru (bisa jadi masih
    # mode lama kalau publish di atas gagal)
    machine_updated = get_machine(machine_id)

    # Kalau mode diminta tapi gagal terkirim, dan tidak ada perubahan config
    # lain, laporkan sebagai error yang jelas ke dashboard — jangan bohong.
    if mode and not mode_command_sent and not updates:
        raise HTTPException(
            status_code=503,
            detail=(
                "Perintah ganti mode gagal dikirim ke mesin (MQTT tidak terhubung). "
                "Mode TIDAK berubah. Coba lagi, atau cek koneksi mesin/broker."
            ),
        )

    # Broadcast ke kiosk via WebSocket
    from services.mqtt_bridge import broadcast_config_update
    broadcast_config_update(machine_id)

    result = {
        "success": True,
        "config": new_config,
        "mode": machine_updated.get("mode") if machine_updated else mode,
    }
    if mode and not mode_command_sent:
        # Ada perubahan config lain yang sukses, tapi mode-nya gagal terkirim.
        result["success"] = False
        result["mode_warning"] = (
            "Perintah ganti mode gagal dikirim ke mesin (MQTT tidak terhubung). "
            "Mode TIDAK berubah dari sebelumnya."
        )
    return result

@router.post("/{machine_id}/pin")
async def change_machine_pin(machine_id: str, req: PinChangeRequest, admin: dict = Depends(require_admin)):
    """Ganti PIN admin mesin."""
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")
    if req.new_pin != req.confirm_pin:
        raise HTTPException(status_code=400, detail="Konfirmasi PIN tidak cocok")
    # Verifikasi PIN lama
    if not verify_admin_pin(req.old_pin, machine["admin_pin_hash"]):
        raise HTTPException(status_code=403, detail="PIN lama salah")
    new_hash = hash_admin_pin(req.new_pin)
    with db_cursor() as cur:
        cur.execute("UPDATE machines SET admin_pin_hash = ? WHERE machine_id = ?", (new_hash, machine_id))
    return {"success": True, "message": "PIN berhasil diubah"}

@router.post("/{machine_id}/signage")
async def upload_signage(
    machine_id: str,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    order: Optional[int] = Form(None),
    admin: dict = Depends(require_admin),
):
    """Upload slide baru (gambar/video)."""
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan")
    # Validasi tipe dan ukuran
    content_type = file.content_type or ""
    if content_type in ALLOWED_IMAGE_TYPES:
        media_type = "image"
        if file.size > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"Ukuran gambar maksimal {MAX_IMAGE_SIZE//1024//1024}MB")
    elif content_type in ALLOWED_VIDEO_TYPES:
        media_type = "video"
        if file.size > MAX_VIDEO_SIZE:
            raise HTTPException(status_code=400, detail=f"Ukuran video maksimal {MAX_VIDEO_SIZE//1024//1024}MB")
    else:
        raise HTTPException(status_code=400, detail="Tipe file tidak didukung. Gunakan JPG/PNG atau MP4.")

    # Simpan file
    rel_path = _save_upload_file(machine_id, file)
    slide_id = add_signage_slide(machine_id, media_type, rel_path, caption, order)
    logger.info(f"Signage file saved: {rel_path} (size: {file.size} bytes)")
    # Broadcast ke kiosk
    from services.mqtt_bridge import broadcast_signage_update
    broadcast_signage_update(machine_id)
    return {
        "success": True,
        "slide_id": slide_id,
        "file_path": rel_path,
        "media_type": media_type,
        "caption": caption,
        "order": order,
    }

@router.patch("/{machine_id}/signage/{slide_id}")
async def update_slide(
    machine_id: str,
    slide_id: int,
    req: dict,  # bisa {slide_order} atau {is_active}
    admin: dict = Depends(require_admin),
):
    """Update order atau status aktif slide."""
    slide = get_signage_slide(slide_id)
    if not slide or slide["machine_id"] != machine_id:
        raise HTTPException(status_code=404, detail="Slide tidak ditemukan")
    # Validasi field yang diizinkan
    allowed_fields = {"slide_order", "is_active"}
    updates = {k: v for k, v in req.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=400, detail="Tidak ada field yang diupdate")
    # Konversi is_active ke int
    if "is_active" in updates:
        updates["is_active"] = int(updates["is_active"])
    success = update_signage_slide(slide_id, **updates)
    if not success:
        raise HTTPException(status_code=500, detail="Gagal update slide")
    # Broadcast
    from services.mqtt_bridge import broadcast_signage_update
    broadcast_signage_update(machine_id)
    return {"success": True}

@router.delete("/{machine_id}/signage/{slide_id}")
async def delete_slide(machine_id: str, slide_id: int, admin: dict = Depends(require_admin)):
    """Hapus slide (termasuk file fisik)."""
    slide = get_signage_slide(slide_id)
    if not slide or slide["machine_id"] != machine_id:
        raise HTTPException(status_code=404, detail="Slide tidak ditemukan")
    # Hapus file
    _delete_file(slide["file_path"])
    # Hapus dari database
    delete_signage_slide(slide_id)
    # Broadcast
    from services.mqtt_bridge import broadcast_signage_update
    broadcast_signage_update(machine_id)
    return {"success": True}