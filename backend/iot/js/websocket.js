/**
 * websocket.js — WebSocket Client for IoT Dashboard
 * TOYAMAS IoT Dashboard
 */

const IoTWebSocket = (() => {

    let _ws = null;
    let _userEmail = null;
    let _reconnectTimer = null;
    let _reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;
    const BASE_URL = window.location.origin.replace('http', 'ws');

    // Event handlers
    let _handlers = {};

    // ──────────────────────────────────────

    function connect(userEmail) {
        if (_ws && _ws.readyState === WebSocket.OPEN) {
            return;
        }

        _userEmail = userEmail;
        const url = `${BASE_URL}/ws/iot/${encodeURIComponent(userEmail)}`;

        console.log('[WS IoT] Connecting to:', url);

        _ws = new WebSocket(url);

        _ws.onopen = () => {
            console.log('[WS IoT] Connected');
            _reconnectAttempts = 0;
            _emit('connected', {});
        };

        _ws.onclose = (event) => {
            console.log('[WS IoT] Disconnected:', event.code);
            _emit('disconnected', { code: event.code });
            _scheduleReconnect();
        };

        _ws.onerror = (error) => {
            console.error('[WS IoT] Error:', error);
            _emit('error', { error });
        };

        _ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                _handleMessage(data);
            } catch (e) {
                console.error('[WS IoT] Parse error:', e);
            }
        };
    }

    function disconnect() {
        if (_ws) {
            _ws.close();
            _ws = null;
        }
        clearTimeout(_reconnectTimer);
    }

    function _scheduleReconnect() {
        if (_reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.log('[WS IoT] Max reconnect attempts reached');
            _emit('reconnect_failed', {});
            return;
        }

        const delay = Math.min(1000 * Math.pow(2, _reconnectAttempts), 30000);
        _reconnectAttempts++;

        console.log(`[WS IoT] Reconnecting in ${delay}ms (attempt ${_reconnectAttempts})`);

        clearTimeout(_reconnectTimer);
        _reconnectTimer = setTimeout(() => {
            if (_userEmail) {
                connect(_userEmail);
            }
        }, delay);
    }

    function _handleMessage(data) {
        const { event, ...rest } = data;
        _emit(event, rest.data || rest);
    }

    function send(message) {
        if (_ws && _ws.readyState === WebSocket.OPEN) {
            _ws.send(JSON.stringify(message));
        } else {
            console.warn('[WS IoT] Cannot send — not connected');
        }
    }

    function ping() {
        send({ type: 'ping' });
    }

    function subscribe(machineId) {
        send({ type: 'subscribe', machine_id: machineId });
    }

    // ──────────────────────────────────────
    // Event System
    // ──────────────────────────────────────

    function on(event, handler) {
        if (!_handlers[event]) {
            _handlers[event] = [];
        }
        _handlers[event].push(handler);
    }

    function off(event, handler) {
        if (!_handlers[event]) return;
        _handlers[event] = _handlers[event].filter(h => h !== handler);
    }

    function _emit(event, data) {
        if (!_handlers[event]) return;
        _handlers[event].forEach(handler => {
            try {
                handler(data);
            } catch (e) {
                console.error('[WS IoT] Handler error:', e);
            }
        });
    }

    function isConnected() {
        return _ws && _ws.readyState === WebSocket.OPEN;
    }

    // ──────────────────────────────────────
    // Public API
    // ──────────────────────────────────────

    return {
        connect,
        disconnect,
        send,
        ping,
        subscribe,
        on,
        off,
        isConnected,
    };

})();

window.IoTWebSocket = IoTWebSocket;