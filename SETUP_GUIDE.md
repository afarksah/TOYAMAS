# TOYAMAS — Panduan Instalasi & Penggunaan Lengkap
**Diperbarui:** 17 Juli 2026 — backend v4.7.6.2 + firmware `toyamas_firmware_v1_4_3_http_ota.ino` (`1.4.3-http-ota`)

---

## 1. Struktur Proyek

```
toyamas-dispenser-v4.7.6.2/
├── backend/
│   ├── main.py                 ← entry point FastAPI
│   ├── create_admin.py         ← buat/reset akun admin pertama (§3.3)
│   ├── midtrans_webhook_sim.py ← simulasi webhook pembayaran (§4)
│   ├── .env                    ← config rahasia (JANGAN commit ke Git)
│   ├── config/settings.py      ← semua konfigurasi terpusat
│   ├── middleware/auth.py      ← bcrypt (admin), JWT, HMAC ESP32↔backend, verifikasi Midtrans
│   ├── services/
│   │   ├── database.py         ← semua query SQLite + migration runner
│   │   └── mqtt_bridge.py      ← klien MQTT (subscribe semua mesin), publish command ke ESP32
│   ├── routes/                 ← auth.py, iot.py, iot_settings.py, payment.py, ticket.py, hardware.py, websocket.py
│   ├── database/
│   │   └── toyamas_local.db    ← file SQLite (dibuat otomatis)
│   ├── uploads/signage/        ← file media slide kiosk (disajikan di /media/signage)
│   ├── frontend/                ← UI KIOSK (disajikan di "/")
│   └── iot/                     ← UI DASHBOARD ADMIN (disajikan di "/iot-dashboard")
├── database/
│   ├── 001_init.sql
│   ├── schema_cloudflare_d1.sql
│   └── migrations/              ← 002–009, dijalankan otomatis & berurutan tiap startup
├── toyamas_mqtt_simulator_Mesin.py  ← simulator MQTT multi-mesin tanpa hardware (§3.7)
├── requirements.txt              ← HANYA di root ini, TIDAK ada salinan di dalam backend/
├── PAYLOAD_SPEC.md              ← spesifikasi lengkap semua format data
└── SETUP_GUIDE.md               ← dokumen ini
```

Lihat `struktur_folder.txt` untuk daftar file lengkap. Firmware ESP32 disimpan terpisah dari repo backend ini — flash manual lewat Arduino IDE (§5), atau update wireless lewat OTA (lihat `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md` untuk 4 metode lengkap) setelah firmware pertama kali ter-flash.

---

## 2. Prasyarat

- **Python 3.11+** dan `pip`
- **Arduino IDE** + **ESP32 Core 3.x** (IDF v5.x)
- Library Arduino: `PubSubClient` 2.8+, `ArduinoJson` 7.x, `ezButton` 1.0+ (via Library Manager). `WiFi`, `WiFiClient`, `WebServer`, `Update` sudah bawaan ESP32 core (dipakai fitur OTA), tidak perlu install manual.
- Akun **Midtrans Sandbox** — https://dashboard.sandbox.midtrans.com
- (Opsional) Broker MQTT sendiri — default pakai broker publik `broker.emqx.io`, cukup untuk development, **jangan untuk produksi**

> Versi sebelumnya dokumen ini mensyaratkan Google Cloud OAuth Client ID untuk
> login dashboard IoT. **Sudah tidak berlaku** — login dashboard sekarang
> memakai username + password (bcrypt), lihat §3.3.

---

## 3. Setup Backend

### 3.1 Install dependencies
```bash
cd toyamas-dispenser-v4.7.6.2      # folder root, BUKAN backend/ — requirements.txt ada di sini
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd backend
```

### 3.2 Isi `.env`
```ini
# Identitas mesin
MACHINE_ID=TYM-001
APP_ENV=development

# Security
JWT_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">

# HMAC fallback — dipakai HANYA untuk mesin yang belum punya secret sendiri
# di kolom `machines.secret` (mis. TYM-001 kalau didaftarkan manual lewat
# 001_init.sql, bukan lewat POST /api/iot/machines). Mesin yang didaftarkan
# lewat endpoint tersebut dapat secret UNIK sendiri secara otomatis — lihat
# §3.6. HARUS SAMA PERSIS dengan MACHINE_SECRET di firmware mesin yang
# memakai fallback ini (§5.2).
MACHINE_SECRET=toyamas-esp32-hmac-secret

# MQTT
MQTT_BROKER=broker.emqx.io
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_USE_TLS=false

# Midtrans SANDBOX — dashboard.sandbox.midtrans.com → Settings → Access Keys  ⚠️
MIDTRANS_SERVER_KEY=Mid-server-xxxxxxxxxx
MIDTRANS_IS_SANDBOX=true

# Cloudflare — KOSONGKAN kalau belum deploy Worker+D1 sendiri
CF_ACCOUNT_ID=
CF_API_TOKEN=
CF_D1_DB_ID=
CF_WORKER_URL=https://toyamas-api.your-worker.workers.dev

# Server
PORT=8000

# Opsional — override default (boleh dihapus)
# TIMEZONE_OFFSET_HOURS=8            # WITA. 7=WIB, 9=WIT
# MACHINE_OFFLINE_TIMEOUT_SEC=30
# BCRYPT_ROUNDS=12
# IOT_WS_REFRESH_STATUS_SEC=2        # interval broadcast status dashboard IoT
# IOT_WS_REFRESH_SALES_SEC=5         # interval broadcast ringkasan penjualan
```

⚠️ `MIDTRANS_SERVER_KEY` dalam bentuk **teks asli** (`Mid-server-...`), bukan base64. Untuk mesin yang memakai `MACHINE_SECRET` fallback ini, nilainya harus **identik** dengan firmware — beda satu karakter, semua komunikasi MQTT (masuk maupun command keluar) ditolak diam-diam (cek log server: `[SEC] HMAC MISMATCH`, atau Serial Monitor ESP32: `[SEC] HMAC fail`).

**Catatan penting:** `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_REDIRECT_URI`/`ADMIN_WHITELIST` yang dulu ada di sini **sudah tidak dipakai** — `config/settings.py` tidak lagi membacanya sama sekali. Boleh dihapus dari `.env` kalau masih tersisa dari setup lama, tidak berpengaruh apa-apa kalau dibiarkan juga (variabel yang tidak dibaca kode diabaikan begitu saja).

### 3.3 Setup Admin Dashboard (Username + Password)

Login dashboard IoT **tidak lagi** memakai Google OAuth — sekarang username + password dengan hash **bcrypt**, disimpan di tabel `admins` (migration 004).

1. Pastikan backend sudah pernah dijalankan minimal sekali (migration `004_add_admins.sql` otomatis membuat tabel `admins` + baris `admin`/`super_admin` tanpa password saat startup — lihat §3.4).
2. Dari folder `backend/`, jalankan:
   ```bash
   python create_admin.py
   ```
   Skrip ini membuat (atau me-reset, kalau `password_hash` masih kosong) akun:
   - **Username:** `admin`
   - **Password:** `toyamas123`
3. Login ke `http://localhost:8000/iot-dashboard` dengan kredensial di atas.
4. **Segera ganti password** lewat halaman profil dashboard (memanggil `POST /auth/change-password`), atau lewat API langsung:
   ```bash
   curl -X POST http://localhost:8000/auth/change-password \
     -H "Authorization: Bearer <token_dari_login>" \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","old_password":"toyamas123","new_password":"passwordBaruKamu"}'
   ```
5. Untuk mereset password admin lain (hanya bisa dilakukan oleh akun `role: super_admin`), gunakan `POST /auth/reset-password` (body `{"username": "...", "new_password": "..."}`) — insert baris admin baru ke tabel `admins` masih manual lewat SQL untuk saat ini (belum ada endpoint "buat admin baru" dari UI).

> Password dashboard dibatasi maksimal 16 karakter (validasi di `routes/auth.py`).

### 3.4 Jalankan backend
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Log yang diharapkan (startup pertama kali):
```
[INFO] services.database: Migration diterapkan: 001_init.sql
[INFO] services.database: Migration diterapkan: 002_add_location.sql
...
[INFO] services.database: Database initialized (9 migration file diperiksa)
[INFO] services.mqtt_bridge: MQTT connected to broker.emqx.io:1883
[INFO] services.mqtt_bridge: Subscribed (semua mesin): toyamas/+/status, toyamas/+/flow, toyamas/+/alarm
[INFO] main: Backend ready ✓
```
(Baris "Migration diterapkan" cuma muncul di startup pertama — restart berikutnya menampilkan "Migration dilewati (sudah diterapkan)" di level DEBUG karena tabel `schema_migrations` sudah mencatatnya.)

### 3.5 Akses UI
| URL | Untuk |
|---|---|
| `http://localhost:8000/` | UI Kiosk |
| `http://localhost:8000/iot-dashboard` | Dashboard admin/IoT (login §3.3) |
| `http://localhost:8000/docs` | Swagger API docs |

### 3.6 Menambah Mesin ke Armada (Multi-Mesin: TYM-002, TYM-003, dst)

Satu backend ini melayani SELURUH armada sekaligus (bukan satu backend per
mesin) — MQTT bridge subscribe wildcard ke semua `toyamas/+/status`, dst.
Untuk menambah mesin baru:

1. Login dashboard IoT (`/iot-dashboard`, §3.3) → halaman **Status Mesin** →
   tombol **"+ Tambah Mesin"** (atau `POST /api/iot/machines` langsung).
2. Isi ID Mesin (mis. `TYM-002`, harus sama persis dengan yang akan
   dipakai di firmware unit itu), Nama, PIN Admin 4 digit, dst.
3. Response-nya berisi field **`secret`** — ini HMAC secret UNIK untuk
   mesin ini (acak, 32 karakter hex, di-generate otomatis). **Catat/salin
   sekarang juga.**
4. Salin nilai `secret` itu ke firmware unit tersebut, di baris:
   ```cpp
   const char* MACHINE_ID     = "TYM-002";              // sama dgn yang didaftarkan
   const char* MACHINE_SECRET = "<secret dari response>"; // BUKAN yang di .env
   ```
5. Flash firmware ke ESP32 unit itu (§5).

> Kenapa secret-nya beda per mesin (bukan pakai `MACHINE_SECRET` di `.env`
> untuk semua)? Karena `machine_id` itu publik (ada di topic MQTT) — kalau
> semua mesin pakai secret yang sama, satu unit ESP32 yang berhasil
> dibongkar firmware-nya bisa dipakai untuk memalsukan data/command mesin
> LAIN juga. Dengan secret unik per mesin, membongkar satu unit cuma
> membahayakan unit itu sendiri.

Lupa mencatat secret dari response? Ambil lagi lewat:
```bash
curl -H "Authorization: Bearer <token_admin>" \
  https://server-kamu/api/iot/machines/TYM-002/secret
```

Mesin yang sudah lama terdaftar SEBELUM fitur ini ada (biasanya `TYM-001`,
lewat seed `001_init.sql`) otomatis tetap jalan tanpa perlu reflash —
backend fallback ke `MACHINE_SECRET` di `.env` untuk mesin yang belum
punya secret sendiri di database. Tidak ada downtime/breaking change.

Mau menghapus mesin dari armada (bukan hard-delete, riwayat transaksi tetap
tersimpan)? `DELETE /api/iot/machines/{machine_id}` — lihat `PAYLOAD_SPEC.md` §5.

### 3.7 (Opsional) Uji Dashboard Tanpa Hardware Fisik

Kalau belum ada ESP32 fisik tapi mau lihat dashboard "hidup" dengan beberapa
mesin sekaligus, pakai simulator MQTT di root repo:
```bash
pip install paho-mqtt --break-system-packages
python3 toyamas_mqtt_simulator_Mesin.py
```
Simulator ini mempublish payload `status`/`flow`/`alarm` dengan HMAC yang
formatnya identik dengan firmware asli, untuk beberapa mesin virtual
(default TYM-001/002/003 — sesuaikan `machine_id` & `secret` di dalam skrip
supaya cocok dengan yang terdaftar di database kamu). Ada console interaktif
(`dispense`, `low`, `alarm`, `refill`, dst.) untuk memicu skenario manual.

---

## 4. Simulasi Pembayaran

```bash
cd backend
python midtrans_webhook_sim.py                          # interaktif
python midtrans_webhook_sim.py TYM-1720000000-001        # sukses langsung
python midtrans_webhook_sim.py TYM-1720000000-001 --status expire
```
Alur uji: kiosk → pilih volume → Bayar → catat `order_id` → jalankan skrip → kiosk pindah ke halaman guide → klik "Sudah Siap" → countdown → DISPENSE terkirim.

`status`: `settlement`/`capture` (sukses) · `pending` · `expire`/`cancel`/`deny` (gagal).

---

## 5. Setup Firmware ESP32

### 5.1 Konfigurasi sebelum flash pertama kali
```cpp
#define DUMMY_MODE 1     // 1 = level galon simulasi, flow meter TETAP hardware asli (lihat §5.4)
                          // 0 = level galon JUGA pakai sensor JSN-SR04T asli

const char* WIFI_SSID      = "...";
const char* WIFI_PASSWORD  = "...";
const char* MQTT_BROKER    = "broker.emqx.io";   // samakan .env backend
const char* MACHINE_ID     = "TYM-001";           // samakan .env backend / hasil registrasi (§3.6)
const char* MACHINE_SECRET = "toyamas-esp32-hmac-secret";  // TYM-001: samakan .env backend.
                                                             // Mesin lain (TYM-002 dst): PAKAI nilai
                                                             // "secret" dari respons POST /api/iot/machines
                                                             // (§3.6), BUKAN nilai ini.
```

Relay di firmware ini **ACTIVE-LOW** (`setPump`/`setSolRO1`/`setSolRO2`/`setSolP1`/`setSolP2`/`setUV`, pola `on ? LOW : HIGH`). Cek modul relay fisik kamu trigger di LOW atau HIGH sebelum pasang ke mesin sungguhan — kalau modul kamu trigger-HIGH, baris itu perlu ditukar jadi `on ? HIGH : LOW`.

Sensor suhu DHT11 **sudah dihapus** dari firmware — kipas DC 12V (`RELAY_SPARE`) sekarang murni event-driven mengikuti solenoid RO/pompa aktif, bukan suhu. Lihat `PAYLOAD_SPEC.md` §0 untuk ringkasan lengkap histori versi firmware (relay polaritas, dual jalur OTA, dsb).

### 5.2 Flash via USB (pertama kali)
1. Board **ESP32 Dev Module** di Arduino IDE.
2. Upload, buka Serial Monitor (115200 baud).
3. Perhatikan boot banner — harus muncul versi firmware `1.4.3-http-ota`.
4. Cek di log backend: `HMAC verify raw: ... expected=X received=X` — kalau selalu cocok, koneksi valid.

### 5.3 Update firmware selanjutnya via OTA (tanpa USB)
Firmware ini mendukung **4 metode update** (USB, OTA HTTP lewat internet, OTA LAN/ArduinoOTA, OTA AP lokal darurat) — dokumentasi lengkap tiap metode ada di `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md`. Ringkasan metode AP lokal (paling sederhana, tanpa perlu setup server):

1. Compile firmware baru di Arduino IDE, **Sketch → Export Compiled Binary** untuk dapat file `.bin`.
2. Dari HP/laptop, connect ke WiFi **`TOYAMAS-OTA`** (password `toyamas123`).
3. Buka browser ke `http://192.168.4.1`.
4. Pilih file `.bin`, upload. ESP32 restart otomatis setelah selesai.

> Kredensial AP OTA ini hardcode di firmware (`OTA_AP_SSID`/`OTA_AP_PASSWORD`) — ganti sebelum produksi kalau khawatir orang lain di lokasi bisa upload firmware sembarangan ke mesin kamu. AP ini berjalan bersamaan dengan koneksi WiFi utama ke MQTT (mode AP+STA).

Untuk update jarak jauh (kios yang tidak satu jaringan dengan kamu) pakai **OTA HTTP lewat internet**, dipicu command MQTT `OTA_UPDATE` lewat script `ota_trigger.py` — lihat `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md` bagian B.

### 5.4 Soal mode DUMMY_MODE — baca sebelum uji coba
Di versi ini, `DUMMY_MODE` **tidak mempengaruhi flow meter** — pompa/UV mati berdasarkan pulsa flow meter **fisik asli** dari `FLOW_PIN`, walau `DUMMY_MODE=1`. Jadi:
- Kalau kamu mau test di meja tanpa galon/pompa sungguhan, tetap **wajib** ada flow meter fisik terpasang & berputar (atau disimulasikan manual dengan memutar sensornya) supaya `STATE_DISPENSING` bisa selesai — kalau tidak ada pulsa sama sekali, sesi dispense tidak akan pernah mencapai `target_liters` dan akan trigger alarm `PUMP_DRY_RUN` setelah 5 detik tanpa aliran.
- Level galon di dashboard/kiosk tetap "masuk akal" secara visual (turun mengikuti liter asli) walau ultrasonic-nya simulasi.
- `DUMMY_SET_LEVEL` (command MQTT, lihat `PAYLOAD_SPEC.md` §2) bisa dipakai untuk set level awal galon dummy secara manual tanpa nunggu naik/turun natural.
- Kalau tidak ada hardware fisik sama sekali (termasuk flow meter), pakai simulator MQTT (§3.7) sebagai gantinya — bukan `DUMMY_MODE` di firmware.

---

## 6. Alur Uji End-to-End (checklist)

1. ✅ Backend jalan, log `MQTT connected` + `Subscribed (semua mesin): .../status, .../flow, .../alarm`
2. ✅ ESP32 jalan, Serial Monitor tidak menunjukkan `[SEC] HMAC fail` berulang, boot banner `1.4.3-http-ota`
3. ✅ Login dashboard IoT dengan username/password (§3.3) → Monitoring menampilkan mesin **Online**
4. ✅ Matikan ESP32 → dalam ±30–35 detik dashboard otomatis **Offline**
5. ✅ Kiosk: pilih volume → Bayar → QR muncul
6. ✅ `python midtrans_webhook_sim.py <order_id>` → kiosk pindah ke guide → klik "Sudah Siap"
7. ✅ Setelah countdown, ESP32 terima `DISPENSE` (Serial Monitor: `[CMD] DISPENSE order=... vol=...L`) — pastikan flow meter berputar (fisik atau manual) supaya sesi bisa selesai
8. ✅ Kiosk animasi realtime jalan, dashboard IoT Transaksi & Laporan menampilkan transaksi baru

---

## 7. Troubleshooting Cepat

| Gejala | Kemungkinan penyebab |
|---|---|
| Login dashboard IoT gagal, "Username atau password salah" | Belum jalankan `python create_admin.py` (§3.3), atau salah ketik. Kalau lupa password dan `password_hash` sudah pernah terisi (skrip tidak auto-reset lagi kalau sudah ada), reset lewat `POST /auth/reset-password` pakai akun `super_admin` lain |
| Login sukses tapi semua halaman dashboard 403 `Akun admin tidak aktif` | Kolom `is_active` admin tersebut `0` di tabel `admins` — aktifkan manual lewat SQL, atau reset via `super_admin` lain |
| Status/flow ESP32 tidak sampai backend / DISPENSE tidak diterima | Secret HMAC di firmware tidak cocok dengan yang backend pakai untuk `machine_id` itu — untuk mesin yang punya secret sendiri (§3.6), cek lewat `GET /api/iot/machines/{id}/secret`; untuk mesin fallback, cek `MACHINE_SECRET` di `.env` |
| Charge Midtrans gagal / 401 | `MIDTRANS_SERVER_KEY` masih base64, belum di-decode |
| Emergency STOP/RESET/PING dari panel admin tidak berefek | Pastikan `services/mqtt_bridge.py` (`publish_stop_command`) dan `routes/hardware.py` mengirim payload **dengan field `hmac`** — versi tanpa ini selalu ditolak firmware |
| Dashboard selalu "Online" walau ESP32 mati | `get_all_machines_status()` di `services/database.py` harus hitung staleness dari `last_seen`, bukan baca flag `online` mentah |
| Jam di dashboard selisih 8 jam | `iot/js/app.js` & `iot/js/transactions.js` harus pakai `parseServerTime()`, bukan `new Date()` langsung; query laporan di `services/database.py` harus pakai `TZ_SQL_MODIFIER` |
| Sesi DISPENSING tidak pernah selesai / macet, muncul alarm `PUMP_DRY_RUN` | Flow meter fisik tidak terdeteksi berputar — ingat di firmware ini flow **selalu** butuh pulsa asli walau `DUMMY_MODE=1` (lihat §5.4) |
| `python midtrans_webhook_sim.py` error `Install dulu: pip install requests` | `requests` belum ada — pastikan `pip install -r requirements.txt` dijalankan dari **root** repo (§3.1), bukan dari dalam `backend/` |
| `pip install -r requirements.txt` gagal "no such file" di dalam folder `backend/` | `requirements.txt` cuma ada di root repo, tidak ada salinan di dalam `backend/` — `cd` ke root dulu (§3.1) |
| Error `ModuleNotFoundError: No module named 'bcrypt'` saat `create_admin.py` / login | `pip install -r requirements.txt` belum di-rerun setelah update — `bcrypt` sekarang sudah ada di `requirements.txt` |
| Tidak bisa akses `192.168.4.1` untuk OTA | Pastikan device (HP/laptop) benar-benar connect ke WiFi `TOYAMAS-OTA`, bukan ke WiFi rumah/kantor — AP OTA ini WiFi terpisah dari WiFi MQTT utama ESP32 |

---

## 8. Keamanan — Wajib Diganti Sebelum Produksi

- Password admin dashboard default `admin` / `toyamas123` (dibuat oleh `create_admin.py`, §3.3) → **ganti segera** lewat `POST /auth/change-password`.
- PIN admin kiosk default `1234` → ganti lewat `POST /api/admin/pin`.
- `JWT_SECRET`, `MACHINE_SECRET` → generate ulang (`python -c "import secrets; print(secrets.token_hex(32))"`), update juga di firmware.
- Kredensial AP OTA (`TOYAMAS-OTA`/`toyamas123`) → ganti di firmware sebelum pasang ke lokasi publik.
- `MIDTRANS_IS_SANDBOX=false` + Server Key produksi saat siap terima pembayaran sungguhan.
- Broker MQTT publik (`broker.emqx.io`) → ganti broker privat untuk produksi.
