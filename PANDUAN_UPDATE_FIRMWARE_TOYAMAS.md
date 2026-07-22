# Panduan Update Firmware Toyamas (sinkron dengan `1.4.3-http-ota`)

Ada **4 cara** untuk memasukkan firmware baru ke ESP32 Toyamas. Pilih sesuai situasi:

| Metode | Kapan Dipakai | Butuh Apa | Tingkat Repot |
|---|---|---|---|
| **A. Kabel USB** | Flash pertama kali / development di meja | Kabel USB, laptop di lokasi device | Rendah (tapi harus di tempat) |
| **B. OTA HTTP (internet)** | Kios di lokasi manapun, termasuk jauh dari admin | Server hosting `.bin`, koneksi internet device | Sedang (sekali setup, selanjutnya tinggal trigger) |
| **C. OTA LAN (ArduinoOTA)** | Kios 1 jaringan WiFi dengan laptop admin | Laptop & device satu jaringan | Rendah |
| **D. OTA AP (fallback)** | Internet/WiFi kios mati total, darurat | Teknisi hadir fisik di lokasi | Sedang |

---

## 0. Persiapan Umum (sekali di awal, berlaku untuk semua metode)

1. **Partition Scheme harus mendukung OTA.** Di Arduino IDE: `Tools → Partition Scheme` → pilih yang ada tulisan "with OTA" (mis. *Minimal SPIFFS (1.9MB APP with OTA)* atau *Default 4MB with spiffs*). Kalau salah pilih skema tanpa OTA, baik `Update.begin()` (OTA HTTP/AP) maupun `ArduinoOTA` (OTA LAN) akan **gagal total** — device cuma punya 1 partisi app, tidak ada slot kedua untuk firmware baru.
2. **Naikkan `FIRMWARE_VERSION`** di kode sebelum compile, supaya kamu bisa lacak versi mana yang jalan di tiap kios (`sys.firmware_ver` muncul di `publishStatus`).
3. Install `paho-mqtt` kalau mau pakai script trigger:
   ```bash
   pip install paho-mqtt
   ```
4. **Kalau ini FIRMWARE UNTUK UNIT BARU** (mesin yang belum pernah online, bukan sekadar update firmware unit yang sudah jalan) — pastikan dulu `MACHINE_ID` dan `MACHINE_SECRET` di kode sudah benar SEBELUM compile:
   - `MACHINE_ID` harus sama persis dengan yang didaftarkan lewat `POST /api/iot/machines` (dashboard IoT → "+ Tambah Mesin").
   - `MACHINE_SECRET` harus nilai `secret` UNIK dari respons registrasi tersebut — **bukan** string `MACHINE_SECRET` yang ada di `.env` backend. Kalau salah pakai (atau lupa ganti dari nilai default di sketch lama), unit akan gagal terverifikasi backend (`[SEC] HMAC fail` di Serial Monitor / `HMAC MISMATCH` di log backend) meski WiFi & MQTT-nya konek normal.
   - Detail lengkap + alasan kenapa tiap mesin butuh secret sendiri (bukan satu secret untuk semua): lihat `SETUP_GUIDE.md` §3.6.

---

## A. Update via Kabel USB (Wired)

Cara paling dasar — dipakai untuk flash pertama kali sebelum device dipasang, atau saat development di meja kerja.

1. Colokkan ESP32 ke laptop via USB.
2. Arduino IDE → `Tools → Board` → pilih **ESP32 Dev Module**.
3. `Tools → Port` → pilih port USB (`COM3`, `/dev/ttyUSB0`, dst — port serial biasa, **bukan** network port).
4. `Tools → Partition Scheme` → pastikan yang OTA-enabled (lihat bagian 0).
5. **Unit baru (belum pernah online)?** Cek ulang `MACHINE_ID`/`MACHINE_SECRET` di kode sesuai bagian 0 poin 4 — ini SATU-SATUNYA kesempatan gampang mengubahnya (setelah dipasang di lokasi, ganti-ganti lewat OTA lebih ribet daripada USB langsung).
6. Klik **Upload** (ikon panah). Kalau gagal connect, tahan tombol **BOOT** di board saat proses "Connecting..." muncul di bawah.
7. Selesai, buka **Serial Monitor** (baud 115200) untuk lihat banner startup dan pastikan versi firmware benar.

---

## B. OTA HTTP — Internet, Pull-based (untuk kios di lokasi manapun)

Ini metode **utama** untuk kios yang lokasinya jauh dari kamu.

### Langkah:

**1. Compile & export firmware jadi file `.bin`**
Arduino IDE → `Sketch → Export Compiled Binary`. File `.bin` muncul di folder sketch (nama biasanya `<nama_sketch>.ino.esp32.bin`).

**2. Upload file `.bin` ke server**
Taruh di endpoint FastAPI yang serve file statis (mis. `https://server-kamu.com/firmware/toyamas_v1.4.4.bin`). Pastikan response-nya mengirim header `Content-Length` — kalau pakai `FileResponse` dari FastAPI, ini otomatis.

**3. Hitung MD5 file `.bin`**
```bash
md5sum toyamas_v1.4.4.bin
```
Simpan hasilnya (32 karakter hex) — ini yang memastikan firmware tidak korup/berubah saat proses download.

**4. Buka monitor di satu terminal**
```bash
python3 ota_trigger.py watch
```

**5. Trigger update di terminal lain**
```bash
python3 ota_trigger.py http \
  --url https://server-kamu.com/firmware/toyamas_v1.4.4.bin \
  --version 1.4.4 \
  --md5 6f1ed002ab5595859014ebf0951522d9
```

**6. Yang terjadi di device (bisa dipantau lewat `watch`):**
- `OTA_HTTP_PROGRESS` — persentase naik tiap ~2 detik
- `OTA_HTTP_SUCCESS` — download selesai, MD5 cocok, device restart otomatis
- Status berikutnya (`publishStatus`) menunjukkan `system.firmware_ver` sudah versi baru

### Kalau gagal, cek `OTA_HTTP_FAILED` messages:
| Pesan | Penyebab | Solusi |
|---|---|---|
| `WiFi tidak terhubung` | Device offline | Cek koneksi WiFi kios |
| `HTTP GET gagal, kode 4xx/5xx` | URL salah / server down | Cek URL bisa diakses via browser dulu |
| `Content-Length tidak valid` | Server tidak kirim header ini | Pastikan pakai static file serving biasa, bukan streaming/chunked |
| `Update.begin gagal` | Partisi OTA tidak cukup/tidak ada | Cek Partition Scheme (lihat bagian 0) |
| `Verifikasi firmware gagal ... MD5 tidak cocok` | MD5 yang dikirim salah, atau file korup di server | Hitung ulang `md5sum`, upload ulang file |
| `Timeout saat download` | Internet kios lambat/putus | Coba lagi saat koneksi lebih stabil, atau kompres/perkecil ukuran `.bin` |
| Update sudah berjalan, command diabaikan | Ada OTA lain sedang proses | Tunggu selesai/restart, baru trigger lagi |

---

## C. OTA LAN (ArduinoOTA) — device 1 jaringan dengan laptop

Untuk kios yang **kebetulan** satu jaringan WiFi dengan kamu (mis. testing di kantor/rumah). **Bukan** untuk kios jarak jauh — ArduinoOTA butuh laptop & device di jaringan yang sama.

### Langkah:

**1. Aktifkan (auto-mati sendiri setelah 5 menit)**
```bash
python3 ota_trigger.py lan-enable
```

**2. Di laptop yang SATU JARINGAN dengan device:**
Arduino IDE → `Tools → Port` → cari network port **`toyamas-tym001 at 192.168.x.x`**.

> Kalau port ini tidak muncul: device & laptop belum satu subnet WiFi, atau 5 menit sudah lewat (enable ulang). Kalau tetap tidak muncul, pakai Metode B.

**3. Klik Upload** seperti biasa. IDE akan minta password → isi `toyamas-ota-secure-2024`.

**4. Alternatif command-line** (tanpa buka Arduino IDE), pakai `espota.py`:
```bash
python3 espota.py -i 192.168.x.x -p 3232 --auth=toyamas-ota-secure-2024 -f firmware.bin
```
(File `espota.py` ada di folder `~/.arduino15/packages/esp32/hardware/esp32/<versi>/tools/`)

**5. Matikan manual kalau sudah selesai (opsional, nanti mati sendiri juga):**
```bash
python3 ota_trigger.py lan-disable
```

---

## D. OTA AP — Fallback Offline (darurat, tanpa internet)

Untuk situasi internet/WiFi kios mati total. **Butuh teknisi hadir fisik** di lokasi.

### Langkah:

**1. Aktifkan** (pilih salah satu):
- **Remote** (kalau device masih ada internet tapi mau siapkan dulu sebelum ke lokasi):
  ```bash
  python3 ota_trigger.py ap-enable
  ```
- **Manual di lokasi** (kalau internet sudah benar-benar mati): tekan tombol **RESET 5x dalam 10 detik**. Device akan bunyi 3x beep sebagai konfirmasi aktif.

**2. Sambungkan HP/laptop teknisi ke WiFi `TOYAMAS-OTA`**, password `toyamas123`.

**3. Buka browser ke `http://192.168.4.1/`** — muncul halaman upload bawaan firmware.

**4. Pilih file `.bin`, klik Upload & Update.** Device flash lalu restart otomatis. AP ini aktif 15 menit lalu mati sendiri kalau tidak dipakai.

---

## Checklist Sebelum Update ke Banyak Kios Sekaligus

1. **Test dulu di 1 device** (idealnya yang gampang dijangkau) sebelum rollout ke semua kios.
2. Pastikan device dalam kondisi **idle** (tidak sedang dispensing) — proses OTA otomatis memanggil `deactivateAll()`, tapi lebih aman kalau memang tidak ada transaksi berjalan.
3. Simpan `.bin` versi lama minimal 1 rilis ke belakang, buat jaga-jaga kalau versi baru bermasalah dan perlu di-downgrade lewat USB.
4. Untuk OTA HTTP, cek dulu URL bisa diakses (`curl -I <url>` — pastikan status 200 dan ada header `Content-Length`) sebelum kirim ke banyak device sekaligus.
5. Catat MD5 & versi tiap rilis di satu tempat (spreadsheet/README), supaya gampang lacak kios mana sudah update ke versi berapa.

---

## Catatan Keamanan

Broker `broker.emqx.io` bersifat publik tanpa autentikasi — command MQTT (termasuk `OTA_UPDATE`) bisa dilihat siapa saja yang subscribe ke topic yang sama. Untuk kios yang sudah full produksi, pertimbangkan pindah ke broker privat (EMQX Cloud/HiveMQ Cloud dengan user/pass, atau Mosquitto self-hosted + TLS).

**Soal HMAC secret:** sejak migration 006, tiap mesin bisa punya `MACHINE_SECRET` sendiri (bukan satu secret yang sama untuk semua unit — lihat `PAYLOAD_SPEC.md` §11 dan `SETUP_GUIDE.md` §3.6). Ini membatasi dampak kalau satu unit ESP32 dibongkar/firmware-nya diekstrak: penyerang cuma bisa memalsukan data/command **unit itu saja**, tidak bisa dipakai untuk mengaku jadi mesin lain di armada.

Yang HMAC (per-mesin atau global) **belum** lindungi: **replay** — command lama yang berhasil ditangkap di broker publik bisa dikirim ulang apa adanya (HMAC-nya tetap valid karena isi payload tidak berubah). Command DISPENSE sudah punya `expires_at` (5 menit dari `issued_at`) yang membatasi jendela replay-nya sedikit, tapi STOP/RESET/PING belum ada mekanisme serupa. Untuk mitigasi penuh, perlu nonce/sequence number yang dicatat & ditolak kalau terulang — belum diimplementasikan di versi ini.
