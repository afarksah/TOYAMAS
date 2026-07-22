// frontend/js/galon.js
/**
 * Galon UI Module
 * Update galon display in UI
 */

const GalonUI = {
    _elements: {},

    // ──────────────────────────────────────────────

    init() {
        this._cacheElements();
        this._bindEvents();
        this.update(75, 45);
    },

    _cacheElements() {
        this._elements = {
            mf1: document.getElementById('mf1'),
            mf2: document.getElementById('mf2'),
            mp1: document.getElementById('mp1'),
            mp2: document.getElementById('mp2'),
            ml1: document.getElementById('ml1'),
            ml2: document.getElementById('ml2'),
            gt1s: document.getElementById('gt1s'),
            gt2s: document.getElementById('gt2s'),
            adG1: document.getElementById('adG1'),
            adG2: document.getElementById('adG2'),
        };
    },

    _bindEvents() {
        AppState.on('galon_update', (data) => {
            this.updateSingle(data.index, data.level, data.status);
        });
    },

    // ──────────────────────────────────────────────

    update(g1Level, g2Level) {
        this.updateSingle(1, g1Level);
        this.updateSingle(2, g2Level);
    },

    updateSingle(index, level, status) {
        const pct = Math.round(level);
        const lit = (level / 100 * 19).toFixed(1);
        const el = this._elements;

        const mf = el['mf' + index];
        const mp = el['mp' + index];
        const ml = el['ml' + index];
        const gt = el['gt' + index + 's'];
        const ad = el['adG' + index];

        if (mf) mf.style.height = Math.min(pct, 100) + '%';
        if (mp) {
            mp.textContent = pct + '%';
            mp.className = 'mini-pct' + (pct < 25 ? ' low' : '');
        }
        if (ml) ml.textContent = lit + ' Liter';
        if (gt) {
            const isLow = pct < 25;
            gt.textContent = isLow ? 'Rendah' : 'Normal';
            gt.className = 'gt-status ' + (isLow ? 'low' : 'ok');
        }
        if (ad) ad.textContent = `${pct}% — ${lit}L`;
    },

    // ──────────────────────────────────────────────

    updateFromMQTT(mqttData) {
        const galon = mqttData.galon || {};
        const g1 = galon.g1_level_pct || 0;
        const g2 = galon.g2_level_pct || 0;
        this.update(g1, g2);

        // Update AppState
        AppState.setGalon(1, g1, galon.g1_status);
        AppState.setGalon(2, g2, galon.g2_status);
    },
};

// Export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { GalonUI };
}
// Ekspos ke global
window.GalonUI = GalonUI;

// Auto-init
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        if (window.GalonUI && window.GalonUI.init) {
            window.GalonUI.init();
        }
    });
} else {
    if (window.GalonUI && window.GalonUI.init) {
        window.GalonUI.init();
    }
}

console.log('[GalonUI] Module loaded');