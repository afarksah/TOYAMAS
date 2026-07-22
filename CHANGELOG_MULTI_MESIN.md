# Perubahan untuk Dukungan Multi-Mesin (TYM-002, TYM-003, dst)

Ringkasan perubahan kode dari v4.7.4 asli. Semua perubahan backward-compatible —
TYM-001 yang sudah jalan tidak terpengaruh.

## 1. `backend/config/settings.py`
Tambah 3 konstanta topic wildcard (tidak menghapus yang lama):
```python
MQTT_TOPIC_STATUS_WILDCARD = "toyamas/+/status"
MQTT_TOPIC_FLOW_WILDCARD   = "toyamas/+/flow"
MQTT_TOPIC_ALARM_WILDCARD  = "toyamas/+/alarm"
```

## 2. `backend/services/mqtt_bridge.py` (perubahan paling penting)
- `_on_connect`: subscribe ke topic **wildcard** (semua mesin), bukan cuma
  `MACHINE_ID` dari `.env`. Ini akar masalahnya — sebelumnya data dari
  TYM-002/003 tidak pernah sampai ke backend meski broker sama.
- `_on_message`: `machine_id` sekarang diambil dari **topic MQTT**
  (`toyamas/{machine_id}/{subtopic}`), bukan dari field `machine_id` di
  payload. Field `machine_id` di payload tetap dicek harus cocok dengan
  topic — kalau beda, pesan ditolak. Dispatch ke processor (`status` /
  `flow` / `alarm`) sekarang berdasarkan subtopic, bukan string topic
  persis, supaya berlaku untuk semua machine_id.
- `_on_disconnect`: tidak lagi menandai satu `MACHINE_ID` sebagai offline
  (itu salah untuk armada — semua mesin sebenarnya kehilangan koneksi ke
  backend saat broker disconnect). Status online/offline tiap mesin sudah
  otomatis dihitung ulang dari `last_seen` di `get_all_machines_status()`.
- `client_id` MQTT diganti jadi `toyamas-backend-hub` (bukan
  `toyamas-backend-{MACHINE_ID}`) karena satu backend ini melayani seluruh
  armada.

## 3. `backend/services/database.py`
Fungsi baru:
- `list_machines()` — semua mesin terdaftar.
- `create_machine(machine_id, name, admin_pin_hash, location=None, price_per_liter=500, mode="RO")`
  — daftarkan mesin baru: insert ke `machines`, seed `machine_state_cache`,
  dan default `machine_config`. Raise `ValueError` kalau `machine_id` sudah ada.

## 4. `backend/routes/iot.py`
Endpoint baru: **`POST /api/iot/machines`** (perlu admin login, sama seperti
endpoint IoT lain). Body:
```json
{
  "machine_id": "TYM-002",
  "name": "Toyamas Cabang 2",
  "admin_pin": "1234",
  "location": "Jl. Contoh No. 5",
  "price_per_liter": 500,
  "mode": "RO"
}
```
Menggantikan cara lama (insert manual ke SQLite).

## 5. `backend/frontend/js/app.js`
`machine_id` kiosk sekarang diambil dari query string URL
(`?machine=TYM-002`), fallback ke `TYM-001` kalau tidak ada. Sebelumnya
hardcode `'TYM-001'` di dua tempat (`AppState.init` & `API.init`). Artinya
file kiosk yang SAMA bisa dipakai di semua unit — tinggal beda bookmark/URL
kiosk browser di tiap lokasi, contoh:
```
https://server-kamu/frontend/?machine=TYM-001
https://server-kamu/frontend/?machine=TYM-002
https://server-kamu/frontend/?machine=TYM-003
```

## 6. UI: Form "+ Tambah Mesin" di Dashboard IoT
Tidak perlu `curl` manual lagi. Di halaman **Status Mesin** (dashboard utama)
sekarang ada tombol **"+ Tambah Mesin"** di pojok kanan atas grid mesin.

- `backend/iot/index.html` — tombol `#addMachineBtn` + modal `#addMachineModal`
  berisi form: ID Mesin, Nama, PIN Admin (4 digit), Mode (RO/Manual), Harga/Liter,
  Lokasi (opsional).
- `backend/iot/css/dashboard.css` — style modal baru (`.modal-overlay`,
  `.modal-card`, `.form-group`, dst), mengikuti warna & radius yang sudah ada
  di dashboard (tidak menyentuh style lain).
- `backend/iot/js/app.js` — `openAddMachineModal()` / `closeAddMachineModal()` /
  `handleAddMachineSubmit()`: submit form memanggil `POST /api/iot/machines`
  lewat `Auth.fetchWithAuth()` (otomatis pakai token admin yang sedang login),
  lalu me-refresh grid mesin (`loadDashboardData()`) begitu berhasil. Pesan
  error dari backend (mis. "machine_id sudah terdaftar") ditampilkan langsung
  di dalam modal. Modal bisa ditutup lewat tombol ×, "Batal", klik di luar
  modal, atau tombol Escape.

Alur pakainya: buka dashboard IoT → login admin → klik "+ Tambah Mesin" →
isi form (ID Mesin harus sama persis dengan `MACHINE_ID` yang akan di-flash
ke ESP32 unit tersebut) → Simpan → mesin baru langsung muncul di grid dengan
status Offline sampai unit fisiknya online.

## 7. Dropdown pilih-mesin di halaman Laporan (+ perbaikan dropdown Transaksi yang mati)
- `backend/iot/index.html` — tambah `<select id="reportMachineFilter">` di
  halaman Laporan Penjualan (di samping tab periode Hari Ini/Minggu Ini/Bulan Ini).
- `backend/iot/js/app.js`:
  - **Bug ditemukan**: `initMachineFilter()` (pengisi dropdown mesin di
    halaman Transaksi) ternyata **tidak pernah dipanggil di mana pun** —
    jadi dropdown itu selama ini selalu kosong meski mesin sudah terdaftar.
    Diganti `populateMachineFilters()` yang mengisi DUA dropdown sekaligus
    (Transaksi & Laporan), idempotent (aman dipanggil berulang tanpa
    duplikasi opsi), dipanggil tiap `loadDashboardData()` — termasuk
    otomatis ter-refresh begitu ada mesin baru lewat form "+ Tambah Mesin".
  - `loadReportData(period)` sekarang menyertakan `machine_id` (kalau
    dipilih) ke `/api/iot/summary` dan `/api/iot/charts`.
  - Halaman **Overview** (dashboard utama, stat cards + grafik atas)
    sengaja TETAP menampilkan gabungan semua mesin — itu memang halaman
    ringkasan armada. Rincian per-mesin sudah ada di halaman Monitoring
    (kartu per mesin) dan sekarang di Laporan (dropdown baru ini).

## 8. SQL Injection di 3 fungsi laporan (perbaikan keamanan)
Ditemukan: `get_sales_summary()`, `get_hourly_sales()`, `get_daily_sales()`
di `backend/services/database.py` menempel `machine_id` langsung ke teks
SQL lewat f-string (`f"AND machine_id = '{machine_id}'"`), bukan lewat
parameter terikat. Endpoint `/api/iot/summary` dan `/api/iot/charts`
menerima `machine_id` sebagai query string BEBAS tanpa validasi format —
jadi payload seperti `?machine_id=x' OR '1'='1` atau `UNION SELECT` bisa
mengubah struktur query dan berpotensi membaca data lintas mesin (bahkan
tabel lain seperti `admins`/`admin_pin_hash`).

**Sudah diperbaiki:**
- Ketiga fungsi di atas diubah ke parameter terikat (`machine_id = ?` +
  value lewat `params`, pola sama seperti `get_transactions_filtered()`
  yang memang sudah benar sejak awal).
- Ditambah validasi format di level endpoint (`routes/iot.py`) —
  `machine_id: str = Query(None, regex="^[A-Za-z0-9_-]+$")` — pada
  `/dashboard`, `/summary`, `/charts`, `/transactions` sebagai lapisan
  pertahanan tambahan (bukan pengganti fix di atas).
- Diverifikasi: fungsi lain yang menyentuh `machine_id` (`get_transactions_filtered`,
  `get_machine_location`, `update_machine_location`, `update_machine_online`,
  dst) sudah memakai parameter terikat dengan benar — cuma 3 fungsi di atas
  yang bermasalah.
- Dites dengan payload `TYM-001' OR '1'='1` — sekarang diperlakukan sebagai
  teks biasa (hasil kosong), bukan mengubah query.

## 9. Secret HMAC per-mesin (bukan satu MACHINE_SECRET global lagi)
- **Migration 006** (`database/migrations/006_add_machine_secret.sql`) — kolom
  `machines.secret`, nullable & backward compatible (mesin lama tanpa secret
  otomatis fallback ke `MACHINE_SECRET` global di `.env`, tidak ada downtime).
- `services/database.py` — `get_machine_secret(machine_id)` (lookup + fallback),
  `create_machine()` sekarang auto-generate secret unik (`secrets.token_hex(16)`)
  kalau tidak diisi eksplisit.
- `middleware/auth.py` — `compute_mqtt_hmac()`, `verify_mqtt_hmac()`,
  `compute_command_hmac()` semua diubah untuk lookup secret KHUSUS `machine_id`
  yang dituju lewat `get_machine_secret()`, bukan `MACHINE_SECRET` global lagi.
- `routes/iot.py` — `POST /api/iot/machines` sekarang mengembalikan `secret`
  yang di-generate (dengan catatan jelas untuk disalin ke firmware); endpoint
  baru `GET /api/iot/machines/{machine_id}/secret` untuk lihat ulang kalau lupa
  dicatat (perlu admin login).
- `iot/index.html` + `iot/js/app.js` — modal "Tambah Mesin" sekarang punya
  **state sukses** yang menampilkan secret hasil registrasi secara persisten
  (dengan tombol salin ke clipboard), bukan cuma toast 3 detik yang gampang
  kelewat. Diperbaiki juga: form asalnya punya `<form>` bersarang tidak valid
  (bug struktur HTML) — sudah dirapikan.
- **Dites lengkap** (payload asli, bukan cuma baca kode): mesin lama tanpa
  secret tetap fallback ke `MACHINE_SECRET` global ✓, mesin baru dapat secret
  unik 32-hex-char ✓, HMAC command untuk 2 mesin berbeda menghasilkan hash
  berbeda ✓, dan yang paling penting — **HMAC yang sah untuk satu mesin
  ditolak kalau dicoba diklaim sebagai mesin lain** ✓ (ini yang menutup celah
  forge lintas-mesin).
- **Dokumentasi diperbarui**: `PAYLOAD_SPEC.md` §11 (skema HMAC, database
  schema §9), `SETUP_GUIDE.md` §3.6 (cara registrasi + catat secret),
  `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md` (poin persiapan sebelum flash unit
  baru + catatan keamanan) — semua disinkronkan supaya tidak ada dokumen yang
  masih menjelaskan model satu-secret-untuk-semua-mesin yang lama.

## 10. Mode RO/Manual dari Dashboard IoT — perbaikan end-to-end (respons palsu & Default Mode global tidak nyampe ke ESP32)

Firmware (`switchMode()`, handler `SET_MODE` di `mqttCallback()`) dan backend
(`publish_set_mode_command()` di `mqtt_bridge.py`) sudah sama-sama benar dari
sisi HMAC/topic/format sejak awal — masalahnya ada di endpoint yang
menghubungkan keduanya:

- **`routes/iot_settings.py` (`POST /api/iot/settings/{machine_id}`)** —
  sebelumnya `UPDATE machines SET mode=...` langsung dieksekusi dan endpoint
  SELALU membalas `success: true`, TANPA pernah mengecek apakah
  `publish_set_mode_command()` benar-benar berhasil publish ke broker MQTT.
  Kalau MQTT client backend sedang disconnect, dashboard tetap bilang
  "berhasil" padahal ESP32 tidak pernah menerima perintahnya, dan DB jadi
  menyimpan mode yang tidak sesuai kondisi mesin sebenarnya.
  **Sekarang:** publish dulu → DB hanya diupdate kalau publish sukses →
  kalau gagal, response `503` (mode-only) atau field `mode_warning` (kalau
  digabung dengan perubahan config lain yang tetap berhasil disimpan).
- **`services/database.py` (`apply_global_default_to_all_machines`, dipanggil
  dari tombol "Default Mode" di halaman Pengaturan Global)** — bug yang sama
  tapi lebih parah: cabang `default_mode` HANYA `UPDATE machines SET mode=...
  WHERE is_active=1` + broadcast WebSocket ke kiosk (update tampilan saja).
  **Perintah MQTT `SET_MODE` ke ESP32 tidak pernah dikirim sama sekali** —
  mode mesin fisik baru benar-benar berubah kalau admin membuka Settings
  per-mesin satu-satu dan klik Simpan lagi. **Sekarang:** tombol Default
  Mode langsung mengirim `SET_MODE` ke tiap mesin aktif; `affected_machines`
  yang dikembalikan ke dashboard sekarang berarti "mesin yang perintahnya
  benar-benar terkirim", bukan sekadar "jumlah mesin aktif di DB".
- `iot/js/app.js` — `saveSettings()` menampilkan `mode_warning` (kalau ada)
  sebagai warning kuning, bukan centang hijau yang menyesatkan.

## 11. Konsolidasi WebSocket Dashboard IoT (kurangi beban DB, sedikit lebih realtime)

- **`routes/websocket.py` (`IoTWebSocketManager`)** — sebelumnya tiap admin
  yang connect memicu `_broadcast_loop` SENDIRI-SENDIRI, masing-masing query
  DB (`get_all_machines_status`, `get_sales_summary`,
  `get_transactions_filtered`) tiap `IOT_WS_REFRESH_STATUS_SEC` detik. 3 admin
  buka dashboard bersamaan = 3x query DB untuk data yang sama persis. Interval
  sales juga ikut nempel ke interval status (bukan `IOT_WS_REFRESH_SALES_SEC`
  yang memang sudah ada tapi tidak pernah dipakai).
  **Sekarang:** satu loop global untuk semua admin — query DB sekali per
  tick, hasil di-fan-out ke semua koneksi yang sedang terbuka. Beban DB jadi
  konstan, tidak scaling dengan jumlah tab dashboard yang dibuka. Status dan
  sales sekarang punya interval independen sesuai konfigurasi masing-masing.
- **`config/settings.py`** — karena beban tidak lagi berkali lipat, interval
  status diturunkan `5s → 3s` (`IOT_WS_REFRESH_STATUS_SEC`) supaya dashboard
  terasa lebih realtime tanpa menambah beban dibanding sebelumnya. Interval
  sales tetap `10s` (`IOT_WS_REFRESH_SALES_SEC`).
- Kiosk WebSocket (`ws_manager` di `mqtt_bridge.py`, per-mesin) tidak diubah —
  itu memang sudah event-driven (push langsung saat pesan MQTT dari ESP32
  masuk), bukan polling berkala.


1. **Firmware tiap ESP32** — ganti `MACHINE_ID` dan semua `TOPIC_*` di
   `.ino` sebelum compile & flash tiap unit (lihat baris ~101-108 di
   firmware). Kalau kelewat satu topic, unit itu tidak akan
   terdeteksi backend / bentrok dengan mesin lain.
2. **Daftarkan tiap mesin baru** lewat `POST /api/iot/machines` (atau lewat
   dashboard IoT kalau nanti dibuatkan UI form-nya) sebelum ESP32-nya
   dinyalakan, supaya begitu online langsung terlihat di dashboard.
3. **(Opsional, keamanan)** `MACHINE_SECRET` saat ini masih satu nilai yang
   sama untuk semua mesin (di `.env` backend maupun di semua firmware).
   Untuk armada yang lebih besar/production, sebaiknya tiap mesin punya
   secret unik (kolom baru di tabel `machines`, dipakai saat hitung/verifikasi
   HMAC per `machine_id`) supaya satu unit yang dibongkar tidak bisa
   memalsukan data/command mesin lain.

## 12. Sinkronisasi firmware ↔ dokumentasi (`toyamas_firmware_v1_4_3_http_ota.ino`)

Kontrak data inti (topic MQTT, HMAC, command, field `status`/`flow`/`alarm`) sudah
sinkron dengan backend sejak awal. Yang tidak sinkron ada di tiga tempat:

- **Label versi ganda di file firmware itu sendiri** — nama file bilang `v1.4.3`,
  komentar header bilang `v1.4.0`, konstanta `FIRMWARE_VERSION` (yang benar-benar
  dikirim ke dashboard via `sys.firmware_ver`) bilang `1.4.1-http-ota`. **Sekarang:**
  ketiganya disamakan jadi `1.4.3-http-ota`, tidak ada perubahan perilaku.
- **Penamaan field OTA yang menyesatkan** — `ota.internet_enabled`/`internet_remaining_sec`
  di payload status sebenarnya melaporkan status OTA **LAN** (ArduinoOTA/mDNS), bukan
  OTA HTTP lewat internet yang beneran (itu `ota.http_in_progress`). Belum ada consumer
  (dashboard/script) yang baca field ini, jadi aman diganti sekarang sebelum ada yang
  mulai pakai. **Sekarang:** `ota.lan_ota_enabled`/`ota.lan_ota_remaining_sec`.
- **`PAYLOAD_SPEC.md` masih mengacu ke firmware `v1.3.5-OTA` yang sudah lama** — belum
  mendokumentasikan `env.fan_on`, seluruh objek `ota.*`, `galon.g1_estimated`/`g2_estimated`,
  command `OTA_ENABLE`/`OTA_DISABLE`/`OTA_UPDATE`, dan alarm type `FILL_TIMEOUT` (semua
  sudah ada di firmware tapi belum tercatat). Masih menyebut field `system.dummy_level_only`
  sebagai fitur baru padahal firmware yang jalan sekarang tidak pernah mengirim field itu.
  **Sekarang:** §0, §1.1, §1.3, §2 di `PAYLOAD_SPEC.md` diperbarui mengikuti firmware
  `1.4.3-http-ota` yang sebenarnya berjalan.