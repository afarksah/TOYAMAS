#!/usr/bin/env python3
"""
generate_fake_tickets.py
Buat tiket dummy di tabel app_tickets untuk testing alur baru.
Jalankan: python generate_fake_tickets.py
"""

import sqlite3
import secrets
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "database" / "toyamas_local.db"

# Daftar volume yang tersedia (dalam ml)
VOLUME_OPTIONS = [250, 350, 500, 750, 1000, 1200]

def generate_ticket_code(suffix: str = None) -> str:
    """Buat ticket_code format TKT-{20 char acak}-{6 digit}"""
    if not suffix:
        suffix = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))
    random_part = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(20))
    return f"TKT-{random_part}-{suffix}"

def create_ticket(
    account_id: str,
    account_name: str,
    account_email: str,
    volume_ml: int,
    amount: int,
    suffix: str = None,
    expire_days: int = 30
) -> dict:
    ticket_code = generate_ticket_code(suffix)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
    return {
        "ticket_code": ticket_code,
        "account_id": account_id,
        "account_name": account_name,
        "account_email": account_email,
        "transaction_id": f"TRX-{secrets.token_hex(8).upper()}",
        "volume_ml": volume_ml,
        "amount": amount,
        "status": "ACTIVE",
        "expires_at": expires_at.isoformat()
    }

def generate_email_from_name(name: str) -> str:
    """Buat email dari nama: nama.lower().replace(' ', '.') + '@gmail.com'"""
    # Hilangkan karakter non-alfanumerik dan spasi, ganti spasi dengan titik
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    parts = clean.lower().split()
    if not parts:
        return "user@gmail.com"
    # jika nama panjang, ambil nama depan dan belakang
    if len(parts) >= 2:
        email = f"{parts[0]}.{parts[-1]}@gmail.com"
    else:
        email = f"{parts[0]}@gmail.com"
    return email

def main():
    parser = argparse.ArgumentParser(description="Generate fake tickets for testing")
    parser.add_argument("--suffix", default=None, help="6 digit suffix (misal MPH6GV), jika tidak diberikan akan random")
    parser.add_argument("--name", default=None, help="Nama pemilik (jika tidak diberikan, akan diminta interaktif)")
    parser.add_argument("--email", default=None, help="Email pemilik (jika tidak diberikan, akan dibuat otomatis dari nama)")
    parser.add_argument("--volume", type=int, choices=VOLUME_OPTIONS, help=f"Volume dalam ml, pilihan: {VOLUME_OPTIONS}")
    parser.add_argument("--price-per-liter", type=int, default=500, help="Harga per liter (default 500)")
    parser.add_argument("--amount", type=int, default=None, help="Total harga (override otomatis dari volume * price_per_liter)")
    parser.add_argument("--count", type=int, default=1, help="Jumlah tiket (default 1)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"❌ Database tidak ditemukan: {DB_PATH}")
        return

    # ── Interaktif jika argumen tidak lengkap ──
    if not args.name:
        args.name = input("Nama pemilik (contoh: Budi Santoso): ").strip()
        if not args.name:
            print("❌ Nama wajib diisi.")
            return

    if not args.volume:
        print("\nPilih volume air (ml):")
        for i, v in enumerate(VOLUME_OPTIONS, 1):
            print(f"  {i}. {v} ml")
        try:
            choice = int(input("Masukkan nomor pilihan (1-6): ").strip())
            if 1 <= choice <= len(VOLUME_OPTIONS):
                args.volume = VOLUME_OPTIONS[choice-1]
            else:
                print("❌ Pilihan tidak valid.")
                return
        except ValueError:
            print("❌ Input harus angka.")
            return

    # Buat email otomatis dari nama jika tidak diberikan
    if not args.email:
        args.email = generate_email_from_name(args.name)
        print(f"📧 Email otomatis: {args.email}")

    # Hitung amount jika tidak di-override
    if args.amount is None:
        price_per_liter = args.price_per_liter
        volume_liter = args.volume / 1000.0
        args.amount = int(volume_liter * price_per_liter)

    account_id = args.email  # kita pakai email sebagai account_id (seperti sebelumnya)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for i in range(args.count):
        suffix = args.suffix if args.suffix else None
        if args.count > 1 and suffix:
            # Jika banyak tiket, suffix perlu unik, tambahkan indeks
            suffix = f"{suffix}{i}" if len(suffix) + len(str(i)) <= 6 else suffix[:6-len(str(i))] + str(i)
            suffix = suffix.upper()

        ticket = create_ticket(
            account_id=account_id,
            account_name=args.name,
            account_email=args.email,
            volume_ml=args.volume,
            amount=args.amount,
            suffix=suffix
        )

        cur.execute("""
            INSERT INTO app_tickets (
                ticket_code, account_id, account_name, account_email,
                transaction_id, volume_ml, amount, status, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticket["ticket_code"],
            ticket["account_id"],
            ticket["account_name"],
            ticket["account_email"],
            ticket["transaction_id"],
            ticket["volume_ml"],
            ticket["amount"],
            ticket["status"],
            ticket["expires_at"]
        ))

        print(f"✅ Tiket dibuat: {ticket['ticket_code']} | {ticket['volume_ml']}ml | {ticket['account_name']}")

    conn.commit()
    conn.close()
    print(f"\n✨ Total {args.count} tiket berhasil ditambahkan.")
    print("🔑 Gunakan 6 digit terakhir (suffix) untuk input di kiosk.")

if __name__ == "__main__":
    main()