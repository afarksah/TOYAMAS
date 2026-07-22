// frontend/js/admin.js
// Panel admin kiosk – hanya monitoring + tombol darurat + verifikasi PIN via backend

(function() {
    'use strict';

    const AdminUI = {
        _isInitialized: false,
        _pinStr: '',
        _validPin: null,  
        _elements: {},

        init() {
            if (this._isInitialized) return;
            this._cacheElements();
            this._bindEvents();
            // Ambil status mesin untuk tampilan monitoring
            this._loadStatus();
            this._isInitialized = true;
            console.log('[AdminUI] Initialized (lite version)');
        },

        _cacheElements() {
            this._elements = {
                pinModal: document.getElementById('pinModal'),
                pinDisplay: document.querySelectorAll('.pin-dot'),
                // Tombol emergency
                btnStop: document.getElementById('adminStopBtn'),
                btnReset: document.getElementById('adminResetBtn'),
                btnPing: document.getElementById('adminPingBtn'),
                // Monitoring
                adG1: document.getElementById('adG1'),
                adG2: document.getElementById('adG2'),
                adminWifiSub: document.getElementById('adminWifiSub'),
                adminWifiVal: document.getElementById('adminWifiVal'),
                // Laporan
                adminReportTotal: document.getElementById('adminReportTotal'),
                adminReportVolume: document.getElementById('adminReportVolume'),
                adminReportRevenue: document.getElementById('adminReportRevenue'),
            };
        },

        _bindEvents() {
            // PIN modal – handle keypad
            const modal = this._elements.pinModal;
            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) this.closePinModal();
                });
            }
            // Delegasi untuk tombol pin
            document.querySelectorAll('.pin-key').forEach(key => {
                key.addEventListener('click', (e) => {
                const val = e.currentTarget.dataset.value || e.target.textContent.trim();
                if (val === 'del') {
                    this._pinDel();
                } else if (val === 'enter') {
                    this._pinEnter();
                } else if (val && val.length === 1 && !isNaN(val)) {
                    this._pinInput(val);
                }
                });
            });
            // Tombol emergency
            const stopBtn = this._elements.btnStop;
            if (stopBtn) stopBtn.addEventListener('click', () => this._sendCommand('STOP'));
            const resetBtn = this._elements.btnReset;
            if (resetBtn) resetBtn.addEventListener('click', () => this._sendCommand('RESET'));
            const pingBtn = this._elements.btnPing;
            if (pingBtn) pingBtn.addEventListener('click', () => this._sendCommand('PING'));
        },

        // ── Buka / Tutup PIN Modal ──

        open() {
            this._pinStr = '';
            this._updatePinDisplay();
            const modal = this._elements.pinModal;
            if (modal) modal.classList.add('show');
        },

        closePinModal() {
            const modal = this._elements.pinModal;
            if (modal) modal.classList.remove('show');
            this._pinStr = '';
            this._updatePinDisplay();
        },

        // ── PIN Handling ──

        _pinInput(digit) {
            if (this._pinStr.length >= 4) return;
            this._pinStr += digit;
            this._updatePinDisplay();
        },
        _pinDel() {
            this._pinStr = this._pinStr.slice(0, -1);
            this._updatePinDisplay();
        },
        _pinEnter() {
            if (this._pinStr.length < 4) {
                showToast('Masukkan 4 digit PIN');
                return;
            }
            // Verifikasi ke backend
            this._verifyPinWithBackend(this._pinStr);
        },

        async _verifyPinWithBackend(pin) {
            try {
                const response = await fetch('/api/admin/verify-pin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin: pin })
                });
                const data = await response.json();
                if (response.ok) {
                    this._validPin = pin;   // simpan PIN
                    this.closePinModal();
                    goTo('page-admin');
                    this._loadStatus();
                    this._loadReport();     // load report dengan PIN yang valid
                } else {
                    showToast('❌ ' + (data.detail || 'PIN salah'));
                    this._pinStr = '';
                    this._updatePinDisplay();
                }
            } catch (err) {
                showToast('❌ Gagal verifikasi PIN: ' + err.message);
                this._pinStr = '';
                this._updatePinDisplay();
            }
        },

        _updatePinDisplay() {
            const dots = this._elements.pinDisplay;
            if (!dots) return;
            dots.forEach((dot, i) => {
                dot.classList.toggle('filled', i < this._pinStr.length);
            });
        },

        // ── Emergency Commands ──

        async _sendCommand(cmd) {
            // Minta PIN dulu
            this.open();
            // Setelah PIN valid, jalankan perintah
            // Override _pinEnter untuk sementara
            const originalEnter = this._pinEnter;
            this._pinEnter = async () => {
                if (this._pinStr.length < 4) return;
                try {
                    const response = await fetch('/api/admin/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            admin_pin: this._pinStr,
                            cmd: cmd,
                        })
                    });
                    const data = await response.json();
                    if (response.ok) {
                        showToast(`✅ Perintah ${cmd} berhasil dikirim`);
                    } else {
                        showToast('❌ ' + (data.detail || 'Gagal'));
                    }
                } catch (err) {
                    showToast('❌ Error: ' + err.message);
                }
                this.closePinModal();
                this._pinEnter = originalEnter;
            };
            // Jalankan PIN modal
            this.open();
        },

        // ── Load Status & Report ──

        async _loadStatus() {
            try {
                const data = await API.getMachineStatus();
                if (data.galon) {
                    const g1 = data.galon.g1_level_pct || 0;
                    const g2 = data.galon.g2_level_pct || 0;
                    if (this._elements.adG1) {
                        this._elements.adG1.textContent = `${g1.toFixed(0)}% — ${(g1/100*19).toFixed(1)}L`;
                    }
                    if (this._elements.adG2) {
                        this._elements.adG2.textContent = `${g2.toFixed(0)}% — ${(g2/100*19).toFixed(1)}L`;
                    }
                }
                if (data.settings) {
                    // Tampilkan harga dan info lain di UI (opsional)
                }
            } catch (e) {
                console.warn('[AdminUI] Load status error:', e);
            }
        },

        async _loadReport() {
            if (!this._validPin) {
                // Jika belum ada PIN, coba pakai default (tapi seharusnya tidak terjadi)
                console.warn('[AdminUI] No valid PIN, using default 1234');
                // this._validPin = '1234'; // jangan, biarkan gagal
            }
            try {
                // Gunakan PIN yang valid
                const data = await API.getAdminReport(this._validPin || '1234');
                if (data) {
                    if (this._elements.adminReportTotal) {
                        this._elements.adminReportTotal.textContent = data.total_transactions || 0;
                    }
                    if (this._elements.adminReportVolume) {
                        this._elements.adminReportVolume.textContent = (data.volume_liters || 0).toFixed(1) + ' L';
                    }
                    if (this._elements.adminReportRevenue) {
                        this._elements.adminReportRevenue.textContent = 'Rp ' + (data.revenue_gross || 0).toLocaleString('id-ID');
                    }
                }
            } catch (e) {
                console.warn('[AdminUI] Load report error:', e);
            }
        }
    };

    // Ekspos ke global
    window.AdminUI = AdminUI;

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            if (window.AdminUI && window.AdminUI.init) window.AdminUI.init();
        });
    } else {
        if (window.AdminUI && window.AdminUI.init) window.AdminUI.init();
    }

    console.log('[AdminUI] Module loaded (lite version)');
})();