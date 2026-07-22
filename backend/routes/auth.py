"""
routes/auth.py
Autentikasi admin dengan username + password (bcrypt)
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel, Field

from config.settings import JWT_EXPIRE_MIN, BCRYPT_ROUNDS
from middleware.auth import (
    hash_password, verify_password,
    create_admin_session, verify_admin_session, require_admin
)
from services.database import db_cursor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"])

# ─────────────────────────────────────────
# Models
# ─────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=16, description="Username admin")
    password: str = Field(..., min_length=1, max_length=16, description="Password admin")

class LoginResponse(BaseModel):
    token: str
    username: str
    name: str
    role: str
    expires_in: int

class ChangePasswordRequest(BaseModel):
    username: str = Field(..., description="Username yang akan diganti password-nya")
    old_password: str = Field(..., min_length=1, max_length=16)
    new_password: str = Field(..., min_length=1, max_length=16)

class AdminProfileResponse(BaseModel):
    username: str
    name: str
    role: str
    is_active: bool
    last_login: str = None

# ─────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────

@router.post("/auth/login", response_model=LoginResponse)
async def admin_login(req: LoginRequest):
    """Login dengan username dan password."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, name, password_hash, role, is_active FROM admins WHERE username = ?",
            (req.username,)
        )
        admin = cur.fetchone()

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah"
        )

    if not admin["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun dinonaktifkan"
        )

    if not admin["password_hash"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun belum memiliki password, hubungi admin"
        )

    if not verify_password(req.password, admin["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username atau password salah"
        )

    # Update last_login
    with db_cursor() as cur:
        cur.execute(
            "UPDATE admins SET last_login = CURRENT_TIMESTAMP WHERE username = ?",
            (req.username,)
        )

    user_data = {
        "username": admin["username"],
        "name": admin["name"],
        "role": admin["role"],
    }
    token = create_admin_session(user_data)

    return LoginResponse(
        token=token,
        username=admin["username"],
        name=admin["name"],
        role=admin["role"],
        expires_in=JWT_EXPIRE_MIN * 60,
    )

@router.post("/auth/logout")
async def admin_logout(admin: dict = Depends(require_admin)):
    """Logout (client cukup hapus token di sisi client)."""
    # Tidak ada server-side session, return success
    return {"success": True, "message": "Logout successful"}

@router.get("/auth/me", response_model=AdminProfileResponse)
async def get_admin_profile(admin: dict = Depends(require_admin)):
    """Get profil admin saat ini."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, name, role, is_active, last_login FROM admins WHERE username = ?",
            (admin["sub"],)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Admin tidak ditemukan")
    
    return AdminProfileResponse(
        username=row["username"],
        name=row["name"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        last_login=row["last_login"],
    )

@router.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, admin: dict = Depends(require_admin)):
    """Ganti password sendiri (hanya untuk admin yang login)."""
    if req.username != admin["sub"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tidak boleh mengubah password orang lain"
        )

    with db_cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM admins WHERE username = ?",
            (req.username,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Admin tidak ditemukan")

        if not row["password_hash"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Akun belum memiliki password, gunakan endpoint reset"
            )

        if not verify_password(req.old_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password lama salah"
            )

        new_hash = hash_password(req.new_password)
        cur.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (new_hash, req.username)
        )

    return {"success": True, "message": "Password berhasil diubah"}

@router.post("/auth/reset-password")
async def reset_password(req: dict, admin: dict = Depends(require_admin)):
    """
    Reset password admin (hanya super_admin yang boleh).
    Body: {"username": "admin", "new_password": "newpass123"}
    """
    # Cek role admin yang login
    if admin.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya super_admin yang bisa reset password"
        )

    target_username = req.get("username")
    new_password = req.get("new_password")
    if not target_username or not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username dan new_password wajib diisi"
        )
    if len(new_password) > 16:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password maksimal 16 karakter"
        )

    with db_cursor() as cur:
        cur.execute(
            "SELECT username FROM admins WHERE username = ?",
            (target_username,)
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Admin tidak ditemukan")

        new_hash = hash_password(new_password)
        cur.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (new_hash, target_username)
        )

    return {"success": True, "message": f"Password untuk {target_username} berhasil direset"}

@router.post("/auth/refresh")
async def refresh_admin_session(admin: dict = Depends(require_admin)):
    """
    Refresh admin session token.
    """
    with db_cursor() as cur:
        cur.execute(
            "SELECT username, name, role FROM admins WHERE username = ?",
            (admin["sub"],)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Admin tidak ditemukan")

    user_data = {
        "username": row["username"],
        "name": row["name"],
        "role": row["role"],
    }
    new_token = create_admin_session(user_data)
    return {
        "token": new_token,
        "expires_in": JWT_EXPIRE_MIN * 60,
    }

@router.get("/auth/check")
async def check_auth(request: Request):
    """
    Cek apakah user sudah login (dari header Authorization).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return {"authenticated": False}

    token = auth_header.replace("Bearer ", "")
    try:
        payload = verify_admin_session(token)
        return {
            "authenticated": True,
            "username": payload["sub"],
            "name": payload.get("name"),
            "role": payload.get("role"),
        }
    except HTTPException:
        return {"authenticated": False}