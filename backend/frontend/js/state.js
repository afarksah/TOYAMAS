// frontend/js/state.js
/**
 * Toyamas Application State
 * Centralized state management
 */

const AppState = {
    // ── Machine ──
    machineId: 'TYM-001',
    pricePerLiter: 500,
    isOnline: false,

    // ── Galon ──
    galon: {
        g1: { level: 75, status: 'OK' },
        g2: { level: 45, status: 'LOW' },
    },
    totalAvailableLiters: 22.9,

    // ── Order ──
    selectedVolume: 0.5,   // default = MEDIUM (500ml), sesuai card "sel" default di UI baru
    selectedWallet: 'QRIS Universal',
    currentOrderId: null,
    currentSessionId: null,

    // ── Filling ──
    isFilling: false,
    currentLiters: 0,
    targetLiters: 0.5,
    pctComplete: 0,

    // ── Admin ──
    adminPin: '1234',
    slideDuration: 5000,
    standbyTimeout: 30,

    // ── UI ──
    currentPage: 'page-standby',
    isAdminMode: false,

    // ── Listeners ──
    _listeners: {},

    // ──────────────────────────────────────────────

    init(machineId = 'TYM-001') {
        this.machineId = machineId;
        this._loadFromStorage();
    },

    _loadFromStorage() {
        try {
            const saved = sessionStorage.getItem('toyamas_state');
            if (saved) {
                const parsed = JSON.parse(saved);
                Object.assign(this, parsed);
                // Don't override sensitive/volatile data
                this.isFilling = false;
                this.currentLiters = 0;
                this.pctComplete = 0;
            }
        } catch (e) {
            // Ignore
        }
    },

    _saveToStorage() {
        try {
            const data = { ...this };
            // Exclude volatile data
            delete data._listeners;
            delete data.isFilling;
            delete data.currentLiters;
            delete data.pctComplete;
            sessionStorage.setItem('toyamas_state', JSON.stringify(data));
        } catch (e) {
            // Ignore
        }
    },

    // ── Getters ──

    getPrice() {
        return this.selectedVolume * this.pricePerLiter;
    },

    getFormattedPrice() {
        return 'Rp ' + this.getPrice().toLocaleString('id-ID');
    },

    getGalonLevel(index) {
        const key = 'g' + index;
        return this.galon[key] || { level: 0, status: 'UNKNOWN' };
    },

    getTotalAvailableLiters() {
        const g1 = this.galon.g1.level / 100 * 19;
        const g2 = this.galon.g2.level / 100 * 19;
        return Math.round((g1 + g2) * 100) / 100;
    },

    // ── Setters ──

    setGalon(index, level, status) {
        const key = 'g' + index;
        this.galon[key] = { level: Math.round(level), status: status || 'OK' };
        this.totalAvailableLiters = this.getTotalAvailableLiters();
        this._saveToStorage();
        this._emit('galon_update', { index, level, status });
    },

    setVolume(volume) {
        this.selectedVolume = volume;
        this._saveToStorage();
        this._emit('volume_change', volume);
    },

    setPrice(price) {
        this.pricePerLiter = price;
        this._saveToStorage();
        this._emit('price_change', price);
    },

    setOrder(orderId, sessionId) {
        this.currentOrderId = orderId;
        this.currentSessionId = sessionId;
        this._saveToStorage();
    },

    // ── Events ──

    on(event, handler) {
        if (!this._listeners[event]) {
            this._listeners[event] = [];
        }
        this._listeners[event].push(handler);
    },

    off(event, handler) {
        if (!this._listeners[event]) return;
        this._listeners[event] = this._listeners[event].filter(h => h !== handler);
    },

    _emit(event, data) {
        if (!this._listeners[event]) return;
        this._listeners[event].forEach(handler => {
            try {
                handler(data);
            } catch (e) {
                console.error('[State] Handler error:', e);
            }
        });
    },

    // ── Reset ──

    reset() {
        this.isFilling = false;
        this.currentLiters = 0;
        this.targetLiters = 0;
        this.pctComplete = 0;
        this.currentOrderId = null;
        this.currentSessionId = null;
        this._saveToStorage();
    },
};

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AppState };
}