"""
services/mqtt_bridge.py
MQTT subscriber yang menerima data dari ESP32,
memproses FSM state, meneruskan ke WebSocket client UI,
dan menulis ke SQLite lokal.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

from config.settings import (
    MQTT_BROKER, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD,
    MQTT_QOS, MQTT_USE_TLS,
    MQTT_TOPIC_STATUS_WILDCARD, MQTT_TOPIC_FLOW_WILDCARD,
    MQTT_TOPIC_ALARM_WILDCARD,
    MACHINE_ID
)
from middleware.auth import verify_mqtt_hmac, compute_command_hmac
from services.database import (
    update_state_cache, log_sensor_data, log_alarm,
    update_dispense_status, update_machine_online
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# WebSocket Manager — broadcast ke semua UI
# ─────────────────────────────────────────

class WebSocketManager:
    """
    Manages semua WebSocket connection dari UI kiosk.
    Setiap machine_id punya set koneksi sendiri.
    """
    def __init__(self):
        # { machine_id: set of WebSocket }
        self.connections: dict[str, set] = {}

    async def connect(self, ws, machine_id: str):
        if machine_id not in self.connections:
            self.connections[machine_id] = set()
        self.connections[machine_id].add(ws)
        logger.info(f"WS connected: {machine_id} (total: {len(self.connections[machine_id])})")

    async def disconnect(self, ws, machine_id: str):
        if machine_id in self.connections:
            self.connections[machine_id].discard(ws)
        logger.info(f"WS disconnected: {machine_id}")

    async def broadcast(self, machine_id: str, event: str, data: dict):
        """Kirim event ke semua UI yang terhubung ke machine_id ini."""
        if machine_id not in self.connections:
            return
        message = json.dumps({"event": event, "data": data})
        dead = set()
        for ws in self.connections[machine_id].copy():
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        # Bersihkan koneksi yang sudah mati
        self.connections[machine_id] -= dead

    def get_count(self, machine_id: str) -> int:
        return len(self.connections.get(machine_id, set()))


# Singleton WebSocket manager
ws_manager = WebSocketManager()


# ─────────────────────────────────────────
# Session Tracker — track sesi dispense aktif
# ─────────────────────────────────────────

class DispenseSession:
    """State sesi dispense aktif (satu per mesin)."""
    def __init__(self):
        self.active    = False
        self.order_id  : Optional[str]   = None
        self.session_id: Optional[str]   = None
        self.target_vol: float           = 0.0
        self.started_at: Optional[float] = None

    def start(self, order_id: str, session_id: str, volume: float):
        self.active     = True
        self.order_id   = order_id
        self.session_id = session_id
        self.target_vol = volume
        self.started_at = time.time()

    def reset(self):
        self.active     = False
        self.order_id   = None
        self.session_id = None
        self.target_vol = 0.0
        self.started_at = None


active_session = DispenseSession()


# ─────────────────────────────────────────
# MQTT Message Processors
# ─────────────────────────────────────────

async def _process_status(payload: dict, machine_id: str):
    """
    Proses pesan MQTT topic: status (tiap 10 detik dari ESP32).
    1. Update cache di SQLite
    2. Log ke sensor_logs
    3. Broadcast ke UI via WebSocket
    """
    # Update mesin online
    update_machine_online(machine_id, online=True)
    update_state_cache(machine_id, payload)
    log_sensor_data(machine_id, payload)

    galon = payload.get("galon", {})
    await ws_manager.broadcast(machine_id, "machine_status", {
        "state":               payload.get("state", "IDLE"),
        "mode":                payload.get("mode", "RO"),
        "g1_level_pct":        galon.get("g1_level_pct", 0),
        "g2_level_pct":        galon.get("g2_level_pct", 0),
        "g1_status":           galon.get("g1_status", "UNKNOWN"),
        "g2_status":           galon.get("g2_status", "UNKNOWN"),
        "active_galon":        galon.get("active_galon", 1),
        "total_available_liters": round(
            ((galon.get("g1_level_pct", 0) / 100) +
             (galon.get("g2_level_pct", 0) / 100)) * 19.0, 2
        )
    })


async def _process_flow(payload: dict, machine_id: str):
    """
    Proses MQTT flow (tiap 100ms saat DISPENSING).
    Forward langsung ke UI — tidak tulis DB untuk menjaga performa.
    """
    flow = payload.get("flow", {})
    await ws_manager.broadcast(machine_id, "realtime_flow", {
        "current_liters": flow.get("current_liters", 0),
        "target_liters":  flow.get("target_liters", active_session.target_vol),
        "pct_complete":   flow.get("pct_complete", 0),
        "flow_rate_lpm":  flow.get("flow_rate_lpm", 0),
        "galon_active":   payload.get("galon_active", 1),
        "session_id":     payload.get("session_id", ""),
    })


async def _process_alarm(payload: dict, machine_id: str):
    """
    Proses MQTT alarm (realtime event).
    1. Log ke tabel alarms
    2. Broadcast ke UI
    3. Tangani DISPENSE_COMPLETE → update transaksi
    """
    alarm_type = payload.get("alarm_type", "UNKNOWN")
    severity   = payload.get("severity", "INFO")
    detail     = payload.get("detail", {})

    # Simpan ke DB
    log_alarm(machine_id, alarm_type, severity, detail)

    # Tangani penyelesaian dispense
    if alarm_type == "DISPENSE_COMPLETE" and active_session.active:
        vol_actual = detail.get("actual_liters", active_session.target_vol)
        update_dispense_status(
            active_session.order_id, "COMPLETE", vol_actual
        )
        await ws_manager.broadcast(machine_id, "dispense_complete", {
            "session_id":    active_session.session_id,
            "order_id":      active_session.order_id,
            "actual_liters": vol_actual,
            "duration_sec":  round(time.time() - (active_session.started_at or time.time())),
        })
        active_session.reset()

    elif alarm_type == "DISPENSE_ABORT" and active_session.active:
        update_dispense_status(active_session.order_id, "ABORTED")
        await ws_manager.broadcast(machine_id, "alarm", {
            "alarm_type": alarm_type,
            "severity":   severity,
            "message":    detail.get("message", "Pengisian dibatalkan"),
        })
        active_session.reset()

    else:
        # Forward alarm lain ke UI
        await ws_manager.broadcast(machine_id, "alarm", {
            "alarm_type": alarm_type,
            "severity":   severity,
            "galon":      detail.get("galon"),
            "level_pct":  detail.get("level_pct"),
            "message":    detail.get("message", ""),
        })


# ─────────────────────────────────────────
# MQTT Command Publisher
# ─────────────────────────────────────────

_mqtt_client: Optional[mqtt.Client] = None


def publish_dispense_command(
    order_id: str, session_id: str,
    volume_liter: float, source: str = "PAYMENT",
    machine_id: str = MACHINE_ID
):
    """
    Kirim perintah DISPENSE ke ESP32 via MQTT.
    Dipanggil setelah payment confirmed ATAU tiket verified.
    """
    global _mqtt_client
    if not _mqtt_client or not _mqtt_client.is_connected():
        logger.error("MQTT client tidak terhubung, command tidak dikirim!")
        return False

    issued_at = int(time.time())
    payload   = {
        "cmd":          "DISPENSE",
        "session_id":   session_id,
        "order_id":     order_id,
        "source":       source,
        "volume_liter": volume_liter,
        "issued_at":    issued_at,
        "expires_at":   issued_at + 300,    # command expired setelah 5 menit
        "hmac":         compute_command_hmac(
            "DISPENSE", session_id, volume_liter, issued_at, machine_id
        ),
    }

    topic = f"toyamas/{machine_id}/command"
    result = _mqtt_client.publish(
        topic, json.dumps(payload), qos=MQTT_QOS, retain=False
    )

    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        # Track sesi aktif
        active_session.start(order_id, session_id, volume_liter)
        update_dispense_status(order_id, "DISPENSING")
        logger.info(f"DISPENSE cmd sent: order={order_id} vol={volume_liter}L")
        return True

    logger.error(f"MQTT publish gagal: rc={result.rc}")
    return False


def publish_stop_command(machine_id: str = MACHINE_ID):
    """
    Hentikan dispense paksa (emergency stop).

    PERBAIKAN: sebelumnya payload ini dikirim TANPA field "hmac" sama sekali.
    Firmware men-tolak SEMUA command yang tidak lolos verifyCommandHMAC()
    (termasuk STOP), jadi tombol Emergency STOP di panel admin tidak pernah
    benar-benar berhasil menghentikan mesin — firmware cuma log "[SEC] HMAC
    fail" dan mengabaikannya. Sekarang payload ditandatangani persis seperti
    DISPENSE, dengan session_id="" dan volume=0.0 (default yang dipakai
    firmware saat field itu tidak relevan untuk STOP).
    """
    if not _mqtt_client or not _mqtt_client.is_connected():
        logger.error("MQTT client tidak terhubung, STOP command tidak dikirim!")
        return False

    issued_at = int(time.time())
    payload = {
        "cmd":          "STOP",
        "session_id":   "",
        "volume_liter": 0.0,
        "issued_at":    issued_at,
        "hmac":         compute_command_hmac(
            "STOP", "", 0.0, issued_at, machine_id
        ),
    }
    result = _mqtt_client.publish(
        f"toyamas/{machine_id}/command",
        json.dumps(payload), qos=MQTT_QOS
    )
    return result.rc == mqtt.MQTT_ERR_SUCCESS

def publish_set_mode_command(machine_id: str, mode: str):
    """
    Kirim perintah SET_MODE ke ESP32 via MQTT.
    """
    if not _mqtt_client or not _mqtt_client.is_connected():
        logger.error("MQTT client tidak terhubung, SET_MODE command tidak dikirim!")
        return False

    # Validasi mode
    if mode not in ("RO", "MANUAL"):
        logger.error(f"Mode tidak valid: {mode}")
        return False

    issued_at = int(time.time())
    payload = {
        "cmd": "SET_MODE",
        "mode": mode,
        "issued_at": issued_at,
        "hmac": compute_command_hmac("SET_MODE", "", 0.0, issued_at, machine_id)
    }

    result = _mqtt_client.publish(
        f"toyamas/{machine_id}/command",
        json.dumps(payload),
        qos=MQTT_QOS
    )

    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        logger.info(f"SET_MODE command sent: machine={machine_id} mode={mode}")
        return True
    else:
        logger.error(f"MQTT publish SET_MODE gagal: rc={result.rc}")
        return False

# ─────────────────────────────────────────
# Broadcast events ke kiosk via WebSocket
# ─────────────────────────────────────────

def broadcast_config_update(machine_id: str):
    """Kirim event config_update ke kiosk (termasuk mode)."""
    from services.database import get_machine_config, get_machine
    config = get_machine_config(machine_id)
    machine = get_machine(machine_id)
    if machine:
        config["mode"] = machine.get("mode", "RO")
    asyncio.run_coroutine_threadsafe(
        ws_manager.broadcast(machine_id, "config_update", config),
        _loop
    )
    logger.info(f"Broadcast config_update untuk {machine_id}")

def broadcast_signage_update(machine_id: str):
    """Kirim event signage_update ke kiosk."""
    from services.database import get_signage_slides
    slides = get_signage_slides(machine_id, active_only=True)
    base_url = "/media/signage/"
    payload = [
        {
            "id": s["id"],
            "media_type": s["media_type"],
            "url": f"{base_url}{s['file_path']}",
            "caption": s.get("caption"),
            "order": s["slide_order"],
        }
        for s in slides
    ]
    asyncio.run_coroutine_threadsafe(
        ws_manager.broadcast(machine_id, "signage_update", payload),
        _loop
    )
    logger.info(f"Broadcast signage_update untuk {machine_id} (jumlah slide: {len(payload)})")


# ─────────────────────────────────────────
# MQTT Client Setup
# ─────────────────────────────────────────

def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info(f"MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
        # PERBAIKAN (multi-mesin): dulu subscribe ke topic satu MACHINE_ID
        # saja (toyamas/TYM-001/status dst), jadi data dari mesin lain
        # (TYM-002, TYM-003, ...) yang dipublish ke broker yang sama TIDAK
        # PERNAH sampai ke backend. Sekarang subscribe wildcard "+" di posisi
        # machine_id supaya satu backend menerima status/flow/alarm dari
        # SELURUH armada sekaligus.
        client.subscribe(MQTT_TOPIC_STATUS_WILDCARD, MQTT_QOS)
        client.subscribe(MQTT_TOPIC_FLOW_WILDCARD,   MQTT_QOS)
        client.subscribe(MQTT_TOPIC_ALARM_WILDCARD,  MQTT_QOS)
        logger.info(
            f"Subscribed (semua mesin): {MQTT_TOPIC_STATUS_WILDCARD}, "
            f"{MQTT_TOPIC_FLOW_WILDCARD}, {MQTT_TOPIC_ALARM_WILDCARD}"
        )
    else:
        logger.error(f"MQTT connect gagal: rc={rc}")


def _on_disconnect(client, userdata, rc):
    """
    Backend kehilangan koneksi ke broker MQTT.

    PERBAIKAN (multi-mesin): sebelumnya fungsi ini menandai HANYA satu
    MACHINE_ID (dari .env) sebagai offline, padahal saat broker disconnect,
    SEMUA mesin di armada otomatis berhenti mengirim status ke backend ini —
    bukan cuma satu mesin. Menandai satu machine_id saja di sini justru
    menyesatkan (mesin lain tetap tampak "online" padahal datanya sudah
    basi). Status online/offline per mesin sudah dihitung ulang secara
    otomatis berdasarkan `last_seen` vs MACHINE_OFFLINE_TIMEOUT_SEC di
    get_all_machines_status() setiap dashboard IoT polling/broadcast — jadi
    begitu broker disconnect dan tidak ada status baru masuk, semua mesin
    akan otomatis tampil offline dalam <= MACHINE_OFFLINE_TIMEOUT_SEC detik
    tanpa perlu di-set manual di sini.
    """
    logger.warning(f"MQTT disconnected: rc={rc}, reconnecting...")


def _on_message(client, userdata, msg):
    """Callback MQTT message — parse JSON dan dispatch ke processor."""
    # Simpan raw bytes SEBELUM decode — dibutuhkan verify_mqtt_hmac
    # agar bisa menghitung HMAC dari string JSON persis seperti ESP32 kirim,
    # tanpa re-serialize yang mengubah urutan field.
    raw_bytes = msg.payload

    # ── Parse topic: toyamas/{machine_id}/{subtopic} ──
    # PERBAIKAN (multi-mesin): machine_id sekarang diambil dari TOPIC MQTT,
    # bukan dari field "machine_id" di dalam payload. Kalau machine_id cuma
    # dipercaya dari payload, satu ESP32 (atau siapa pun yang tahu topic
    # publik) bisa mengklaim jadi mesin lain sekadar dengan mengubah field
    # itu. Topic sendiri sudah menentukan mesin mana yang mengirim, karena
    # tiap unit ESP32 di-flash dengan topic yang berbeda (TOPIC_STATUS dst
    # di firmware). Payload machine_id tetap dicek harus SAMA dengan topic
    # sebagai lapisan konsistensi tambahan.
    topic_parts = msg.topic.split("/")
    if len(topic_parts) != 3 or topic_parts[0] != "toyamas":
        logger.warning(f"MQTT topic format tidak dikenali, diabaikan: {msg.topic}")
        return
    machine_id, subtopic = topic_parts[1], topic_parts[2]

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"MQTT JSON parse error [{msg.topic}]: {e}")
        return

    payload_machine_id = payload.get("machine_id")
    if payload_machine_id and payload_machine_id != machine_id:
        logger.warning(
            f"MQTT machine_id di payload ({payload_machine_id}) tidak cocok "
            f"dengan topic ({machine_id}) — DIABAIKAN"
        )
        return

    # ── Verifikasi HMAC (kirim raw_bytes agar verifikasi akurat) ──
    received_hmac = payload.get("hmac", "")
    if not verify_mqtt_hmac(payload, received_hmac, machine_id,
                            raw_bytes=raw_bytes):
        logger.warning(
            f"MQTT HMAC MISMATCH dari {machine_id} topic {msg.topic} — DIABAIKAN\n"
            f"  raw={raw_bytes[:120]}"
        )
        return

    # ── Dispatch ke processor yang sesuai berdasarkan subtopic ──
    if subtopic == "status":
        asyncio.run_coroutine_threadsafe(
            _process_status(payload, machine_id), _loop
        )
    elif subtopic == "flow":
        asyncio.run_coroutine_threadsafe(
            _process_flow(payload, machine_id), _loop
        )
    elif subtopic == "alarm":
        asyncio.run_coroutine_threadsafe(
            _process_alarm(payload, machine_id), _loop
        )


_loop: asyncio.AbstractEventLoop = None


def start_mqtt_client(event_loop: asyncio.AbstractEventLoop):
    """Inisialisasi dan jalankan MQTT client di background thread."""
    global _mqtt_client, _loop
    _loop = event_loop

    # client_id fleet-wide (backend ini melayani semua mesin, bukan cuma
    # MACHINE_ID di .env) — cukup satu instance backend yang connect ke broker.
    client = mqtt.Client(client_id="toyamas-backend-hub", clean_session=True)
    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    if MQTT_USE_TLS:
        client.tls_set()

    # Reconnect otomatis
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()   # Non-blocking background thread
        _mqtt_client = client
        logger.info("MQTT client started")
    except Exception as e:
        logger.error(f"MQTT connect gagal: {e}")


def stop_mqtt_client():
    global _mqtt_client
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        logger.info("MQTT client stopped")

