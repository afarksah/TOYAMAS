# TOYAMAS — Master Payload Specification
**Versi:** 2.5 | **Diperbarui:** 23 Juli 2026 — firmware `1.5.0-ota-lan-ap`, backend v4.7.6.2

> Perubahan v2.5 (§0–§2, khusus bagian ESP32 — bagian lain belum direview ulang
> di revisi ini): firmware naik dari `1.4.3-http-ota` ke `1.5.0-ota-lan-ap`.
> **OTA HTTP internet (dulu §0.2, command `OTA_UPDATE`) dihapus dari dokumen
> ini karena TIDAK ADA implementasinya di firmware yang jalan sekarang** —
> tidak ada `HTTPClient`, tidak ada verifikasi MD5, tidak ada handler
> `OTA_UPDATE` di `mqttCallback`. Firmware ini hanya punya OTA LAN (ArduinoOTA)
> dan OTA AP (WebServer lokal). Field payload `ota.*` diperbaiki sesuai nama
> asli di kode (`lan_enabled`/`ap_enabled`, bukan `lan_ota_enabled`/
> `http_in_progress`). §1.1 interval publish `status` dikoreksi (berhenti
> total saat `DISPENSING`, digantikan topic `flow`, bukan "tiap 10 detik state
> apa pun"). §1.2/§0 dikoreksi: saat `DUMMY_MODE 1`, ISR flow meter fisik
> **dimatikan** dan datanya ikut disimulasikan (`dummySimulateFlow()`) — bukan
> "selalu data real" seperti tercatat sebelumnya. §2 tabel `OTA_ENABLE`/
> `OTA_DISABLE` ditambah field wajib `type` & `token` yang sebelumnya terlewat.
>
> Perubahan v2.4: §3.1 tambah event WS `config_update`/`signage_update` yang
> sebelumnya belum tercatat; §3.2 koreksi nilai default interval WS
> (`IOT_WS_REFRESH_STATUS_SEC`/`IOT_WS_REFRESH_SALES_SEC`) sesuai
> `config/settings.py` yang berjalan; §4 tambah `POST /api/admin/verify-pin`
> yang terlewat dari tabel; §5 ganti seluruh bagian Auth dari Google OAuth
> (sudah tidak dipakai) ke username+password, dan pindahkan endpoint
> soft-delete mesin dari tabel Locations ke tabel Machines sesuai lokasi
> sebenarnya di `routes/iot.py`.

Dokumen ini mendefinisikan **semua format data** yang bergerak antar komponen sistem:
ESP32 ↔ Backend ↔ Database ↔ UI Kiosk ↔ UI IoT Dashboard ↔ Midtrans ↔ (opsional) Cloudflare

Bagian §0–§2 (ESP32) di bawah ini diverifikasi langsung terhadap kode yang berjalan
(`toyamas_firmware_v1_5_0.ino`, `FIRMWARE_VERSION "1.5.0-ota-lan-ap"`), bukan
rencana/desain awal. Bagian §3 ke bawah (backend/DB/UI) belum direview ulang
di revisi ini — tanggal verifikasinya masih mengikuti v2.4.

---

## 0. Status Firmware

Firmware: `toyamas_firmware_v1_5_0.ino`, versi internal **konsisten** di semua tempat (nama file, komentar header, `sys.firmware_ver`) = **`1.5.0-ota-lan-ap`**.

**Ringkasan dari histori versi (lihat changelog lengkap di header file `.ino`):**

1. **Mode dummy** (`DUMMY_MODE 1`) → sensor ketinggian (ultrasonic JSN-SR04T) **dan** flow meter **sama-sama disimulasikan**. Saat `DUMMY_MODE 1`, `initHardware()` **tidak** memasang interrupt `flowPulseISR` ke `FLOW_PIN` sama sekali ("Hardware ISR dinonaktifkan — pakai data simulasi") — angka aliran datang dari `dummySimulateFlow()` yang menyuntikkan pulsa palsu ke variabel `pulseCount` yang sama, bukan dari sensor fisik. Jadi `flow.current_liters`/`flow.flow_rate_lpm` (topic `flow`, §1.2) **TIDAK bisa dipercaya sebagai angka real saat `DUMMY_MODE 1`** — ini beda dari catatan versi sebelumnya yang bilang flow meter "selalu real hardware terlepas dari DUMMY_MODE". `system.dummy_mode: true` muncul kalau dikompilasi dummy. Tidak ada field terpisah `dummy_level_only` di firmware ini — hanya `system.dummy_mode`.
2. **Relay polaritas: ACTIVE-LOW** (`digitalWrite(RELAY_x, on ? LOW : HIGH)`) untuk `RELAY_PUMP`, `RELAY_SOL_RO1/RO2`, `RELAY_SOL_P1/P2`, `RELAY_UV`.
3. **Dual jalur OTA** — lihat §0.1 (AP lokal) dan §0.2 (LAN/ArduinoOTA). **Tidak ada jalur OTA HTTP/internet** di firmware ini (lihat catatan di §0.2).
4. **Sensor suhu DHT11 sudah DIHAPUS** — Kipas DC 12V (`RELAY_SPARE`) murni event-driven: ON kalau salah satu solenoid (RO1/RO2/P1/P2) aktif, OFF kalau semua nonaktif. `env.fan_on` tetap ada di payload status, `env.temp_c` **tidak ada** (dan tidak pernah dikirim).
5. **Relay ke-8** untuk solenoid input RO — otomatis ikut buka kalau SOL_RO1 ATAU SOL_RO2 aktif.
6. **Alarm audible** — beep ringan buzzer untuk `GALON_LOW` (1x) & `GALON_CRITICAL` (2x), di luar pola beep panjang untuk alarm ERROR.

### 0.1 OTA AP Lokal — murni sisi firmware, tidak lewat backend
ESP32 bisa membuka **Access Point WiFi sendiri** khusus update firmware tanpa kabel USB:
- SSID: `TOYAMAS-OTA`, password: `toyamas123`
- Alamat: `http://192.168.4.1` (buka browser setelah connect ke WiFi itu dari HP/laptop)
- Upload file `.bin` hasil compile Arduino IDE lewat halaman web itu, device restart otomatis setelah selesai
- Aktivasi: command MQTT `OTA_ENABLE` dengan `type:"ap"` (§2), **atau** langsung di device tekan tombol **MODE 3x cepat dalam 5 detik** (beep 3x sebagai konfirmasi). Auto-mati sendiri setelah 15 menit (`OTA_AP_TIMEOUT_MS`) kalau tidak dipakai.
- ⚠️ Beda dari OTA LAN (§0.2): mulai upload di jalur AP **tidak** otomatis memanggil `deactivateAll()` — kalau device sedang dispensing saat upload AP OTA dimulai, pompa/solenoid berpotensi masih menyala.

Ini **tidak melewati MQTT/backend sama sekali** untuk transfer filenya — murni koneksi langsung HP/laptop ↔ ESP32 lewat WiFi lokal. Tidak ada endpoint atau event baru di backend untuk ini.

### 0.2 OTA LAN (ArduinoOTA) — device & laptop admin satu jaringan
Aktivasi: command MQTT `OTA_ENABLE` dengan `type:"lan"` (§2), **atau** langsung di device tekan tombol **MODE 6x cepat dalam 10 detik** (beep 2x sebagai konfirmasi). Auto-mati sendiri setelah 5 menit (`OTA_LAN_TIMEOUT_MS`) kalau tidak dipakai, atau matikan manual lewat `OTA_DISABLE`. Begitu update mulai (`ArduinoOTA.onStart()`), firmware otomatis panggil `deactivateAll()` — pompa/solenoid/UV mati semua secara otomatis.

Butuh laptop admin & ESP32 di jaringan WiFi yang sama — **bukan** untuk device di lokasi jauh dari admin.

> **Tidak ada OTA HTTP/internet di firmware ini.** Versi dokumen sebelumnya (`1.4.3-http-ota`) mencatat adanya command `OTA_UPDATE` untuk download `.bin` dari URL server + verifikasi MD5 — ini **tidak ada** di kode `toyamas_firmware_v1_5_0.ino` yang jalan sekarang (tidak ada `HTTPClient`, tidak ada pengecekan MD5, tidak ada handler `OTA_UPDATE` di `mqttCallback`). Kalau butuh update kios yang jaraknya jauh dan tidak bisa didatangi teknisi, satu-satunya opsi saat ini adalah OTA LAN lewat VPN/tunnel ke jaringan yang sama, atau kirim teknisi (USB/OTA AP) — lihat `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md`.

Kedua command ini (`OTA_ENABLE`/`OTA_DISABLE`) **dipicu dari script terpisah `ota_trigger.py`** (lihat `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md`), **bukan** dari UI dashboard IoT — belum ada tombol/endpoint backend untuk trigger OTA dari dashboard.

### 0.3 Nama field OTA di payload status
Field aktualnya (lihat `publishStatus()` di kode): **`ota.lan_enabled`**, **`ota.ap_enabled`**, **`ota.lan_remaining_sec`** (muncul kalau `lan_enabled: true`), **`ota.ap_remaining_sec`** (muncul kalau `ap_enabled: true`). **Tidak ada** `ota.lan_ota_enabled`, `ota.http_in_progress`, atau `ota.http_progress_pct` — field-field itu tercatat di versi dokumen sebelumnya tapi tidak pernah ada di kode yang jalan.



## 1. ESP32 → Backend (MQTT Publish)

### 1.1 Topic: `toyamas/{machine_id}/status`
Dikirim setiap **10 detik**, **kecuali saat `state == DISPENSING`** — selama dispensing, topic ini **berhenti total** dan digantikan sepenuhnya oleh topic `flow` (§1.2) tiap ~100ms. Keduanya berbagi satu timer publish yang sama di firmware (`taskStatus`), jadi tidak pernah dikirim bersamaan.

```json
{
  "machine_id": "TYM-001",
  "timestamp": 3142,
  "state": "IDLE",
  "mode": "RO",
  "galon": {
    "g1_level_pct": 78.5,
    "g1_level_cm": 14.9,
    "g1_status": "OK",
    "g1_estimated": false,
    "g2_level_pct": 42.1,
    "g2_level_cm": 8.0,
    "g2_status": "LOW",
    "g2_estimated": false,
    "active_galon": 1,
    "filling_galon": 1
  },
  "actuators": {
    "pump_dc": false,
    "solenoid_ro1": false,
    "solenoid_ro2": false,
    "solenoid_pump1": false,
    "solenoid_pump2": false,
    "uv_lamp": false
  },
  "leds": { "green": true, "yellow": false, "red": false },
  "system": {
    "uptime_sec": 86400,
    "wifi_rssi": -62,
    "free_heap": 180000,
    "firmware_ver": "1.5.0-ota-lan-ap",
    "dummy_mode": true
  },
  "env": { "fan_on": false },
  "ota": {
    "lan_enabled": false,
    "ap_enabled": false,
    "lan_remaining_sec": 240,
    "ap_remaining_sec": 870
  },
  "machine_status": {
    "online_since": 12,
    "last_dispense": 51230,
    "total_dispense_today": 42.5,
    "total_transactions_today": 9
  },
  "hmac": "sha256hex_signature"
}
```

Catatan field:
- `timestamp` **bukan** epoch Unix — ini `millis()/1000` sejak ESP32 boot. Backend memakai waktu server sendiri untuk `last_seen`/`created_at`.
- `galon.filling_galon` hanya muncul saat `state == "FILLING"`.
- `galon.g1_estimated`/`g2_estimated` — `true` kalau angka level lagi berasal dari estimasi flow meter (blind-zone ultrasonic), bukan bacaan sensor langsung.
- `system.dummy_mode` — muncul (selalu `true`) kalau firmware dikompilasi `DUMMY_MODE 1`. **Bukan cuma sensor ketinggian yang disimulasikan** — flow meter fisik ikut dinonaktifkan (lihat §0 poin 1), jadi `flow.current_liters`/`flow.flow_rate_lpm` di topic `flow` (§1.2) **ikut simulasi**, bukan angka real, selama `DUMMY_MODE 1`.
- `env.fan_on` — status kipas DC 12V (`RELAY_SPARE`), event-driven dari solenoid aktif (§0), bukan dari suhu (DHT11 sudah dihapus).
- `ota.lan_enabled`/`ota.lan_remaining_sec` (muncul kalau `lan_enabled: true`) — status OTA LAN (§0.2).
- `ota.ap_enabled`/`ota.ap_remaining_sec` (muncul kalau `ap_enabled: true`) — status OTA AP lokal (§0.1).
- Tidak ada field `ota.http_in_progress`/`ota.http_progress_pct` — OTA HTTP tidak ada di firmware ini (§0.2).
  > Backend saat ini **belum** membaca field `ota.*` atau `env.fan_on` secara eksplisit (belum ada badge/indikator khusus di dashboard) — datanya tetap tersimpan lengkap di `machine_state_cache.raw_json` kalau suatu saat mau ditampilkan (mis. badge status OTA di halaman Monitoring).
- `state` salah satu dari: `IDLE | FILLING | DISPENSING | FINISHING | ALERT | ERROR`.

### 1.2 Topic: `toyamas/{machine_id}/flow`
Dikirim setiap **~100 ms** hanya saat `state = DISPENSING`. Dari flow meter fisik asli **kecuali saat `DUMMY_MODE 1`**, di mana datanya ikut disimulasikan (lihat §0 poin 1 — ini beda dari catatan versi dokumen sebelumnya).

```json
{
  "machine_id": "TYM-001",
  "timestamp": 3180,
  "session_id": "sess_abc123",
  "state": "DISPENSING",
  "flow": {
    "current_liters": 3.42,
    "target_liters": 5.0,
    "flow_rate_lpm": 1.18,
    "pct_complete": 68.4,
    "elapsed_sec": 174
  },
  "galon_active": 1,
  "hmac": "sha256hex_signature"
}
```

### 1.3 Topic: `toyamas/{machine_id}/alarm`
Dikirim **realtime** (event-driven), tidak menunggu interval.

```json
{
  "machine_id": "TYM-001",
  "timestamp": 3190,
  "alarm_type": "GALON_LOW",
  "severity": "WARNING",
  "mode": "RO",
  "detail": { "galon": 2, "level_pct": 18.3, "message": "Galon 2 level rendah, segera isi" },
  "hmac": "sha256hex_signature"
}
```

**alarm_type yang ada di firmware:**
| Value | Severity | Trigger |
|---|---|---|
| `GALON_LOW` | WARNING | level < 20% |
| `GALON_CRITICAL` | WARNING | level < 5% |
| `GALON_EMPTY` | ERROR | level < 1%, atau stok kurang saat DISPENSE diminta |
| `BOTH_GALON_EMPTY` | ERROR | Kedua galon kosong |
| `PUMP_DRY_RUN` | ERROR | Pompa jalan tanpa aliran air terdeteksi (timeout **5 detik**, sebelumnya 8 detik) |
| `SENSOR_FAULT` | ERROR | Sensor tidak merespons |
| `DISPENSE_COMPLETE` | INFO | Pengisian selesai normal |
| `DISPENSE_ABORT` | WARNING | Pengisian dibatalkan / emergency STOP |
| `GALON_SWITCH` | INFO | Auto-switch galon aktif |
| `MODE_CHANGED` | INFO | Ganti mode RO ⇄ MANUAL |
| `GALON_REPLACED` | INFO | Galon terdeteksi diganti/diisi ulang |
| `FILL_TIMEOUT` | ERROR | Pengisian galon dari state `FILLING` melebihi batas aman mutlak `RO_FILL_MAX_TIMEOUT_MS` (10 menit). Ini beda dari timer estimasi blind-zone `RO_FILL_BLIND_ZONE_MS` (3 menit) — timer blind-zone menandai galon **selesai/penuh** (tidak memicu alarm), timer ini khusus jaga-jaga kalau pengisian gagal total (mis. solenoid/RO macet) |

### 1.4 Response PING → PONG
Dipublish ke **topic `status` yang sama** (bukan topic terpisah):
```json
{ "machine_id": "TYM-001", "response": "PONG", "timestamp": 3195, "uptime_sec": 3195, "hmac": "..." }
```
Backend memproses ini lewat handler `status` yang sama (`_process_status()`), field yang tidak ada jatuh ke default kosong — tidak merusak data lain, tapi PONG bukan sumber data status.

---

## 2. Backend → ESP32 (MQTT Subscribe: `toyamas/{machine_id}/command`)

QoS 1. **Setiap** command wajib field `hmac` valid (lihat §11) atau ditolak (`[SEC] HMAC fail`).

```json
{
  "cmd": "DISPENSE", "session_id": "sess_abc123", "order_id": "TYM-1720000000-001",
  "source": "PAYMENT", "volume_liter": 5.0, "issued_at": 1720000000,
  "expires_at": 1720000300, "hmac": "sha256hex_signature"
}
```

| Value | Keterangan | Field wajib |
|---|---|---|
| `DISPENSE` | Mulai keluarkan air. Ditolak jika stok < volume diminta, atau sesi lain sedang jalan. | `session_id`, `volume_liter`, `issued_at`, `hmac` |
| `STOP` | Hentikan dispense paksa, trigger alarm `DISPENSE_ABORT` | `issued_at`, `hmac` |
| `SET_MODE` | `{"mode": "RO"}` atau `{"mode": "MANUAL"}` | `mode`, `issued_at`, `hmac` |
| `RESET` | Soft reset (`ESP.restart()`) setelah 300ms | `issued_at`, `hmac` |
| `PING` | Balasan `PONG` ke topic `status`, lihat §1.4 | `issued_at`, `hmac` |
| `DUMMY_SET_LEVEL` | **Hanya saat `DUMMY_MODE 1`.** `{"g1_pct": 85.0, "g2_pct": 55.0}` — set level ultrasonic dummy manual. **Catatan:** di firmware ini flow meter TIDAK tetap real saat `DUMMY_MODE 1` (lihat §0 poin 1) — command ini cuma mengatur level galon, flow tetap ikut logika simulasi `dummySimulateFlow()` yang berjalan independen | `issued_at`, `hmac` |
| `OTA_ENABLE` | `{"type": "lan"\|"ap", "token": "..."}` — nyalakan OTA LAN (§0.2, auto-disable 5 menit / `OTA_LAN_TIMEOUT_MS`) atau OTA AP (§0.1, auto-disable 15 menit / `OTA_AP_TIMEOUT_MS`) tergantung `type`. `token` harus cocok dengan `OTA_TOKEN` di firmware, terpisah dari HMAC command biasa — kalau tidak cocok, request diabaikan (`[OTA] Invalid token`) | `type`, `token`, `issued_at`, `hmac` |
| `OTA_DISABLE` | `{"type": "lan"\|"ap"\|"all", "token": "..."}` — matikan OTA LAN/AP/keduanya manual sebelum timeout. `token` wajib cocok seperti di atas | `type`, `token`, `issued_at`, `hmac` |

**Tidak ada command `OTA_UPDATE` di firmware ini** (lihat §0.2) — versi dokumen sebelumnya mencatat command ini untuk OTA HTTP lewat internet, tapi tidak pernah ada implementasinya di kode yang jalan.

`OTA_ENABLE`/`OTA_DISABLE` **dipicu dari script terpisah `ota_trigger.py`** (lihat `PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md`), bukan dari dashboard IoT — belum ada UI/endpoint backend untuk ini.

Backend mengirim `DISPENSE`, `STOP`, `RESET`, `PING` lewat `/api/admin/command`
(kiosk) dan `SET_MODE` lewat `POST /api/iot/settings/{machine_id}` (per-mesin)
atau `POST /api/iot/global/settings` (`default_mode`, diterapkan ke semua
mesin aktif) di dashboard IoT — lihat §5. Kedua endpoint itu HANYA menandai
sukses & menyimpan `mode` ke DB kalau publish MQTT-nya benar-benar terkirim;
kalau MQTT client backend disconnect, response error/`mode_warning` yang
dikembalikan, bukan `success: true` palsu. `DUMMY_SET_LEVEL` ada di firmware
tapi masih belum ada trigger dari backend/dashboard.

---

## 3. Backend → UI (WebSocket)

### 3.1 Kiosk WebSocket — `ws://host:8000/ws/{machine_id}`
Dikelola `ws_manager` di `services/mqtt_bridge.py`.

- **`init`** (sekali) — snapshot awal `machine_status` (state, mode, level galon, dsb.)
- **`machine_status`** (~10 detik, tiap status MQTT masuk) — state/mode/level galon/status galon. **Tidak** termasuk `machine_status.total_dispense_today` dkk., `leds`, atau `dummy_level_only` dari payload firmware.
- **`realtime_flow`** (~100ms saat DISPENSING) — `current_liters`, `target_liters`, `pct_complete`, `flow_rate_lpm`, `galon_active`. Selalu data real (lihat §1.2).
- **`payment_confirmed`** — setelah webhook Midtrans sukses, **belum** trigger dispense (`dispense_sent: false`)
- **`payment_failed`** — `{order_id, reason}`
- **`dispense_started`** — setelah UI panggil `/start-dispense`, DISPENSE baru dikirim ke ESP32 di titik ini
- **`dispense_complete`** — dari alarm `DISPENSE_COMPLETE`: `{session_id, actual_liters, duration_sec}`
- **`alarm`** — diteruskan mentah dari MQTT alarm (§1.3)
- **`ticket_verified`** — dari `routes/ticket.py` setelah redeem tiket sukses
- **`config_update`** — dari `routes/iot_settings.py` (`POST /api/iot/settings/{machine_id}`) setiap ada perubahan config mesin (harga, timeout, mode, dst.) lewat dashboard IoT — dipush ke kiosk supaya tampilan langsung ikut update tanpa reload
- **`signage_update`** — dari `routes/iot_settings.py` setiap upload/update/hapus slide signage — dipush daftar slide aktif terbaru (`id`, `media_type`, `url`, `caption`, `order`) ke kiosk

### 3.2 IoT Dashboard WebSocket — `ws://host:8000/ws/iot/{user_id}`
Dikelola `IoTWebSocketManager` di `routes/websocket.py`. **Satu loop broadcast
global** untuk semua admin yang connect (bukan satu loop per admin) — query DB
sekali per tick, hasil di-fan-out ke semua koneksi terbuka, supaya beban DB
tidak berkali lipat kalau banyak tab dashboard dibuka bersamaan. `machine_status`
tiap `IOT_WS_REFRESH_STATUS_SEC` detik (default **2 detik**, `config/settings.py`),
`sales_update` tiap `IOT_WS_REFRESH_SALES_SEC` detik (default **5 detik**, independen dari
interval status) — bukan reaktif per-pesan MQTT.

- **`connected`** (sekali)
- **`machine_status`** — daftar SEMUA mesin: `{machines: [...], summary: {total, online, offline}, timestamp}`. `online` dihitung ulang tiap panggilan dari `last_seen` (`MACHINE_OFFLINE_TIMEOUT_SEC`, default 30 detik), bukan flag mentah database. Tiap mesin bawa `raw_json` (payload `status` MQTT lengkap termasuk `machine_status`, `leds`, `system.dummy_level_only`) — ini sumber data halaman Monitoring.
- **`sales_update`** — `{summary: {...}, recent_transactions: [...], timestamp}`

---

## 4. UI Kiosk → Backend (HTTP REST)

| Endpoint | Fungsi |
|---|---|
| `POST /api/payment/create` | Buat transaksi + charge Midtrans QRIS. Request: `{volume_liter, payment_method, wallet_name, machine_id, kiosk_token}` |
| `POST /api/payment/confirm-dispense` | User klik "Sudah Siap" — **hanya validasi**, belum kirim ke ESP32. Request: `{order_id}` |
| `POST /api/payment/start-dispense` | Setelah countdown UI selesai — **di sinilah** `DISPENSE` benar-benar dikirim. Request: `{order_id}` |
| `GET /api/payment/status/{order_id}` | Polling fallback kalau WebSocket terputus |
| `GET /api/machine/status?machine_id=` | Status mesin untuk render awal kiosk |
| `GET /api/kiosk/session?machine_id=` | QR session token metode tiket, `expires_in` = 7200 detik (120 menit) |
| `GET /api/admin/report/today?admin_pin=` | Laporan harian panel admin kiosk |
| `POST /api/admin/config` | `{machine_id, admin_pin, key, value}` — key: `price_per_liter`, `slide_duration_ms`, `standby_timeout_sec`, `signage_enabled`, `ticker_text` |
| `POST /api/admin/pin` | Ganti PIN admin |
| `POST /api/admin/verify-pin` | Validasi PIN admin mesin — dipakai kiosk untuk buka panel admin tanpa expose PIN ke frontend. Request: `{machine_id, pin}` |
| `POST /api/admin/command` | `{machine_id, admin_pin, cmd, volume_liter?}` — cmd: `STOP`, `RESET`, `PING` |

---

## 5. IoT Dashboard → Backend (HTTP REST — butuh sesi admin)

**Auth:** Login dashboard IoT memakai **username + password** (bcrypt), BUKAN Google OAuth — migration 004 (`admins.password_hash`). `POST /auth/login` (body `{username, password}`) → `{token, username, name, role, expires_in}`, token JWT dipakai sebagai `Authorization: Bearer {token}` untuk semua endpoint `/api/iot/*` di bawah. Juga: `GET /auth/me`, `GET /auth/check`, `POST /auth/logout`, `POST /auth/refresh`, `POST /auth/change-password` (body `{username, old_password, new_password}`, hanya untuk diri sendiri), `POST /auth/reset-password` (body `{username, new_password}`, hanya `role: super_admin` boleh reset password admin lain). Akun pertama dibuat lewat script `backend/create_admin.py` (username `admin`, password default `toyamas123`, wajib diganti — lihat `SETUP_GUIDE.md` §3.3/§8).

**Data** (semua butuh `require_admin`):
| Endpoint | Fungsi |
|---|---|
| `GET /api/iot/dashboard?machine_id=` | Semua data dashboard sekaligus |
| `GET /api/iot/machines` | `{"machines": [...]}` |
| `POST /api/iot/machines` | Daftarkan mesin baru — body `{machine_id, name, admin_pin, location?, price_per_liter?, mode?, secret?}`, response berisi `secret` HMAC unik yang harus disalin ke firmware (§11) |
| `DELETE /api/iot/machines/{machine_id}` | Soft-delete mesin (`is_active=0`, migration 007) — mesin hilang dari `/api/iot/machines`, dropdown, dan peta lokasi, tapi baris di tabel `machines` TETAP ADA sehingga riwayat transaksi/laporan lama tetap tampil apa adanya. `machine_id` yang sudah dihapus tidak bisa dipakai ulang untuk mesin baru |
| `GET /api/iot/machines/{id}/status` | `{online, last_seen, seconds_since_last_seen}` |
| `GET /api/iot/machines/{id}/secret` | Lihat ulang `secret` HMAC mesin (kalau lupa dicatat saat registrasi) |
| `GET /api/iot/charts?chart_type=hourly\|weekly\|monthly` | `{type, labels, datasets: {volume, transactions, revenue}}` |
| `GET /api/iot/transactions?page=&limit=&status=&source=&start_date=&end_date=` | `{transactions: [...], pagination: {...}}` |
| `GET /api/iot/summary?period=today\|week\|month` | `{transactions, volume_liters, revenue, payment_count, ticket_count, avg_volume_per_trx, avg_revenue_per_trx, period}` |
| `GET/POST /api/iot/locations[/{id}]` | Lokasi mesin di peta (Leaflet + geocoding Nominatim). Tidak ada `DELETE` di sini — hapus mesin dilakukan lewat `DELETE /api/iot/machines/{machine_id}` di atas, bukan lewat path `/locations/{id}` |
| `GET /api/iot/global/settings` | `{default_price, default_mode}` — nilai default armada (tabel `app_config`, migration 009) |
| `POST /api/iot/global/settings` | Terapkan `default_price` dan/atau `default_mode` ke **semua mesin aktif** sekaligus. Untuk `default_mode`: mengirim `SET_MODE` ke tiap mesin (bukan cuma tulis DB — lihat §2); `affected_machines` di response = jumlah mesin yang perintahnya **benar-benar terkirim**, bukan sekadar jumlah mesin aktif |
| `GET /api/iot/settings/{machine_id}` | Config + slide signage satu mesin: `{config: {price_per_liter, standby_timeout_sec, slide_duration_ms, signage_enabled, mode}, slides: [...], machine: {...}}` |
| `POST /api/iot/settings/{machine_id}` | Update satu/lebih field di atas. `mode` dipisah dari field lain — publish `SET_MODE` dulu, DB `machines.mode` hanya diupdate kalau publish sukses (lihat §2). Response bisa `503` (mode gagal & tidak ada field lain), atau `{success, mode_warning}` (mode gagal tapi field lain tersimpan) |
| `POST /api/iot/settings/{machine_id}/pin` | Ganti PIN admin mesin — body `{old_pin, new_pin, confirm_pin}`, verifikasi PIN lama di server (bukan client-side) |
| `POST /api/iot/settings/{machine_id}/signage` | Upload slide baru (multipart) — `file` (JPG/PNG maks 5MB atau MP4 maks 100MB), `caption?`, `order?` |
| `PATCH /api/iot/settings/{machine_id}/signage/{slide_id}` | Update `slide_order` atau `is_active` |
| `DELETE /api/iot/settings/{machine_id}/signage/{slide_id}` | Hapus slide (file fisik + record DB) |

---

## 6. Aplikasi User → Backend (Ticket Redeem)

`POST /api/ticket/redeem` — dikirim aplikasi smartphone, bukan kiosk.
```json
// Request:  {ticket_code, session_token, user_jwt, machine_id}
// Response: {success: true, ticket_code, volume_liter, order_id, message}
```
**error values:** `SESSION_EXPIRED` | `MACHINE_MISMATCH` | `USER_AUTH_INVALID` | `TICKET_NOT_FOUND` | `TICKET_ALREADY_USED` | `TICKET_EXPIRED` | `USER_MISMATCH` | `GALON_INSUFFICIENT` | `SESSION_ALREADY_USED` | `CLOUD_UNAVAILABLE`

> **Status implementasi:** validasi sungguhan lewat Cloudflare Worker eksternal (`CF_TICKET_REDEEM_URL`/`CF_API_TOKEN`). Selama kosong di `.env` (default), backend jatuh ke simulasi lokal — kode harus awalan `TYM-`, volume dari digit terakhir (`...1`→5L, `...2`→10L, `...3`→15L, `...4`→19L, lainnya→5L).

---

## 7. Backend → Midtrans

`POST {MIDTRANS_BASE_URL}/v2/charge` (`sandbox` kecuali `MIDTRANS_IS_SANDBOX=false`), `Authorization: Basic {Base64(MIDTRANS_SERVER_KEY:)}`, payment_type `qris`, acquirer `gopay`.

## 8. Midtrans → Backend (Webhook)

`POST /api/payment/notify` — verifikasi `SHA512(order_id + status_code + gross_amount + MIDTRANS_SERVER_KEY)` dengan `hmac.compare_digest`. `PAID`: `settlement`/`capture`. `FAILED`: `deny`/`cancel`/`expire`/`failure`. Idempotent, **tidak langsung dispense** (lihat §12).

---

## 9. Database Schema — SQLite Lokal

- **`machines`** — identitas, PIN, `firmware_ver`, `online`, `last_seen`, `mode` (RO/MANUAL) + kolom lokasi (migration 002) + `secret` (migration 006, HMAC per-mesin — lihat §11) + `is_active` (migration 007, soft-delete)
- **`machine_config`** — key-value per mesin (`price_per_liter`, `standby_timeout_sec`, `slide_duration_ms`, `signage_enabled`, dst)
- **`machine_signage_slides`** (migration 008) — slide gambar/video kiosk per mesin: `slide_order`, `media_type`, `file_path`, `caption`, `is_active`
- **`app_config`** (migration 009) — key-value global (bukan per-mesin): `default_price`, `default_mode` — dipakai halaman Pengaturan Global dashboard IoT (§5)
- **`transactions`** — semua transaksi PAYMENT/TICKET, status pembayaran & dispense
- **`sensor_logs`** — histori status per 10 detik (termasuk `solenoid_pump1/2`)
- **`alarms`** — log semua alarm
- **`kiosk_sessions`** — token QR metode tiket
- **`machine_state_cache`** — 1 baris per mesin, cache status MQTT terakhir + `raw_json` (sumber data Monitoring, termasuk `dummy_level_only`)
- **`admins`** — login dashboard IoT (migration 004)
- **`sales_hourly`** — agregat per jam, timezone-aware (migration 003 + 005)
- **`schema_migrations`** — tracking migration mana yang sudah diterapkan (001–009, dijalankan otomatis berurutan tiap startup)

## 10. Cloudflare D1 — KOMPONEN OPSIONAL/EKSTERNAL
Tidak termasuk repo ini. Tabel `users`/`tickets`/`transactions_sync` hidup di Worker+D1 terpisah, dikonfigurasi lewat `CF_*` di `.env`. Kosong = mode simulasi lokal (§6).

## 11. HMAC Signature Scheme

**MQTT ESP32→Backend:** `HMAC-SHA256(JSON tanpa field "hmac", key="{machine_id}:{secret}")`
**Command Backend→ESP32:** `HMAC-SHA256("{cmd}:{session_id}:{volume_liter:.3f}:{issued_at}", key="{machine_id}:{secret}")` — default `session_id=""`, `volume_liter=0.0` untuk command yang tidak butuh (STOP/RESET/PING), tapi **field `hmac` tetap wajib ada**.

**`secret` per mesin (migration 006), BUKAN satu `MACHINE_SECRET` global untuk semua mesin.**
Setiap `machine_id` bisa punya HMAC secret sendiri, disimpan di kolom `machines.secret`
dan di-generate otomatis (`secrets.token_hex(16)`, 32 hex char acak) saat mesin
didaftarkan lewat `POST /api/iot/machines`. Backend menurunkan key HMAC lewat
`get_machine_secret(machine_id)` (`services/database.py`): kalau mesin punya
`secret` sendiri, itu yang dipakai; kalau kolomnya `NULL` (mesin lama yang
terdaftar sebelum migration 006 ada, mis. `TYM-001` dari seed `001_init.sql`),
fallback ke `MACHINE_SECRET` di `.env` backend.

Alasan per-mesin: `machine_id` itu publik (ada di topic MQTT), jadi kalau semua
mesin pakai secret yang sama, membongkar firmware **satu** unit ESP32 saja
cukup untuk menghitung HMAC valid dan mengaku jadi mesin lain — termasuk
memalsukan command STOP/DISPENSE ke mesin yang tidak dibongkar. Dengan secret
unik per mesin, membongkar satu unit cuma membahayakan unit itu sendiri.

Field `hmac` firmware unit tersebut (`const char* MACHINE_SECRET` di `.ino`)
harus identik string-nya dengan nilai yang dipakai backend untuk `machine_id`
itu — untuk mesin dengan secret sendiri, ambil dari respons
`POST /api/iot/machines` atau `GET /api/iot/machines/{machine_id}/secret`;
untuk mesin fallback, dari `MACHINE_SECRET` di `.env`. Lihat SETUP_GUIDE.md §3.6.

## 12. Ringkasan Alur

```
METODE A (Kiosk QRIS) — 2 tahap konfirmasi:
create → Midtrans charge → PENDING
  → webhook notify (SHA512 verify) → PAID → WS payment_confirmed (dispense_sent=false)
  → user klik "Sudah Siap" → POST confirm-dispense (validasi saja) → countdown UI ~10 detik
  → POST start-dispense → MQTT DISPENSE (dgn HMAC) → WS dispense_started
  → ESP32 DISPENSING (flow real terus, level dummy ikut turun kalau DUMMY_MODE)
  → MQTT flow ~100ms → WS realtime_flow → animasi kiosk
  → alarm DISPENSE_COMPLETE → WS dispense_complete → SQLite COMPLETE

METODE B (Tiket App):
kiosk session QR → app scan → redeem (verify session+user JWT, validasi tiket
cloud/simulasi, cek galon) → SQLite transaction TICKET → WS ticket_verified
→ MQTT DISPENSE langsung (tanpa tahap countdown seperti Metode A)
```