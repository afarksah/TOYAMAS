// frontend/js/clock.js
/**
 * Clock Module
 * Update time display in UI
 */

// Gunakan IIFE (Immediately Invoked Function Expression) untuk menghindari konflik
(function() {
    'use strict';

    const ClockUI = {
        _elements: {},
        _interval: null,

        init() {
            console.log('[ClockUI] Initializing...');
            this._cacheElements();
            this.update();
            
            if (this._interval) {
                clearInterval(this._interval);
            }
            this._interval = setInterval(() => this.update(), 1000);
        },

        _cacheElements() {
            this._elements = {
                sClock: document.getElementById('sClock'),
                sDate: document.getElementById('sDate'),
            };
            console.log('[ClockUI] Elements cached:', this._elements);
        },

        update() {
            try {
                const d = new Date();
                const t = d.toLocaleTimeString('id-ID', {
                    hour: '2-digit',
                    minute: '2-digit',
                });
                const dt = d.toLocaleDateString('id-ID', {
                    weekday: 'short',
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                });

                if (this._elements.sClock) {
                    this._elements.sClock.textContent = t;
                }
                if (this._elements.sDate) {
                    this._elements.sDate.textContent = dt.toUpperCase();
                }
            } catch (e) {
                console.warn('[ClockUI] Update error:', e);
            }
        },

        destroy() {
            if (this._interval) {
                clearInterval(this._interval);
                this._interval = null;
            }
        }
    };

    // Ekspos ke global
    window.ClockUI = ClockUI;

    // Auto-init jika DOM sudah siap
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            if (window.ClockUI && window.ClockUI.init) {
                window.ClockUI.init();
            }
        });
    } else {
        if (window.ClockUI && window.ClockUI.init) {
            window.ClockUI.init();
        }
    }

    console.log('[ClockUI] Module loaded');
})();