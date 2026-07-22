#!/usr/bin/env python3
"""
toyamas_mqtt_simulator.py  —  v2.0 (realistic simulation)
=============================================================
Simulator MQTT untuk TOYAMAS Dispenser — meniru perilaku firmware
dengan siklus pengisian otomatis, blind zone ultrasonik, dan
estimasi berbasis flow meter.

Fitur baru:
- Auto-fill (RO) saat galon < 10%
- Blind zone: sensor tidak valid di atas 60% level
- Estimasi level saat blind zone (timer saat fill, flow meter saat dispense)
- State FILLING, DISPENSING, IDLE, ERROR
"""

import os
import sys
import json
import time
import hmac
import random
import hashlib
import threading
import argparse

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Modul 'paho-mqtt' belum terpasang.")
    print("Install dulu dengan: pip install paho-mqtt --break-system-packages")
    sys.exit(1)


# ════════════════════════════════════════════════════════
# KONFIGURASI — sesuaikan dengan firmware & dashboard
# ════════════════════════════════════════════════════════

MQTT_BROKER = os.environ.get("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT   = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER   = os.environ.get("MQTT_USER", "")
MQTT_PASS   = os.environ.get("MQTT_PASS", "")

FIRMWARE_VERSION = "1.4.3-http-ota"

# Daftar mesin virtual
MACHINES = [
    {"machine_id": "TYM-001", "secret": "toyamas-esp32-hmac-secret",     "g1_pct": 85.0, "g2_pct": 55.0},
    {"machine_id": "TYM-002", "secret": "7b43eee341c86d821eb97d1815984254", "g1_pct": 40.0, "g2_pct": 90.0},
    {"machine_id": "TYM-003", "secret": "cb7b30cfd2967ddaa0420b8901006410", "g1_pct": 15.0, "g2_pct": 65.0},
]

# Konstanta fisik — disalin dari firmware .ino
GALON_CAPACITY_L       = 19.0
GALON_MAX_HEIGHT_CM    = 45.0
SENSOR_MOUNT_HEIGHT_CM = 50.0
MIN_SENSOR_DIST_CM     = 23.0   # blind zone mulai dari jarak ini
GALON_LOW_PCT          = 20.0
GALON_CRITICAL_PCT     = 5.0
GALON_EMPTY_PCT        = 1.0
GALON_REFILL_THRESHOLD = 10.0   # mulai isi ulang di bawah ini
GALON_FILL_THRESHOLD   = 95.0   # berhenti isi di atas ini

# Laju aliran (realistis)
FILL_FLOW_RATE_LPM     = 1.5    # kecepatan isi RO (liter/menit)
DISPENSE_FLOW_RATE_LPM = 2.0    # kecepatan dispensing

# Blind zone: ketinggian air saat sensor mulai tidak valid
BLIND_ZONE_HEIGHT_CM   = SENSOR_MOUNT_HEIGHT_CM - MIN_SENSOR_DIST_CM   # 27 cm
BLIND_ZONE_PCT         = (BLIND_ZONE_HEIGHT_CM / GALON_MAX_HEIGHT_CM) * 100.0   # ~60%

# Timer untuk blind zone saat filling (kalibrasi manual)
RO_FILL_BLIND_ZONE_MS  = 180000   # 3 menit (contoh, sesuai firmware)
RO_FILL_MAX_TIMEOUT_MS = 600000   # 10 menit

ALARM_THROTTLE_SEC     = 30

# Interval publish
STATUS_INTERVAL_SEC    = 3
FLOW_INTERVAL_SEC      = 0.5
TICK_SEC               = 0.5

# ALARM_TABLE
ALARM_TABLE = [
    ("GALON_LOW",         "WARNING"),
    ("GALON_CRITICAL",    "WARNING"),
    ("GALON_EMPTY",       "ERROR"),
    ("BOTH_GALON_EMPTY",  "ERROR"),
    ("PUMP_DRY_RUN",      "ERROR"),
    ("SENSOR_FAULT",      "ERROR"),
    ("DISPENSE_COMPLETE", "INFO"),
    ("DISPENSE_ABORT",    "WARNING"),
    ("GALON_SWITCH",      "INFO"),
    ("MODE_CHANGED",      "INFO"),
    ("GALON_REPLACED",    "INFO"),
    ("FILL_TIMEOUT",      "ERROR"),
]
ALARM_NAME_TO_IDX = {name: i for i, (name, _sev) in enumerate(ALARM_TABLE)}


# ════════════════════════════════════════════════════════
# HMAC — identik dengan firmware
# ════════════════════════════════════════════════════════

def _hmac_key(machine_id: str, secret: str) -> bytes:
    return f"{machine_id}:{secret}".encode()

def _compute_hmac(message: str, key: bytes) -> str:
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()

def add_hmac(payload: dict, secret: str) -> dict:
    machine_id = payload["machine_id"]
    payload.pop("hmac", None)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload["hmac"] = _compute_hmac(body, _hmac_key(machine_id, secret))
    return payload

def verify_command_hmac(doc: dict, machine_id: str, secret: str) -> bool:
    cmd = str(doc.get("cmd", ""))
    sid = str(doc.get("session_id", ""))
    vol = float(doc.get("volume_liter", 0.0) or 0.0)
    iat = int(doc.get("issued_at", 0) or 0)
    rx_h = str(doc.get("hmac", ""))
    msg2 = f"{cmd}:{sid}:{vol:.3f}:{iat}"
    expect = _compute_hmac(msg2, _hmac_key(machine_id, secret))
    return hmac.compare_digest(expect, rx_h)


# ════════════════════════════════════════════════════════
# MODEL MESIN VIRTUAL — dengan simulasi realistis
# ════════════════════════════════════════════════════════

class MachineSim:
    def __init__(self, machine_id: str, secret: str, g1_pct: float, g2_pct: float):
        self.machine_id = machine_id
        self.secret = secret

        # Level galon (persen)
        self.g1_pct = g1_pct
        self.g2_pct = g2_pct
        self.active_galon = 1
        self.mode = "RO"          # "RO" atau "MANUAL"
        self.state = "IDLE"       # IDLE, DISPENSING, FILLING, ERROR

        self.online_since = int(time.time())
        self.last_dispense = 0
        self.total_dispense_today = 0.0
        self.total_transactions_today = 0

        # Dispensing state
        self.dispense_active = False
        self.session_id = ""
        self.order_id = ""
        self.target_liters = 0.0
        self.total_liters = 0.0
        self.flow_rate = 0.0
        self.flow_start_ts = 0.0

        # Filling state
        self.filling_galon = 0
        self.fill_start_ts = 0.0
        self.blind_zone_fill_start_ts = 0.0   # kapan mulai blind zone saat filling

        # Blind zone tracking (dispense side)
        self.in_blind_zone_g1 = False
        self.in_blind_zone_g2 = False
        self.liters_removed_since_full_g1 = 0.0
        self.liters_removed_since_full_g2 = 0.0

        self.last_alarm_ts = {}   # idx -> epoch
        self.last_status_ts = 0.0
        self.last_tick_ts = time.time()
        self.lock = threading.RLock()

    # ── topic helpers ──
    @property
    def topic_status(self):  return f"toyamas/{self.machine_id}/status"
    @property
    def topic_flow(self):    return f"toyamas/{self.machine_id}/flow"
    @property
    def topic_alarm(self):   return f"toyamas/{self.machine_id}/alarm"
    @property
    def topic_command(self): return f"toyamas/{self.machine_id}/command"

    # ── helper: mendapatkan level aktual (dengan estimasi blind zone) ──
    def get_level_pct(self, galon: int) -> float:
        """Mengembalikan level persen yang sudah memperhitungkan estimasi blind zone.
        Jika in_blind_zone true, level dihitung dari liter yang keluar sejak penuh.
        """
        if galon == 1:
            if self.in_blind_zone_g1:
                frac = self.liters_removed_since_full_g1 / (GALON_CAPACITY_L * (BLIND_ZONE_PCT / 100.0))
                frac = max(0.0, min(1.0, frac))
                return 100.0 - frac * BLIND_ZONE_PCT
            else:
                return self.g1_pct
        else:  # galon 2
            if self.in_blind_zone_g2:
                frac = self.liters_removed_since_full_g2 / (GALON_CAPACITY_L * (BLIND_ZONE_PCT / 100.0))
                frac = max(0.0, min(1.0, frac))
                return 100.0 - frac * BLIND_ZONE_PCT
            else:
                return self.g2_pct

    def get_level_cm(self, galon: int) -> float:
        pct = self.get_level_pct(galon)
        return (pct / 100.0) * GALON_MAX_HEIGHT_CM

    def is_sensor_valid(self, galon: int) -> bool:
        """Simulasi apakah sensor ultrasonik bisa membaca level saat ini.
        Sensor tidak valid jika level > BLIND_ZONE_PCT (karena jarak < MIN_SENSOR_DIST_CM).
        """
        pct = self.g1_pct if galon == 1 else self.g2_pct
        return pct <= BLIND_ZONE_PCT

    # ── builder payload ──
    def build_status(self) -> dict:
        g1_pct = self.get_level_pct(1)
        g2_pct = self.get_level_pct(2)
        g1_cm = round(self.get_level_cm(1), 1)
        g2_cm = round(self.get_level_cm(2), 1)

        payload = {
            "machine_id": self.machine_id,
            "timestamp": int(time.time()),
            "state": self.state,
            "mode": self.mode,
            "galon": {
                "g1_level_pct": round(g1_pct, 1),
                "g1_level_cm": g1_cm,
                "g1_status": "LOW" if g1_pct < GALON_LOW_PCT else "OK",
                "g1_estimated": self.in_blind_zone_g1,
                "g2_level_pct": round(g2_pct, 1),
                "g2_level_cm": g2_cm,
                "g2_status": "LOW" if g2_pct < GALON_LOW_PCT else "OK",
                "g2_estimated": self.in_blind_zone_g2,
                "active_galon": self.active_galon,
            },
            "actuators": {
                "pump_dc": self.state == "DISPENSING",
                "solenoid_ro1": self.state == "FILLING" and self.filling_galon == 1,
                "solenoid_ro2": self.state == "FILLING" and self.filling_galon == 2,
                "solenoid_pump1": self.state == "DISPENSING" and self.active_galon == 1,
                "solenoid_pump2": self.state == "DISPENSING" and self.active_galon == 2,
                "uv_lamp": self.state == "DISPENSING",
            },
            "leds": {
                "green": self.state not in ("ERROR", "ALERT"),
                "yellow": g1_pct < GALON_LOW_PCT or g2_pct < GALON_LOW_PCT,
                "red": self.state == "ERROR",
            },
            "system": {
                "uptime_sec": int(time.time()) - self.online_since,
                "wifi_rssi": random.randint(-75, -45),
                "free_heap": random.randint(170000, 220000),
                "firmware_ver": FIRMWARE_VERSION,
                "dummy_mode": True,
            },
            "env": {
                "fan_on": self.state in ("DISPENSING", "FILLING"),
            },
            "ota": {
                "internet_enabled": False,
                "ap_enabled": False,
                "http_in_progress": False,
            },
            "machine_status": {
                "online_since": self.online_since,
                "last_dispense": self.last_dispense,
                "total_dispense_today": round(self.total_dispense_today, 2),
                "total_transactions_today": self.total_transactions_today,
            },
        }
        return payload

    def build_flow(self) -> dict:
        elapsed = int(time.time() - self.flow_start_ts) if self.flow_start_ts else 0
        pct_complete = (
            round((self.total_liters / self.target_liters) * 1000) / 10.0
            if self.target_liters > 0 else 0
        )
        return {
            "machine_id": self.machine_id,
            "timestamp": int(time.time()),
            "session_id": self.session_id,
            "state": "DISPENSING",
            "flow": {
                "current_liters": round(self.total_liters, 2),
                "target_liters": self.target_liters,
                "flow_rate_lpm": round(self.flow_rate, 2),
                "pct_complete": pct_complete,
                "elapsed_sec": elapsed,
            },
            "galon_active": self.active_galon,
        }

    def build_alarm(self, alarm_name: str, message: str, galon_num: int = 0) -> dict:
        idx = ALARM_NAME_TO_IDX[alarm_name]
        type_str, severity = ALARM_TABLE[idx]
        detail = {
            "message": message,
            "galon": galon_num if galon_num > 0 else self.active_galon,
            "level_pct": self.get_level_pct(self.active_galon),
        }
        if alarm_name == "DISPENSE_COMPLETE":
            detail["actual_liters"] = round(self.total_liters, 2)
            detail["session_id"] = self.session_id
        return {
            "machine_id": self.machine_id,
            "timestamp": int(time.time()),
            "alarm_type": type_str,
            "severity": severity,
            "mode": self.mode,
            "detail": detail,
        }

    def build_pong(self) -> dict:
        uptime = int(time.time()) - self.online_since
        return {
            "machine_id": self.machine_id,
            "response": "PONG",
            "timestamp": int(time.time()),
            "uptime_sec": uptime,
        }


# ════════════════════════════════════════════════════════
# SIMULATOR (MQTT glue + logika real)
# ════════════════════════════════════════════════════════

class ToyamasSimulator:
    def __init__(self, machines_cfg, broker, port, user="", password=""):
        self.machines = {
            m["machine_id"]: MachineSim(m["machine_id"], m["secret"], m["g1_pct"], m["g2_pct"])
            for m in machines_cfg
        }
        self.client = mqtt.Client(client_id=f"toyamas-sim-{random.randint(1000,9999)}")
        if user:
            self.client.username_pw_set(user, password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.broker = broker
        self.port = port
        self._stop = threading.Event()

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            print(f"[MQTT] Gagal konek, rc={rc}")
            return
        print(f"[MQTT] Terhubung ke {self.broker}:{self.port}")
        for m in self.machines.values():
            client.subscribe(m.topic_command, qos=1)
            print(f"[MQTT] Subscribe {m.topic_command}")

    def _on_message(self, client, userdata, msg):
        try:
            doc = json.loads(msg.payload.decode())
        except Exception:
            return
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[2] != "command":
            return
        machine_id = parts[1]
        m = self.machines.get(machine_id)
        if not m:
            return
        if not verify_command_hmac(doc, machine_id, m.secret):
            print(f"[SEC] {machine_id}: HMAC command tidak valid, diabaikan -> {doc}")
            return
        self._handle_command(m, doc)

    def _publish(self, topic: str, payload: dict, secret: str):
        add_hmac(payload, secret)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        self.client.publish(topic, body, qos=1)

    def _handle_command(self, m: MachineSim, doc: dict):
        cmd = doc.get("cmd", "")
        print(f"[CMD] {m.machine_id} <- {cmd} {doc}")
        with m.lock:
            if cmd == "DISPENSE":
                if m.dispense_active or m.state == "FILLING":
                    return
                vol = float(doc.get("volume_liter", 0.0) or 0.0)
                if vol <= 0 or vol > GALON_CAPACITY_L * 2:
                    return
                avail = (m.get_level_pct(1) + m.get_level_pct(2)) / 100.0 * GALON_CAPACITY_L
                if avail < vol:
                    self._trigger_alarm(m, "GALON_EMPTY", f"Stok kurang: {avail:.1f}L")
                    return
                m.session_id = doc.get("session_id", "")
                m.order_id = doc.get("order_id", "")
                m.target_liters = vol
                m.total_liters = 0.0
                m.flow_start_ts = time.time()
                m.dispense_active = True
                m.state = "DISPENSING"
                # Reset dry-run timer
                m.dry_run_start_ts = 0.0   # tambahkan nanti jika perlu
                print(f"[CMD] {m.machine_id} DISPENSE order={m.order_id} vol={vol:.2f}L")

            elif cmd == "STOP":
                if m.state == "DISPENSING":
                    m.dispense_active = False
                    m.state = "IDLE"
                    self._trigger_alarm(m, "DISPENSE_ABORT", "Emergency STOP")

            elif cmd == "SET_MODE":
                mode = doc.get("mode", "RO")
                if mode != m.mode:
                    m.mode = "MANUAL" if mode == "MANUAL" else "RO"
                    # Jika mode manual, hentikan filling
                    if m.mode == "MANUAL" and m.state == "FILLING":
                        m.state = "IDLE"
                        m.filling_galon = 0
                    self._trigger_alarm(m, "MODE_CHANGED", f"Mode {m.mode}")

            elif cmd == "RESET":
                m.online_since = int(time.time())
                m.dispense_active = False
                m.state = "IDLE"
                m.filling_galon = 0

            elif cmd == "PING":
                self._publish(m.topic_status, m.build_pong(), m.secret)
                print(f"[CMD] {m.machine_id} PONG")

            else:
                print(f"[CMD] {m.machine_id}: cmd '{cmd}' tidak disimulasikan (diabaikan)")

    # ── alarm dgn throttle ──
    def _trigger_alarm(self, m: MachineSim, alarm_name: str, message: str, galon_num: int = 0) -> bool:
        idx = ALARM_NAME_TO_IDX[alarm_name]
        _type_str, severity = ALARM_TABLE[idx]
        is_err = severity == "ERROR"
        now = time.time()
        last = m.last_alarm_ts.get(idx, 0)
        if not is_err and (now - last) < ALARM_THROTTLE_SEC:
            return False
        m.last_alarm_ts[idx] = now
        if is_err:
            m.dispense_active = False
            m.state = "ERROR"
            if m.state == "FILLING":
                m.state = "IDLE"
                m.filling_galon = 0
        payload = m.build_alarm(alarm_name, message, galon_num)
        self._publish(m.topic_alarm, payload, m.secret)
        print(f"[ALARM][{severity}] {m.machine_id} {alarm_name}: {message}")
        return True

    # ── logika utama tiap tick ──
    def _tick_machine(self, m: MachineSim, dt: float):
        with m.lock:
            now = time.time()
            # Jika dalam ERROR, tidak lakukan apa-apa (kecuali reset lewat command)
            if m.state == "ERROR":
                return

            # ========== HANDLE FILLING ==========
            if m.state == "FILLING":
                g = m.filling_galon
                # Laju pengisian (liter/menit)
                fill_lpm = FILL_FLOW_RATE_LPM * (1.0 + random.uniform(-0.05, 0.05))  # variasi kecil
                liter_added = (fill_lpm / 60.0) * dt
                pct_added = (liter_added / GALON_CAPACITY_L) * 100.0

                # Update level aktual (tanpa estimasi blind zone)
                if g == 1:
                    m.g1_pct = min(100.0, m.g1_pct + pct_added)
                    # Jika sensor valid (level <= BLIND_ZONE_PCT), reset timer blind zone
                    if m.is_sensor_valid(1):
                        m.blind_zone_fill_start_ts = 0.0
                    else:
                        if m.blind_zone_fill_start_ts == 0.0:
                            m.blind_zone_fill_start_ts = now
                        elif (now - m.blind_zone_fill_start_ts) * 1000 >= RO_FILL_BLIND_ZONE_MS:
                            # Timer blind zone habis → anggap penuh
                            m.g1_pct = 100.0
                            m.state = "IDLE"
                            m.filling_galon = 0
                            print(f"[FILL] {m.machine_id} G1 penuh (estimasi blind zone timer)")
                            return
                else:  # g == 2
                    m.g2_pct = min(100.0, m.g2_pct + pct_added)
                    if m.is_sensor_valid(2):
                        m.blind_zone_fill_start_ts = 0.0
                    else:
                        if m.blind_zone_fill_start_ts == 0.0:
                            m.blind_zone_fill_start_ts = now
                        elif (now - m.blind_zone_fill_start_ts) * 1000 >= RO_FILL_BLIND_ZONE_MS:
                            m.g2_pct = 100.0
                            m.state = "IDLE"
                            m.filling_galon = 0
                            print(f"[FILL] {m.machine_id} G2 penuh (estimasi blind zone timer)")
                            return

                # Cek apakah sudah mencapai threshold penuh (berdasarkan sensor valid)
                if g == 1 and m.is_sensor_valid(1) and m.g1_pct >= GALON_FILL_THRESHOLD:
                    m.state = "IDLE"
                    m.filling_galon = 0
                    m.blind_zone_fill_start_ts = 0.0
                    print(f"[FILL] {m.machine_id} G1 penuh (sensor valid)")
                    return
                if g == 2 and m.is_sensor_valid(2) and m.g2_pct >= GALON_FILL_THRESHOLD:
                    m.state = "IDLE"
                    m.filling_galon = 0
                    m.blind_zone_fill_start_ts = 0.0
                    print(f"[FILL] {m.machine_id} G2 penuh (sensor valid)")
                    return

                # Safety timeout
                if (now - m.fill_start_ts) * 1000 >= RO_FILL_MAX_TIMEOUT_MS:
                    self._trigger_alarm(m, "FILL_TIMEOUT",
                                        f"G{m.filling_galon} fill timeout — cek RO/solenoid manual!",
                                        m.filling_galon)
                    m.state = "IDLE"
                    m.filling_galon = 0
                    m.blind_zone_fill_start_ts = 0.0
                    return

            # ========== HANDLE DISPENSING ==========
            elif m.state == "DISPENSING" and m.dispense_active:
                # Laju aliran dispensing
                flow_lpm = DISPENSE_FLOW_RATE_LPM * (1.0 + random.uniform(-0.05, 0.05))
                lit_interval = (flow_lpm / 60.0) * dt
                m.total_liters += lit_interval
                m.flow_rate = flow_lpm

                # Kurangi level galon aktif
                g = m.active_galon
                pct_drop = (lit_interval / GALON_CAPACITY_L) * 100.0
                if g == 1:
                    m.g1_pct = max(0.0, m.g1_pct - pct_drop)
                    # Update liter removed sejak full (untuk estimasi blind zone)
                    if m.in_blind_zone_g1:
                        m.liters_removed_since_full_g1 += lit_interval
                    # Jika sensor kembali valid, non-aktifkan blind zone
                    if m.is_sensor_valid(1):
                        m.in_blind_zone_g1 = False
                else:
                    m.g2_pct = max(0.0, m.g2_pct - pct_drop)
                    if m.in_blind_zone_g2:
                        m.liters_removed_since_full_g2 += lit_interval
                    if m.is_sensor_valid(2):
                        m.in_blind_zone_g2 = False

                # Cek dry-run
                if m.total_liters > 0.1 and m.flow_rate < 0.05:
                    # Dry-run sederhana: jika flow rate sangat kecil, alarm
                    pass  # bisa ditambahkan nanti

                # Selesai dispensing
                if m.total_liters >= m.target_liters and m.target_liters > 0:
                    m.dispense_active = False
                    m.state = "IDLE"
                    m.last_dispense = int(now)
                    m.total_dispense_today += m.total_liters
                    m.total_transactions_today += 1
                    self._trigger_alarm(m, "DISPENSE_COMPLETE",
                                        f"Selesai: {m.total_liters:.2f}L")
                    # Setelah dispense selesai, jika mode RO dan level di bawah refill, mulai filling
                    if m.mode == "RO":
                        # Cek level masing-masing (termasuk estimasi)
                        l1 = m.get_level_pct(1)
                        l2 = m.get_level_pct(2)
                        if l1 < GALON_REFILL_THRESHOLD and l2 < GALON_REFILL_THRESHOLD:
                            # Pilih yang lebih rendah
                            target = 1 if l1 <= l2 else 2
                            self._start_filling(m, target)
                        elif l1 < GALON_REFILL_THRESHOLD:
                            self._start_filling(m, 1)
                        elif l2 < GALON_REFILL_THRESHOLD:
                            self._start_filling(m, 2)

            # ========== HANDLE IDLE (cek refill) ==========
            if m.state == "IDLE" and m.mode == "RO" and not m.dispense_active:
                # Cek apakah ada galon yang perlu diisi
                l1 = m.get_level_pct(1)
                l2 = m.get_level_pct(2)
                if l1 < GALON_REFILL_THRESHOLD or l2 < GALON_REFILL_THRESHOLD:
                    # Pilih galon dengan level terendah (atau jika salah satu di bawah threshold)
                    if l1 < GALON_REFILL_THRESHOLD and l2 < GALON_REFILL_THRESHOLD:
                        target = 1 if l1 <= l2 else 2
                    elif l1 < GALON_REFILL_THRESHOLD:
                        target = 1
                    else:
                        target = 2
                    self._start_filling(m, target)

            # ========== AUTO-SWITCH GALON AKTIF ==========
            # Pilih galon dengan level tertinggi (kecuali jika salah satu kosong)
            pref = 1 if m.get_level_pct(1) >= m.get_level_pct(2) else 2
            pref_lv = m.get_level_pct(pref)
            if pref_lv > GALON_EMPTY_PCT and pref != m.active_galon and not m.dispense_active:
                old = m.active_galon
                m.active_galon = pref
                self._trigger_alarm(m, "GALON_SWITCH", f"Auto-switch G{old}->G{pref}")

            # ========== CEK AMBANG LEVEL ==========
            # Gunakan level aktual (dengan estimasi)
            l1 = m.get_level_pct(1)
            l2 = m.get_level_pct(2)
            if l1 < GALON_EMPTY_PCT and l2 < GALON_EMPTY_PCT:
                self._trigger_alarm(m, "BOTH_GALON_EMPTY", "Kedua galon kosong!")
            else:
                if l1 < GALON_CRITICAL_PCT and l1 >= GALON_EMPTY_PCT:
                    self._trigger_alarm(m, "GALON_CRITICAL", "G1 kritis", 1)
                if l2 < GALON_CRITICAL_PCT and l2 >= GALON_EMPTY_PCT:
                    self._trigger_alarm(m, "GALON_CRITICAL", "G2 kritis", 2)
                if l1 < GALON_LOW_PCT and l1 >= GALON_CRITICAL_PCT:
                    self._trigger_alarm(m, "GALON_LOW", "G1 rendah", 1)
                if l2 < GALON_LOW_PCT and l2 >= GALON_CRITICAL_PCT:
                    self._trigger_alarm(m, "GALON_LOW", "G2 rendah", 2)

    def _start_filling(self, m: MachineSim, galon: int):
        """Mulai proses pengisian untuk galon tertentu."""
        if m.state != "IDLE":
            return
        if m.mode != "RO":
            return
        m.filling_galon = galon
        m.state = "FILLING"
        m.fill_start_ts = time.time()
        m.blind_zone_fill_start_ts = 0.0
        print(f"[FILL] {m.machine_id} mulai mengisi G{galon}")

    # ── loop background ──
    def _loop(self):
        last_tick = time.time()
        while not self._stop.is_set():
            now = time.time()
            dt = now - last_tick
            last_tick = now

            for m in self.machines.values():
                self._tick_machine(m, dt)

                # Publish flow jika dispensing
                if m.state == "DISPENSING" and (now - m.last_status_ts) >= FLOW_INTERVAL_SEC:
                    self._publish(m.topic_flow, m.build_flow(), m.secret)

                # Publish status dengan interval
                pub_interval = FLOW_INTERVAL_SEC if m.state == "DISPENSING" else STATUS_INTERVAL_SEC
                if (now - m.last_status_ts) >= pub_interval:
                    self._publish(m.topic_status, m.build_status(), m.secret)
                    m.last_status_ts = now

            self._stop.wait(TICK_SEC)

    def start(self):
        print(f"[MQTT] Menghubungkan ke {self.broker}:{self.port} ...")
        self.client.connect(self.broker, self.port, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.client.loop_stop()
        self.client.disconnect()

    # ── aksi manual dari console ──
    def cmd_list(self):
        for m in self.machines.values():
            l1 = m.get_level_pct(1)
            l2 = m.get_level_pct(2)
            print(
                f"  {m.machine_id:10s} state={m.state:10s} mode={m.mode:6s} "
                f"G1={l1:5.1f}% G2={l2:5.1f}% active=G{m.active_galon} "
                f"today={m.total_dispense_today:.2f}L/{m.total_transactions_today}trx"
            )

    def cmd_dispense(self, machine_id, liters):
        m = self.machines.get(machine_id)
        if not m:
            print("Machine tidak ditemukan"); return
        self._handle_command(m, {
            "cmd": "DISPENSE", "volume_liter": liters,
            "session_id": f"manual-{int(time.time())}",
            "order_id": f"cli-{int(time.time())}",
        })

    def cmd_stop(self, machine_id):
        m = self.machines.get(machine_id)
        if not m:
            print("Machine tidak ditemukan"); return
        self._handle_command(m, {"cmd": "STOP"})

    def cmd_set_level(self, machine_id, which, pct):
        m = self.machines.get(machine_id)
        if not m:
            print("Machine tidak ditemukan"); return
        pct = max(0.0, min(100.0, pct))
        with m.lock:
            if which in ("g1", "both"):
                m.g1_pct = pct
                # Reset blind zone flags
                m.in_blind_zone_g1 = False
                m.liters_removed_since_full_g1 = 0.0
            if which in ("g2", "both"):
                m.g2_pct = pct
                m.in_blind_zone_g2 = False
                m.liters_removed_since_full_g2 = 0.0
            # Jika state filling dan level sudah di atas threshold, hentikan
            if m.state == "FILLING":
                m.state = "IDLE"
                m.filling_galon = 0
        print(f"{machine_id}: level di-set -> G1={m.g1_pct:.1f}% G2={m.g2_pct:.1f}%")

    def cmd_alarm(self, machine_id, alarm_name, message):
        m = self.machines.get(machine_id)
        if not m:
            print("Machine tidak ditemukan"); return
        if alarm_name not in ALARM_NAME_TO_IDX:
            print(f"Nama alarm tidak dikenal. Pilihan: {', '.join(ALARM_NAME_TO_IDX)}")
            return
        m.last_alarm_ts.pop(ALARM_NAME_TO_IDX[alarm_name], None)
        self._trigger_alarm(m, alarm_name, message)


# ════════════════════════════════════════════════════════
# CONSOLE INTERAKTIF
# ════════════════════════════════════════════════════════

HELP_TEXT = """
Perintah yang tersedia:
  list                                         - tampilkan status semua mesin virtual
  dispense <machine_id> <liter>                - trigger simulasi dispensing
  stop <machine_id>                            - emergency stop
  refill <machine_id> <g1|g2|both> [pct=95]    - set ulang level galon (simulasi ganti galon)
  low <machine_id> <g1|g2>                     - set level ke 19% (di bawah LOW)
  critical <machine_id> <g1|g2>                - set level ke 4% (di bawah CRITICAL)
  empty <machine_id> <g1|g2>                   - set level ke 0%
  alarm <machine_id> <ALARM_NAME> [pesan...]   - paksa kirim alarm tertentu
  help                                          - tampilkan bantuan ini
  quit / exit                                   - keluar

Nama ALARM_NAME yang valid:
  """ + ", ".join(ALARM_NAME_TO_IDX) + """
"""

def run_console(sim: ToyamasSimulator):
    print(HELP_TEXT)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd in ("quit", "exit"):
                break
            elif cmd == "help":
                print(HELP_TEXT)
            elif cmd == "list":
                sim.cmd_list()
            elif cmd == "dispense" and len(parts) >= 3:
                sim.cmd_dispense(parts[1], float(parts[2]))
            elif cmd == "stop" and len(parts) >= 2:
                sim.cmd_stop(parts[1])
            elif cmd == "refill" and len(parts) >= 3:
                pct = float(parts[3]) if len(parts) >= 4 else 95.0
                sim.cmd_set_level(parts[1], parts[2], pct)
            elif cmd == "low" and len(parts) >= 3:
                sim.cmd_set_level(parts[1], parts[2], GALON_LOW_PCT - 1)
            elif cmd == "critical" and len(parts) >= 3:
                sim.cmd_set_level(parts[1], parts[2], GALON_CRITICAL_PCT - 1)
            elif cmd == "empty" and len(parts) >= 3:
                sim.cmd_set_level(parts[1], parts[2], 0.0)
            elif cmd == "alarm" and len(parts) >= 3:
                msg = " ".join(parts[3:]) if len(parts) > 3 else "Manual trigger dari console"
                sim.cmd_alarm(parts[1], parts[2], msg)
            else:
                print("Perintah tidak dikenal / argumen kurang. Ketik 'help'.")
        except Exception as e:
            print(f"Error: {e}")


# ════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Simulator MQTT fleet TOYAMAS (realistic)")
    ap.add_argument("--broker", default=MQTT_BROKER)
    ap.add_argument("--port", type=int, default=MQTT_PORT)
    ap.add_argument("--user", default=MQTT_USER)
    ap.add_argument("--password", default=MQTT_PASS)
    args = ap.parse_args()

    sim = ToyamasSimulator(MACHINES, args.broker, args.port, args.user, args.password)
    sim.start()
    try:
        run_console(sim)
    finally:
        sim.stop()

if __name__ == "__main__":
    main()