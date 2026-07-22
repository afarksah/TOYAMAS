# Panduan Update Firmware Toyamas (sinkron dengan `1.5.0-ota-lan-ap`)

Ada **3 cara** untuk memasukkan firmware baru ke ESP32 Toyamas. Pilih sesuai situasi:

| Metode | Kapan Dipakai | Butuh Apa | Tingkat Repot |
|---|---|---|---|
| **A. Kabel USB** | Flash pertama kali / development di meja | Kabel USB, laptop di lokasi device | Rendah (tapi harus di tempat) |
| **B. OTA LAN (ArduinoOTA)** | Kios 1 jaringan WiFi dengan laptop admin | Laptop & device satu jaringan | Rendah |
| **C. OTA AP (fallback)** | Internet/WiFi kios mati total, darurat | Teknisi hadir fisik di lokasi | Sedang |

> **Catatan:** Firmware `1.5.0-ota-lan-ap` **belum punya OTA HTTP (pull dari server jarak jauh)**. Command MQTT yang didukung firmware ini hanya: `DISPENSE`, `STOP`, `SET_MODE`, `RESET`, `PING`, `OTA_ENABLE`, `OTA_DISABLE`. Kalau butuh update kios yang jaraknya jauh dan tidak bisa didatangi teknisi, saat ini satu-satunya opsi realistis adalah **OTA LAN** kalau device bisa diakses lewat VPN/tunnel ke jaringan yang sama, atau kirim teknisi untuk **USB**/**OTA AP**. OTA HTTP bisa jadi pengembangan berikutnya kalau dibutuhkan.

---

## 0. Persiapan Umum (sekali di awal, berlaku untuk semua metode)

1. **Partition Scheme harus mendukung OTA.** Di Arduino IDE: `Tools → Partition Scheme` → pilih yang ada tulisan "with OTA" (mis. *Minimal SPIFFS (1.9MB APP with OTA)* atau *Default 4MB with spiffs*). Kalau salah pilih skema tanpa OTA, baik `ArduinoOTA` (Metode B) maupun `Update.begin()` (Metode C) akan **gagal total** — device cuma punya 1 partisi app, tidak ada slot kedua untuk firmware baru.
2. **Naikkan `FIRMWARE_VERSION`** di kode sebelum compile, supaya kamu bisa lacak versi mana yang jalan di tiap kios (`sys.firmware_ver` muncul di `publishStatus`).
3. **🔴 Cek dulu: MQTT broker sekarang HiveMQ Cloud (TLS).**
   Konfigurasi saat ini di kode:
   ```cpp
   const char* MQTT_BROKER = "a5507a637f2647c1befeb61705d81f04.s1.eu.hivemq.cloud";
   const int   MQTT_PORT   = 8883;   // port TLS
   onst char* MQTT_USER      = "";
   const char* MQTT_PASS      = "";

   ```
   
4. Install `paho-mqtt` kalau mau pakai script trigger:
   ```bash
   pip install paho-mqtt
   ```
5. **Kalau ini FIRMWARE UNTUK UNIT BARU** (mesin yang belum pernah online, bukan sekadar update firmware unit yang sudah jalan) — pastikan dulu `MACHINE_ID` dan `MACHINE_SECRET` di kode sudah benar SEBELUM compile:
   - `MACHINE_ID` harus sama persis dengan yang didaftarkan lewat `POST /api/iot/machines` (dashboard IoT → "+ Tambah Mesin").
   - `MACHINE_SECRET` harus nilai `secret` UNIK dari respons registrasi tersebut — **bukan** string `MACHINE_SECRET` yang ada di `.env` backend. Kalau salah pakai (atau lupa ganti dari nilai default di sketch lama), unit akan gagal terverifikasi backend (`[SEC] HMAC fail` di Serial Monitor / `HMAC MISMATCH` di log backend) meski WiFi & MQTT-nya konek normal.
   - Detail lengkap + alasan kenapa tiap mesin butuh secret sendiri (bukan satu secret untuk semua): lihat `SETUP_GUIDE.md`.

---

## A. Update via Kabel USB (Wired)

Cara paling dasar — dipakai untuk flash pertama kali sebelum device dipasang, atau saat development di meja kerja.

1. Colokkan ESP32 ke laptop via USB (buka case box controller).
2. Arduino IDE → `Tools → Board` → pilih **ESP32 Dev Module**.
3. `Tools → Port` → pilih port USB (`COM3`, `/dev/ttyUSB0`, dst — port serial biasa, **bukan** network port).
4. `Tools → Partition Scheme` → pastikan yang OTA-enabled (lihat bagian 0).
5. **Unit baru (belum pernah online)?** Cek ulang `MACHINE_ID`/`MACHINE_SECRET` di kode sesuai bagian 0 poin 5 — ini SATU-SATUNYA kesempatan gampang mengubahnya (setelah dipasang di lokasi, ganti-ganti lewat OTA lebih ribet daripada USB langsung).
6. Klik **Upload** (ikon panah). Kalau gagal connect, tahan tombol **BOOT** di board saat proses "Connecting..." muncul di bawah.
7. Selesai, buka **Serial Monitor** (baud 115200) untuk lihat banner startup dan pastikan versi firmware benar.

---

## B. OTA LAN (ArduinoOTA) — device 1 jaringan dengan laptop

Untuk kios yang **kebetulan** satu jaringan WiFi dengan kamu (mis. testing di kantor/rumah). **Bukan** untuk kios jarak jauh — ArduinoOTA butuh laptop & device di jaringan yang sama.

### Cara aktivasi (pilih salah satu):
- **Via MQTT:** kirim command `OTA_ENABLE` dengan `type: "lan"` + `token` yang cocok dengan `OTA_TOKEN` di firmware (`TYM-OTA-VERIFY-2024`), lewat `ota_trigger.py` atau publish manual ke topic command.
- **Langsung di device:** tekan tombol **MODE 6x cepat dalam 10 detik**. Device akan beep 2x sebagai konfirmasi aktif.

Auto-mati sendiri setelah **5 menit** kalau tidak dipakai.

### Langkah lanjutan:

**1. Di laptop yang SATU JARINGAN dengan device:**
Arduino IDE → `Tools → Port` → cari network port **`toyamas-tym001 at 192.168.x.x`**.

> Kalau port ini tidak muncul: device & laptop belum satu subnet WiFi, atau 5 menit sudah lewat (aktivasi ulang). Kalau tetap tidak muncul, pakai Metode A (USB) atau C (AP).

**2. Klik Upload** seperti biasa. IDE akan minta password → isi `toyamas-ota-secure-2024`.

**3. Alternatif command-line** (tanpa buka Arduino IDE), pakai `espota.py`:
```bash
python3 espota.py -i 192.168.x.x -p 3232 --auth=toyamas-ota-secure-2024 -f firmware.bin
```
(File `espota.py` ada di folder `~/.arduino15/packages/esp32/hardware/esp32/<versi>/tools/`)

**4. Matikan manual kalau sudah selesai** (opsional, nanti mati sendiri juga):
```bash
python3 ota_trigger.py lan-disable
```

**Catatan safety:** begitu update LAN OTA mulai (`ArduinoOTA.onStart()`), firmware otomatis memanggil `deactivateAll()` — pompa/solenoid/UV mati semua secara otomatis, tidak perlu tindakan manual.

---

## C. OTA AP — Fallback Offline (darurat, tanpa internet)

Untuk situasi internet/WiFi kios mati total. **Butuh teknisi hadir fisik** di lokasi.

### Cara aktivasi (pilih salah satu):
- **Remote** (kalau device masih ada internet tapi mau siapkan dulu sebelum ke lokasi): kirim command `OTA_ENABLE` dengan `type: "ap"` + `token` yang cocok, lewat `ota_trigger.py ap-enable` atau publish manual.
- **Manual di lokasi** (kalau internet sudah benar-benar mati): tekan tombol **MODE 3x cepat dalam 5 detik**. Device akan bunyi 3x beep sebagai konfirmasi aktif.

### Langkah:

**1.** Sambungkan HP/laptop teknisi ke WiFi `TOYAMAS-OTA`, password `toyamas123`.

**2.** Buka browser ke `http://192.168.4.1/` — muncul halaman upload bawaan firmware.

**3.** Pilih file `.bin`, klik Upload & Update. Device flash lalu restart otomatis. AP ini aktif **15 menit** lalu mati sendiri kalau tidak dipakai.

⚠️ **Catatan safety penting:** berbeda dari OTA LAN, jalur AP OTA (`handleOTAAPUpdate`) **tidak** otomatis memanggil `deactivateAll()` saat upload dimulai. Kalau ada dispensing yang sedang berjalan pas upload dimulai, pompa/solenoid berpotensi masih menyala selama proses flashing. **Pastikan device benar-benar idle (tidak sedang dispensing) sebelum mulai upload AP OTA** — cek dulu lewat status LED atau Serial Monitor kalau memungkinkan.

---

## Checklist Sebelum Update ke Banyak Kios Sekaligus

1. **Test dulu di 1 device** (idealnya yang gampang dijangkau) sebelum rollout ke semua kios.
2. Pastikan device dalam kondisi **idle** (tidak sedang dispensing) sebelum mulai update — untuk OTA LAN ini di-enforce otomatis (`deactivateAll()` di `onStart`), tapi untuk **OTA AP harus dicek manual** (lihat catatan safety di atas).
3. Simpan `.bin` versi lama minimal 1 rilis ke belakang, buat jaga-jaga kalau versi baru bermasalah dan perlu di-downgrade lewat USB.
4. Catat MD5 & versi tiap rilis di satu tempat (spreadsheet/README), supaya gampang lacak kios mana sudah update ke versi berapa — meski firmware ini belum verifikasi MD5 otomatis (khusus OTA HTTP yang belum ada), tetap berguna buat tracking manual.

---

## Catatan Keamanan

**Soal HMAC secret:** sejak migration 006, tiap mesin bisa punya `MACHINE_SECRET` sendiri (bukan satu secret yang sama untuk semua unit — lihat `PAYLOAD_SPEC.md` dan `SETUP_GUIDE.md`). Ini membatasi dampak kalau satu unit ESP32 dibongkar/firmware-nya diekstrak: penyerang cuma bisa memalsukan data/command **unit itu saja**, tidak bisa dipakai untuk mengaku jadi mesin lain di armada.

**Soal OTA token:** aktivasi OTA lewat MQTT (`OTA_ENABLE`/`OTA_DISABLE`) butuh `token` yang cocok dengan `OTA_TOKEN` di firmware, terpisah dari HMAC command biasa. Pastikan script trigger yang dipakai tim menyertakan token ini.

Yang HMAC (per-mesin atau global) **belum** lindungi: **replay** — command lama yang berhasil ditangkap di broker bisa dikirim ulang apa adanya (HMAC-nya tetap valid karena isi payload tidak berubah). Command DISPENSE sudah punya `expires_at` (5 menit dari `issued_at`) yang membatasi jendela replay-nya sedikit, tapi STOP/RESET/PING belum ada mekanisme serupa. Untuk mitigasi penuh, perlu nonce/sequence number yang dicatat & ditolak kalau terulang — belum diimplementasikan di versi ini.
