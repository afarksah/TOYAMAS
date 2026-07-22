// frontend/js/ticket.js
/**
 * Ticket Module — ALUR BARU
 * 1. Input 6 digit → verify-code → tampilkan QR + info
 * 2. Timer & auto-refresh
 * 3. Event WS 'ticket_verified' → modal → guide (hanya dengan tombol)
 */

(function() {
    'use strict';

    const TicketUI = {
        _elements: {},
        _timerInterval: null,
        _remainingSeconds: 180,
        _verifySession: null,
        _currentVolume: 0,
        _currentTicketCode: '',
        _currentAccountName: '',
        _isInitialized: false,

        init() {
            if (this._isInitialized) return;
            this._cacheElements();
            this._bindEvents();
            this._isInitialized = true;
            console.log('[TicketUI] Initialized (new flow)');
        },

        _cacheElements() {
            this._elements = {
                ticketCodeInput: document.getElementById('ticketCodeInput'),
                btnVerify: document.getElementById('btnVerifyCode'),
                errorEl: document.getElementById('ticketCodeError'),
                loadingEl: document.getElementById('ticketCodeLoading'),
                ticketUserName: document.getElementById('ticketUserName'),
                ticketCodeDisplay: document.getElementById('ticketCodeDisplay'),
                ticketVolumeDisplay: document.getElementById('ticketVolumeDisplay'),
                ticketTimer: document.getElementById('ticketTimer'),
                ticketQrCanvas: document.getElementById('ticketQrCanvas'),
                verifModal: document.getElementById('ticketVerifModal'),
                vTicketNum: document.getElementById('vTicketNum'),
                vTicketVol: document.getElementById('vTicketVol'),
                btnTicketProceed: document.getElementById('btnTicketProceed'),
            };
        },

        _bindEvents() {
            const btn = this._elements.btnVerify;
            if (btn) {
                btn.addEventListener('click', () => this._handleVerify());
            }
            const input = this._elements.ticketCodeInput;
            if (input) {
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        this._handleVerify();
                    }
                });
                input.addEventListener('input', () => {
                    this._elements.ticketCodeInput.value = this._elements.ticketCodeInput.value.toUpperCase();
                });
            }

            // Event dari WebSocket
            if (typeof API !== 'undefined') {
                API.on('ticket_verified', (data) => {
                    this.showVerificationSuccess(data);
                });
            }

            // Tombol proceed di modal
            const proceed = this._elements.btnTicketProceed;
            if (proceed) {
                proceed.addEventListener('click', () => {
                    this._elements.verifModal.classList.remove('show');
                    this._goToGuide();
                });
            }

            // Cleanup saat halaman ticket ditutup
            const observer = new MutationObserver(() => {
                const page = document.getElementById('page-ticket');
                if (page && !page.classList.contains('active')) {
                    this._cleanup();
                }
                const pageCode = document.getElementById('page-ticket-code');
                if (pageCode && pageCode.classList.contains('active')) {
                    const err = document.getElementById('ticketCodeError');
                    if (err) err.style.display = 'none';
                    const input = document.getElementById('ticketCodeInput');
                    if (input) { input.value = ''; input.focus(); }
                }
            });
            document.querySelectorAll('.page').forEach(p => {
                observer.observe(p, { attributes: true, attributeFilter: ['class'] });
            });
        },

        // ─── VERIFY CODE ──────────────────────────────────────

        async _handleVerify() {
            const input = this._elements.ticketCodeInput;
            const code = input.value.trim().toUpperCase();
            const err = this._elements.errorEl;

            if (code.length !== 6 || !/^[A-Z0-9]{6}$/.test(code)) {
                err.textContent = 'Masukkan 6 digit alfanumerik (contoh: MPH6GV)';
                err.style.display = 'block';
                return;
            }
            err.style.display = 'none';

            const btn = this._elements.btnVerify;
            const loading = this._elements.loadingEl;
            btn.disabled = true;
            btn.textContent = '⏳ Memeriksa...';
            loading.style.display = 'block';

            try {
                const machineId = typeof API !== 'undefined' ? API.machineId : 'TYM-001';
                const resp = await fetch('/api/ticket/verify-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code, machine_id: machineId })
                });
                const data = await resp.json();

                if (!data.success) {
                    const errMap = {
                        'RATE_LIMITED': 'Terlalu banyak percobaan. Coba lagi dalam 10 menit.',
                        'CODE_NOT_FOUND': 'Kode tidak valid atau tiket sudah kedaluwarsa.',
                    };
                    err.textContent = errMap[data.error] || 'Kode tidak ditemukan. Periksa kembali 6 digit terakhir.';
                    err.style.display = 'block';
                    return;
                }

                this._verifySession = data.verify_session;
                this._currentVolume = data.volume_liter;
                this._currentTicketCode = data.ticket_code_masked;
                this._currentAccountName = data.account_name;

                const userNameEl = this._elements.ticketUserName;
                if (userNameEl) userNameEl.textContent = '👤 ' + data.account_name;
                const codeEl = this._elements.ticketCodeDisplay;
                if (codeEl) codeEl.textContent = data.ticket_code_masked;
                const volEl = this._elements.ticketVolumeDisplay;
                if (volEl) {
                    const ml = Math.round(data.volume_liter * 1000);
                    volEl.textContent = ml + ' ml';
                }

                this._renderQR(data.verify_session);
                goTo('page-ticket');
                this._startTimer(180);

            } catch (e) {
                err.textContent = 'Gagal menghubungi server. Coba lagi.';
                err.style.display = 'block';
                console.error('[Ticket] verify-code error:', e);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Cari Tiket →';
                loading.style.display = 'none';
            }
        },

        // ─── QR RENDER ──────────────────────────────────────

        _renderQR(value) {
            const canvas = this._elements.ticketQrCanvas;
            if (!canvas) return;
            if (typeof QRious === 'undefined') {
                console.error('[Ticket] QRious library not loaded');
                return;
            }
            try {
                new QRious({
                    element: canvas,
                    value: value,
                    size: 180,
                    background: '#ffffff',
                    foreground: '#1A3A52',
                    level: 'M',
                    padding: 8,
                });
            } catch (e) {
                console.error('[Ticket] QR render error:', e);
            }
        },

        // ─── TIMER ──────────────────────────────────────────

        _startTimer(seconds) {
            clearInterval(this._timerInterval);
            this._remainingSeconds = seconds;
            const tick = () => {
                const m = String(Math.floor(this._remainingSeconds / 60)).padStart(2, '0');
                const s = String(this._remainingSeconds % 60).padStart(2, '0');
                const el = this._elements.ticketTimer;
                if (el) {
                    el.textContent = m + ':' + s;
                    el.classList.toggle('urgent', this._remainingSeconds <= 15);
                }
                if (this._remainingSeconds <= 0) {
                    clearInterval(this._timerInterval);
                    showToast('⏳ Sesi habis, silakan masukkan ulang kode tiket.');
                    goTo('page-ticket-code');
                }
                this._remainingSeconds--;
            };
            tick();
            this._timerInterval = setInterval(tick, 1000);
        },

        // ─── VERIFICATION SUCCESS (PUBLIC) ──────────────────

        showVerificationSuccess(data) {
            clearInterval(this._timerInterval);

            // Set pending order & volume untuk digunakan di guide
            window._pendingOrderId = data.order_id || null;
            window._pendingVolume = data.volume_liter || 0;
            window._pendingSessionId = data.session_id || null;

            // Update AppState
            if (typeof AppState !== 'undefined' && data.volume_liter) {
                AppState.setVolume(data.volume_liter);
            }

            const modal = this._elements.verifModal;
            if (!modal) return;

            if (this._elements.vTicketNum) {
                this._elements.vTicketNum.textContent = data.ticket_code || 'TKT-XXXX';
            }
            if (this._elements.vTicketVol) {
                const ml = Math.round((data.volume_liter || 0) * 1000);
                this._elements.vTicketVol.textContent = ml + ' ml';
            }

            modal.classList.add('show');

            // Tidak ada auto-close! Hanya tombol yang menutup.
        },

        // ─── NAVIGASI KE GUIDE ─────────────────────────────

        _goToGuide() {
            goTo('page-guide');
            // Checklist akan di-centang otomatis oleh app.js (tickGuideCheck)
            setTimeout(() => {
                if (typeof tickGuideCheck === 'function') {
                    tickGuideCheck(0);
                    setTimeout(() => tickGuideCheck(1), 800);
                    setTimeout(() => tickGuideCheck(2), 1600);
                }
            }, 500);
        },

        // ─── CLEANUP ────────────────────────────────────────

        _cleanup() {
            clearInterval(this._timerInterval);
            this._verifySession = null;
            const err = this._elements.errorEl;
            if (err) err.style.display = 'none';
            const modal = this._elements.verifModal;
            if (modal) modal.classList.remove('show');
        },

        // ─── OPEN / CLOSE ──────────────────────────────────

        open() {
            goTo('page-ticket-code');
            const input = this._elements.ticketCodeInput;
            if (input) {
                input.value = '';
                input.focus();
            }
            const err = this._elements.errorEl;
            if (err) err.style.display = 'none';
            const canvas = this._elements.ticketQrCanvas;
            if (canvas) {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        },

        close() {
            this._cleanup();
        }
    };

    window.TicketUI = TicketUI;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            if (window.TicketUI && window.TicketUI.init) window.TicketUI.init();
        });
    } else {
        if (window.TicketUI && window.TicketUI.init) window.TicketUI.init();
    }

    console.log('[TicketUI] Module loaded (new flow)');
})();