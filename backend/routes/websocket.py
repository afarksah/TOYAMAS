"""
routes/websocket.py
WebSocket endpoint untuk UI kiosk dan IoT Dashboard
"""
import json
import logging
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.settings import (
    MACHINE_ID, 
    IOT_WS_REFRESH_STATUS_SEC,
    IOT_WS_REFRESH_SALES_SEC
)
from services.database import (
    get_state_cache, get_machine_config,
    get_sales_summary,
    get_transactions_filtered,
    get_all_machines_status,
)
from services.mqtt_bridge import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


# ─────────────────────────────────────────
# KIOSK WEBSOCKET
# ─────────────────────────────────────────

@router.websocket("/ws/{machine_id}")
async def websocket_endpoint(ws: WebSocket, machine_id: str):
    """Kiosk UI WebSocket."""
    await ws.accept()
    await ws_manager.connect(ws, machine_id)

    try:
        cache = get_state_cache(machine_id)
        config = get_machine_config(machine_id)

        init_data = {
            "event": "init",
            "data": {
                "machine_id": machine_id,
                "connected": True,
                "price_per_liter": int(config.get("price_per_liter", 500)),
                "machine_status": {
                    "online": bool(cache.get("online")) if cache else False,
                    "state": cache.get("state", "UNKNOWN") if cache else "UNKNOWN",
                    "mode": cache.get("mode", "RO") if cache else "RO",
                    "g1_level_pct": cache.get("g1_level_pct", 0) if cache else 0,
                    "g2_level_pct": cache.get("g2_level_pct", 0) if cache else 0,
                    "g1_status": cache.get("g1_status", "UNKNOWN") if cache else "UNKNOWN",
                    "g2_status": cache.get("g2_status", "UNKNOWN") if cache else "UNKNOWN",
                    "total_available_liters":
                        cache.get("total_available_liters", 0) if cache else 0,
                } if cache else None,
            }
        }
        await ws.send_text(json.dumps(init_data))

        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(ws, machine_id)
    except Exception as e:
        await ws_manager.disconnect(ws, machine_id)
        logger.error(f"WS error {machine_id}: {e}")


# ─────────────────────────────────────────
# IOT DASHBOARD WEBSOCKET
# ─────────────────────────────────────────

class IoTWebSocketManager:
    """
    Manager untuk WebSocket dashboard IoT.

    PERBAIKAN: sebelumnya tiap user_id yang connect memicu _broadcast_loop
    SENDIRI-SENDIRI, masing-masing query DB tiap IOT_WS_REFRESH_STATUS_SEC
    detik. Kalau 3 admin buka dashboard bersamaan, DB di-query 3x lipat
    untuk data yang persis sama. Interval sales juga ikut nempel ke interval
    status (5 detik) padahal IOT_WS_REFRESH_SALES_SEC (10 detik) sudah ada
    tapi tidak pernah dipakai.

    Sekarang: HANYA ADA SATU loop global yang jalan selama minimal satu
    admin connect. Loop ini query DB sekali per tick, lalu fan-out hasilnya
    ke SEMUA admin yang sedang connect. Beban ke DB jadi konstan (tidak
    scaling dengan jumlah tab dashboard yang terbuka), sehingga interval
    bisa dijaga tetap singkat (terasa realtime) tanpa menambah beban.
    """

    def __init__(self):
        self.connections: dict[str, set] = {}
        self._global_task: asyncio.Task | None = None

    def _total_connections(self) -> int:
        return sum(len(s) for s in self.connections.values())

    async def connect(self, ws: WebSocket, user_id: str):
        await ws.accept()
        if user_id not in self.connections:
            self.connections[user_id] = set()
        self.connections[user_id].add(ws)
        logger.info(f"IoT WS connected: {user_id} (total koneksi: {self._total_connections()})")

        await self._send_to_user(user_id, {
            "event": "connected",
            "data": {"message": "IoT Dashboard connected", "user_id": user_id}
        })

        if self._global_task is None or self._global_task.done():
            self._global_task = asyncio.create_task(self._broadcast_loop())

    async def disconnect(self, ws: WebSocket, user_id: str):
        if user_id in self.connections:
            self.connections[user_id].discard(ws)
            if not self.connections[user_id]:
                del self.connections[user_id]
        logger.info(f"IoT WS disconnected: {user_id} (sisa koneksi: {self._total_connections()})")

        if self._total_connections() == 0 and self._global_task is not None:
            self._global_task.cancel()
            self._global_task = None

    async def _broadcast_loop(self):
        """Satu loop untuk semua admin yang connect. Query DB sekali per tick,
        broadcast ke semua. Status setiap IOT_WS_REFRESH_STATUS_SEC detik,
        sales setiap IOT_WS_REFRESH_SALES_SEC detik (independen, tidak
        nempel ke tick status)."""
        elapsed_since_sales = IOT_WS_REFRESH_SALES_SEC  # kirim sales di tick pertama
        try:
            while self._total_connections() > 0:
                try:
                    machines = get_all_machines_status()
                    online_count = sum(1 for m in machines if m.get("online", False))

                    await self._broadcast_all({
                        "event": "machine_status",
                        "data": {
                            "machines": machines,
                            "summary": {
                                "total": len(machines),
                                "online": online_count,
                                "offline": len(machines) - online_count
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    })

                    if elapsed_since_sales >= IOT_WS_REFRESH_SALES_SEC:
                        await self._broadcast_all({
                            "event": "sales_update",
                            "data": {
                                "summary": get_sales_summary(None, "today"),
                                "recent_transactions": get_transactions_filtered(limit=10)[0],
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        })
                        elapsed_since_sales = 0

                    await asyncio.sleep(IOT_WS_REFRESH_STATUS_SEC)
                    elapsed_since_sales += IOT_WS_REFRESH_STATUS_SEC

                except Exception as e:
                    logger.error(f"IoT WS broadcast error: {e}")
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("IoT WS broadcast loop cancelled (tidak ada admin connect)")
        except Exception as e:
            logger.error(f"IoT WS broadcast loop fatal: {e}")
        finally:
            self._global_task = None

    async def _broadcast_all(self, message: dict):
        for user_id in list(self.connections.keys()):
            await self._send_to_user(user_id, message)

    async def _send_to_user(self, user_id: str, message: dict):
        if user_id not in self.connections:
            return

        dead = set()
        for ws in self.connections[user_id].copy():
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.add(ws)

        if dead:
            self.connections[user_id] -= dead


# Singleton
iot_ws_manager = IoTWebSocketManager()


@router.websocket("/ws/iot/{user_id}")
async def iot_websocket_endpoint(ws: WebSocket, user_id: str):
    """IoT Dashboard WebSocket."""
    await iot_ws_manager.connect(ws, user_id)

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
                elif msg.get("type") == "subscribe":
                    machine_id = msg.get("machine_id")
                    if machine_id:
                        await ws.send_text(json.dumps({
                            "type": "subscribed",
                            "machine_id": machine_id
                        }))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await iot_ws_manager.disconnect(ws, user_id)
    except Exception as e:
        await iot_ws_manager.disconnect(ws, user_id)
        logger.error(f"IoT WS error {user_id}: {e}")