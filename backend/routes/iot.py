"""
routes/iot.py
IoT Dashboard API — Data untuk monitoring mesin
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field

from config.settings import IOT_TRANSACTIONS_PER_PAGE
from middleware.auth import require_admin, hash_admin_pin
from services.database import (
    get_iot_dashboard_data,
    get_iot_chart_data,
    get_transactions_filtered,
    get_sales_summary,
    get_all_machines_locations,
    get_machine_location,
    get_all_machines_status,
    get_machine_online_status,
    list_machines,
    create_machine,
    get_machine,
    get_machine_secret,
    soft_delete_machine,
    get_app_config,
    set_app_config,
    apply_global_default_to_all_machines,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/iot", tags=["IoT Dashboard"])


# ─────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────

@router.get("/dashboard")
async def get_dashboard(
    machine_id: str = Query(None, regex="^[A-Za-z0-9_-]+$", description="Filter spesifik machine_id"),
    admin: dict = Depends(require_admin)
):
    """
    Get semua data dashboard dalam satu panggilan.
    """
    data = get_iot_dashboard_data(machine_id)
    return data


@router.get("/machines")
async def get_machines(admin: dict = Depends(require_admin)):
    """
    Get daftar semua mesin dengan status terbaru.
    """
    machines = get_all_machines_status()
    return {"machines": machines}


class CreateMachineRequest(BaseModel):
    machine_id:      str = Field(..., min_length=1, max_length=32,
                                  description="Contoh: TYM-002")
    name:            str = Field(..., min_length=1, max_length=100)
    admin_pin:       str = Field(..., min_length=4, max_length=4,
                                  description="PIN admin 4 digit untuk mesin ini")
    location:        str = Field(None, max_length=200)
    price_per_liter: int = Field(500, ge=1)
    mode:            str = Field("RO", pattern="^(RO|MANUAL)$")
    secret:          str = Field(
        None, min_length=16, max_length=128,
        description=(
            "HMAC secret khusus mesin ini. Kosongkan untuk di-generate "
            "otomatis (direkomendasikan — jangan pakai secret yang sama "
            "untuk banyak mesin)."
        )
    )


@router.post("/machines", status_code=status.HTTP_201_CREATED)
async def register_machine(
    req: CreateMachineRequest,
    admin: dict = Depends(require_admin)
):
    """
    Daftarkan mesin baru ke armada (mis. TYM-002, TYM-003, ...).

    Ini menggantikan cara lama (INSERT manual ke SQLite lewat seed SQL) —
    setelah dipanggil, mesin langsung muncul di `/api/iot/machines` dan di
    dashboard IoT (statusnya OFFLINE/UNKNOWN sampai ESP32 fisiknya pertama
    kali mengirim status MQTT ke topic toyamas/{machine_id}/status).

    Catatan: mendaftarkan mesin di sini TIDAK otomatis mem-flash ESP32 —
    firmware unit tersebut tetap harus di-build dengan MACHINE_ID dan
    TOPIC_* yang SAMA PERSIS dengan machine_id yang didaftarkan di sini.

    `secret` dalam response HANYA muncul di sini — salin ke `MACHINE_SECRET`
    di firmware unit ini SEBELUM di-flash. Kalau lupa dicatat, secret masih
    bisa dilihat lagi lewat GET /api/iot/machines/{machine_id}/secret
    (perlu admin login), tapi lebih aman langsung dicatat sekarang.
    """
    try:
        machine = create_machine(
            machine_id=req.machine_id,
            name=req.name,
            admin_pin_hash=hash_admin_pin(req.admin_pin),
            location=req.location,
            price_per_liter=req.price_per_liter,
            mode=req.mode,
            secret=req.secret,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    return {
        "success": True,
        "machine": machine,
        "note": (
            f"Salin nilai 'secret' di atas ke firmware unit {req.machine_id} "
            f"sebagai MACHINE_SECRET sebelum di-flash. Nilai ini beda dari "
            f"MACHINE_SECRET di .env backend (yang sekarang cuma jadi "
            f"fallback untuk mesin lama)."
        ),
    }


@router.get("/machines/{machine_id}/secret")
async def get_machine_secret_endpoint(
    machine_id: str,
    admin: dict = Depends(require_admin)
):
    """
    Lihat ulang HMAC secret mesin tertentu — dipakai kalau secret dari
    respons POST /machines lupa dicatat, atau untuk reflash firmware unit
    yang sudah lama terdaftar. Perlu login admin.
    """
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"machine_id '{machine_id}' tidak ditemukan")

    return {
        "machine_id": machine_id,
        "secret": get_machine_secret(machine_id),
    }


@router.delete("/machines/{machine_id}")
async def delete_machine_endpoint(
    machine_id: str,
    admin: dict = Depends(require_admin)
):
    """
    Hapus mesin dari armada (dipanggil dari tombol "Hapus" di menu Location).

    Ini SOFT DELETE, bukan hapus fisik baris/riwayat transaksi: mesin cuma
    ditandai `is_active = 0` supaya langsung hilang dari GET /machines,
    dropdown lokasi, dan peta. Riwayat transaksi/laporan lama yang sudah
    menunjuk ke machine_id ini tetap tampil apa adanya di halaman Laporan,
    tanpa perlu bisa diklik balik ke detail mesin.

    machine_id yang sudah dihapus tidak bisa dipakai ulang untuk mesin
    baru (create_machine menolak machine_id yang masih ada baris-nya,
    aktif ataupun tidak).
    """
    machine = get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                             detail=f"machine_id '{machine_id}' tidak ditemukan")

    if not machine.get("is_active", 1):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                             detail=f"machine_id '{machine_id}' sudah dihapus sebelumnya")

    soft_delete_machine(machine_id)
    logger.info(f"Machine {machine_id} soft-deleted by admin {admin.get('email', admin)}")

    return {
        "success": True,
        "message": f"Mesin {machine_id} berhasil dihapus dari daftar aktif",
    }


@router.get("/machines/{machine_id}/status")
async def get_machine_status(
    machine_id: str,
    admin: dict = Depends(require_admin)
):
    """
    Get status spesifik mesin.
    """
    return get_machine_online_status(machine_id)


# ─────────────────────────────────────────
# Charts
# ─────────────────────────────────────────

@router.get("/charts")
async def get_charts(
    machine_id: str = Query(None, regex="^[A-Za-z0-9_-]+$"),
    chart_type: str = Query("hourly", regex="^(hourly|weekly|monthly)$"),
    admin: dict = Depends(require_admin)
):
    """
    Get data grafik.
    chart_type: hourly | weekly | monthly
    """
    data = get_iot_chart_data(machine_id, chart_type)
    return data


# ─────────────────────────────────────────
# Transactions
# ─────────────────────────────────────────

@router.get("/transactions")
async def get_transactions(
    machine_id: str = Query(None, regex="^[A-Za-z0-9_-]+$"),
    start_date: str = Query(None),
    end_date: str = Query(None),
    status: str = Query(None),
    source: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(IOT_TRANSACTIONS_PER_PAGE, ge=1, le=100),
    admin: dict = Depends(require_admin)
):
    """
    Get riwayat transaksi dengan filter dan pagination.
    """
    offset = (page - 1) * limit

    transactions, total = get_transactions_filtered(
        machine_id=machine_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        source=source,
        limit=limit,
        offset=offset
    )

    return {
        "transactions": transactions,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }
    }


# ─────────────────────────────────────────
# Summary
# ─────────────────────────────────────────

@router.get("/summary")
async def get_summary(
    machine_id: str = Query(None, regex="^[A-Za-z0-9_-]+$"),
    period: str = Query("today", regex="^(today|week|month)$"),
    admin: dict = Depends(require_admin)
):
    """
    Get ringkasan penjualan.
    period: today | week | month
    """
    data = get_sales_summary(machine_id, period)
    return data


# ─────────────────────────────────────────
# Locations
# ─────────────────────────────────────────

@router.get("/locations")
async def get_locations(admin: dict = Depends(require_admin)):
    """
    Get lokasi semua mesin.
    """
    locations = get_all_machines_locations()
    return {"locations": locations}


@router.get("/locations/{machine_id}")
async def get_location(
    machine_id: str,
    admin: dict = Depends(require_admin)
):
    """
    Get lokasi spesifik mesin.
    """
    location = get_machine_location(machine_id)
    if not location:
        return {"error": "Machine not found"}
    return location


@router.post("/locations/{machine_id}")
async def update_location(
    machine_id: str,
    lat: float = Query(...),
    lng: float = Query(...),
    address: str = Query(None),
    admin: dict = Depends(require_admin)
):
    """
    Update lokasi mesin secara manual (admin).
    """
    from services.database import update_machine_location
    update_machine_location(
        machine_id=machine_id,
        lat=lat,
        lng=lng,
        address=address,
        source="admin_manual"
    )
    return {"success": True, "message": "Location updated"}

# ─────────────────────────────────────────
# Global Settings
# ─────────────────────────────────────────

class GlobalSettingsRequest(BaseModel):
    default_price: Optional[int] = Field(None, ge=1)
    default_mode: Optional[str] = Field(None, pattern="^(RO|MANUAL)$")

@router.get("/global/settings")
async def get_global_settings(admin: dict = Depends(require_admin)):
    """Ambil pengaturan global (default price, default mode)."""
    from services.database import get_app_config
    return {
        "default_price": int(get_app_config("default_price", "500")),
        "default_mode": get_app_config("default_mode", "RO"),
    }

@router.post("/global/settings")
async def update_global_settings(req: GlobalSettingsRequest, admin: dict = Depends(require_admin)):
    """
    Update pengaturan global.
    - default_price: akan diterapkan ke semua mesin aktif (sinkron).
    - default_mode: akan diterapkan ke semua mesin aktif (sinkron).
    """
    from services.database import set_app_config, apply_global_default_to_all_machines
    updates = req.dict(exclude_none=True)
    if not updates:
        return {"message": "Tidak ada perubahan"}
    
    affected = 0
    for key, value in updates.items():
        # Simpan ke app_config
        set_app_config(key, str(value))
        # Terapkan ke semua mesin
        affected += apply_global_default_to_all_machines(key, str(value))
    
    return {
        "success": True,
        "affected_machines": affected,
        "updated": updates
    }