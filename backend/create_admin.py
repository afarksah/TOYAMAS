"""
create_admin.py
Buat/update akun admin pertama untuk dashboard IoT (username + password)
Jalankan: python create_admin.py
"""
import bcrypt
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "database" / "toyamas_local.db"

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def main():
    if not DB_PATH.exists():
        print(f"❌ Database tidak ditemukan: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Cek apakah tabel admins ada
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'")
    if not cur.fetchone():
        print("❌ Tabel admins belum ada. Jalankan migration dulu (restart server).")
        conn.close()
        return

    # Cek apakah admin dengan username 'admin' sudah ada
    cur.execute("SELECT username, password_hash FROM admins WHERE username = 'admin'")
    row = cur.fetchone()
    if not row:
        # Insert admin baru
        hashed = hash_password("toyamas123")
        cur.execute("""
            INSERT INTO admins (username, name, password_hash, role, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, ("admin", "Administrator", hashed, "super_admin", 1))
        print("✅ Admin 'admin' berhasil dibuat dengan password 'toyamas123'.")
    else:
        if row[1] is None:
            # Update password_hash jika masih NULL
            hashed = hash_password("toyamas123")
            cur.execute("UPDATE admins SET password_hash = ? WHERE username = 'admin'", (hashed,))
            print("✅ Password admin 'admin' di-set ke 'toyamas123'.")
        else:
            print("✅ Admin 'admin' sudah memiliki password. Lewati.")

    conn.commit()
    conn.close()
    print("⚠️  Segera ganti password setelah login pertama!")

if __name__ == "__main__":
    main()