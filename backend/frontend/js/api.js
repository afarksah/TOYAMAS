// frontend/js/api.js
/**
 * Toyamas Frontend API Client
 * Koneksi ke backend FastAPI via HTTP dan WebSocket
 */

const API = {
    baseURL: window.location.origin,
    wsURL: null,
    machineId: 'TYM-001',
    ws: null,
    wsReconnectTimer: null,
    wsReconnectAttempts: 0,
    maxReconnectAttempts: 10,
    eventHandlers: {},

    // ──────────────────────────────────────────────
    // INIT
    // ──────────────────────────────────────────────

    init(machineId = 'TYM-001') {
        this.machineId = machineId;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.wsURL = `${protocol}//${window.location.host}/ws/${machineId}`;
        console.log('[API] Initialized for machine:', machineId);
    },

    // ──────────────────────────────────────────────
    // HTTP REQUESTS
    // ──────────────────────────────────────────────

    async _fetch(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': 'true', // no-op kalau bukan lewat ngrok, aman dibiarkan
            ...options.headers,
        };

        try {
            const response = await fetch(url, {
                ...options,
                headers,
            });

            const data = await response.json();

            if (!response.ok) {
                throw {
                    status: response.status,
                    data: data,
                    message: data.detail || data.error || 'Request failed',
                };
            }

            return data;
        } catch (error) {
            if (error.status) throw error;
            console.error('[API] Network error:', error);
            throw {
                status: 0,
                message: 'Network error, please check your connection',
                data: null,
            };
        }
    },

    // ── Machine Status ──

    async getMachineStatus(machineId = null) {
        const id = machineId || this.machineId;
        return this._fetch(`/api/machine/status?machine_id=${id}`);
    },

    // ── Payment ──

    async createPayment(volumeLiter, paymentMethod = 'qris', walletName = 'QRIS Universal') {
        return this._fetch('/api/payment/create', {
            method: 'POST',
            body: JSON.stringify({
                volume_liter: volumeLiter,
                payment_method: paymentMethod,
                wallet_name: walletName,
                machine_id: this.machineId,
                kiosk_token: this._getKioskToken(),
            }),
        });
    },

    async getPaymentStatus(orderId) {
        return this._fetch(`/api/payment/status/${orderId}`);
    },

    // ── Ticket / Kiosk Session ──

    async getKioskSession() {
        return this._fetch(`/api/kiosk/session?machine_id=${this.machineId}`);
    },

    // ── Admin ──

    async getAdminReport(pin) {
        return this._fetch(`/api/admin/report/today?machine_id=${this.machineId}&admin_pin=${pin}`);
    },

    async updateConfig(pin, key, value) {
        return this._fetch('/api/admin/config', {
            method: 'POST',
            body: JSON.stringify({
                machine_id: this.machineId,
                admin_pin: pin,
                key: key,
                value: value,
            }),
        });
    },

    async changeAdminPin(oldPin, newPin, confirmPin) {
        return this._fetch('/api/admin/pin', {
            method: 'POST',
            body: JSON.stringify({
                machine_id: this.machineId,
                old_pin: oldPin,
                new_pin: newPin,
                confirm_pin: confirmPin,
            }),
        });
    },

    async sendAdminCommand(pin, cmd, volumeLiter = null) {
        return this._fetch('/api/admin/command', {
            method: 'POST',
            body: JSON.stringify({
                machine_id: this.machineId,
                admin_pin: pin,
                cmd: cmd,
                volume_liter: volumeLiter,
            }),
        });
    },

    // ──────────────────────────────────────────────
    // WEBSOCKET
    // ──────────────────────────────────────────────

    connectWebSocket() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WS] Already connected');
            return;
        }

        console.log('[WS] Connecting to', this.wsURL);
        this.ws = new WebSocket(this.wsURL);

        this.ws.onopen = () => {
            console.log('[WS] Connected');
            this.wsReconnectAttempts = 0;
            this._emit('connected', { machine_id: this.machineId });
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this._handleWebSocketMessage(msg);
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };

        this.ws.onclose = (event) => {
            console.log('[WS] Disconnected, code:', event.code);
            this._emit('disconnected', { code: event.code });
            this._scheduleReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('[WS] Error:', error);
            this._emit('error', { error: error });
        };
    },

    disconnectWebSocket() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        clearTimeout(this.wsReconnectTimer);
    },

    _scheduleReconnect() {
        if (this.wsReconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[WS] Max reconnect attempts reached');
            this._emit('reconnect_failed', {});
            return;
        }

        const delay = Math.min(1000 * Math.pow(2, this.wsReconnectAttempts), 30000);
        this.wsReconnectAttempts++;

        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.wsReconnectAttempts})`);
        this.wsReconnectTimer = setTimeout(() => {
            this.connectWebSocket();
        }, delay);
    },

    _handleWebSocketMessage(msg) {
        const { event, data } = msg;
        this._emit(event, data);
    },

    // ──────────────────────────────────────────────
    // EVENT SYSTEM
    // ──────────────────────────────────────────────

    on(event, handler) {
        if (!this.eventHandlers[event]) {
            this.eventHandlers[event] = [];
        }
        this.eventHandlers[event].push(handler);
    },

    off(event, handler) {
        if (!this.eventHandlers[event]) return;
        this.eventHandlers[event] = this.eventHandlers[event].filter(h => h !== handler);
    },

    _emit(event, data) {
        if (!this.eventHandlers[event]) return;
        this.eventHandlers[event].forEach(handler => {
            try {
                handler(data);
            } catch (e) {
                console.error('[WS] Handler error:', e);
            }
        });
    },

    // ──────────────────────────────────────────────
    // TOKEN MANAGEMENT
    // ──────────────────────────────────────────────

    _getKioskToken() {
        // Token disimpan di memory (bukan localStorage) untuk keamanan
        return this._kioskToken || '';
    },

    setKioskToken(token) {
        this._kioskToken = token;
    },

    // ──────────────────────────────────────────────
    // HELPERS
    // ──────────────────────────────────────────────

    isWebSocketConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    },

    formatRp(amount) {
        return 'Rp ' + Math.round(amount).toLocaleString('id-ID');
    },
};

// Export untuk digunakan di modul lain
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { API };
}