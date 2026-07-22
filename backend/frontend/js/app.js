// frontend/js/app.js
/**
 * TOYAMAS - Main Application Bridge
 * Menyediakan fungsi global untuk kompatibilitas dengan HTML
 * dan menginisialisasi semua modul
 */

// ──────────────────────────────────────────────
// Ekspos fungsi global untuk HTML onclick
// ──────────────────────────────────────────────

// ── Navigasi ──
window.goTo = function(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');

    // Update state
    if (typeof AppState !== 'undefined') {
        AppState.currentPage = pageId;
        // Di dalam fungsi goTo, setelah baris AppState.currentPage = pageId:
        const tapZoneAdmin   = document.getElementById('tapZoneAdmin');
        const tapZonePreview = document.getElementById('tapZonePreview');
        const isStandby = (pageId === 'page-standby');
        if (tapZoneAdmin)   tapZoneAdmin.style.display   = isStandby ? 'block' : 'none';
        if (tapZonePreview) tapZonePreview.style.display  = isStandby ? 'block' : 'none';
    }

    // Signage control
    if (pageId === 'page-standby') {
        if (typeof SignageUI !== 'undefined' && SignageUI.start) {
            SignageUI.start();
        }
        // Start standy timer
        clearTimeout(_standbyTimer);
    } else {
        if (typeof SignageUI !== 'undefined' && SignageUI.stop) {
            SignageUI.stop();
        }
        resetStandbyTimer();
    }

    // Update galon
    if (typeof GalonUI !== 'undefined' && GalonUI.update) {
        if (typeof AppState !== 'undefined') {
            GalonUI.update(
                AppState.galon?.g1?.level || 75,
                AppState.galon?.g2?.level || 45
            );
        }
    }
};

// ── Reset Signage ──
window.resetSignage = function() {
    if (typeof SignageUI !== 'undefined' && SignageUI.resetSignage) {
        SignageUI.resetSignage();
    } else {
        // Fallback: disable video manual
        const video = document.getElementById('videoSignage');
        if (video) {
            video.pause();
            video.src = '';
            video.style.display = 'none';
        }
        
        // Reset background
        const standby = document.getElementById('page-standby');
        if (standby) {
            standby.style.background = 'linear-gradient(180deg, #0d4f7c 0%, #1a7fc1 45%, #5bb8f5 100%)';
        }
        
        // Tampilkan elemen yang hilang
        document.querySelector('.water-visual').style.display = '';
        document.querySelector('.wave-bg').style.display = '';
        document.getElementById('dropsDeco').style.display = '';
        document.querySelector('.slide-area').style.display = '';
        
        // Reset slide
        if (typeof SignageUI !== 'undefined' && SignageUI.reset) {
            SignageUI.reset();
            SignageUI.start();
        }
        
        showToast('✓ Signage direset ke default');
    }
};

// Ubah fungsi goToStandby
window.goToStandby = function() {
    resetTransactionState(); // Reset state sebelum pindah
    goTo('page-standby');
    if (typeof FillingUI !== 'undefined' && FillingUI.reset) {
        FillingUI.reset();
    }
    if (typeof TicketUI !== 'undefined' && TicketUI.close) {
        TicketUI.close();
    }
    resetFillingUI();
    // Reset AppState
    if (typeof AppState !== 'undefined') {
        AppState.isFilling = false;
        AppState.currentLiters = 0;
        AppState.pctComplete = 0;
    }
    
    console.log('[App] Returned to standby with clean state');
};

window.goToMenu = function() {
    goTo('page-menu');
    updatePriceDisplay();
};

window.goToPayment = function() {
    updateOrderSummary();
    goTo('page-payment');
};

// ── Filling UI Reset ──
function resetFillingUI() {
    const elements = {
        bigFill: document.getElementById('bigFill'),
        tankLabel: document.getElementById('tankLabel'),
        fillBar: document.getElementById('fillBar'),
        fillPct: document.getElementById('fillPct'),
        fillCurrent: document.getElementById('fillCurrent'),
        fillTarget: document.getElementById('fillTarget'),
        fillTitle: document.getElementById('fillTitle'),
        fillSub: document.getElementById('fillSub'),
        fillStatusBadge: document.getElementById('fillStatusBadge'),
        bigTank: document.getElementById('bigTank'),
        successIcon: document.getElementById('successIcon'),
        fillDoneBtn: document.getElementById('fillDoneBtn'),
    };

    if (elements.bigFill) elements.bigFill.style.height = '0%';
    if (elements.tankLabel) elements.tankLabel.textContent = '0%';
    if (elements.fillBar) elements.fillBar.style.width = '0%';
    if (elements.fillPct) elements.fillPct.textContent = '0%';
    if (elements.fillCurrent) elements.fillCurrent.textContent = '0.0';
    if (elements.bigTank) elements.bigTank.style.display = '';
    if (elements.successIcon) elements.successIcon.style.display = 'none';
    if (elements.fillDoneBtn) elements.fillDoneBtn.style.display = 'none';
    if (elements.fillTitle) elements.fillTitle.textContent = 'Mengisi Air...';
    if (elements.fillSub) elements.fillSub.textContent = 'Harap tunggu, jangan pindahkan galon';
    if (elements.fillStatusBadge) {
        elements.fillStatusBadge.textContent = 'Mengisi...';
        elements.fillStatusBadge.style.background = '#e8f4ff';
        elements.fillStatusBadge.style.color = '#2A91D8';
    }
}

// ──────────────────────────────────────────────
// KONVERSI TAMPILAN ml <-> Liter
// ──────────────────────────────────────────────
// PENTING: Backend, ESP32, dan AppState.selectedVolume TETAP memakai Liter
// (tidak ada satupun kode di luar tampilan UI ini yang diubah satuannya).
// Fungsi di bawah ini HANYA dipakai untuk menampilkan angka ke pengguna
// dalam satuan mililiter (ml), sesuai permintaan desain UI baru.

// Liter (float) -> teks ml untuk ditampilkan, contoh: 0.25 -> "250 ml"
window.formatMl = function(liter) {
    const ml = Math.round(liter * 1000);
    return ml.toLocaleString('id-ID') + ' ml';
};

// ml (integer, dari keyboard custom) -> Liter (float) untuk disimpan ke AppState
window.mlToLiter = function(ml) {
    return ml / 1000;
};

// Liter (float) -> ml (integer) — kebalikan dari mlToLiter, untuk tampilan angka saja
window.literToMl = function(liter) {
    return Math.round(liter * 1000);
};


window.updatePriceDisplay = function() {
    const vol = typeof AppState !== 'undefined' ? AppState.selectedVolume : 0.5;
    const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;
    const total = vol * price;

    const elements = {
        priceDetail: document.getElementById('priceDetail'),
        totalPrice: document.getElementById('totalPrice'),
        btnPrice: document.getElementById('btnPrice'),
    };

    if (elements.priceDetail) {
        // Tampilan ml — backend/AppState tetap menyimpan Liter, tidak diubah
        elements.priceDetail.textContent = `${formatMl(vol)} × Rp ${price.toLocaleString('id')}/L`;
    }
    if (elements.totalPrice) {
        elements.totalPrice.textContent = formatRp(total);
    }
    if (elements.btnPrice) {
        elements.btnPrice.textContent = formatRp(total);
    }
    // Catatan: fillTarget SENGAJA tidak disentuh di sini.
    // Nilainya dikontrol penuh oleh filling.js dari data realtime ESP32
    // (satuan Liter sesuai PAYLOAD_SPEC backend).
};

// ── Order Summary ──
window.updateOrderSummary = function() {
    const vol = typeof AppState !== 'undefined' ? AppState.selectedVolume : 0.5;
    const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;
    const total = vol * price;

    const elements = {
        osSummaryVol: document.getElementById('osSummaryVol'),
        osPricePerL: document.getElementById('osPricePerL'),
        osSummaryPrice: document.getElementById('osSummaryPrice'),
        osSummaryTotal: document.getElementById('osSummaryTotal'),
    };

    if (elements.osSummaryVol) elements.osSummaryVol.textContent = formatMl(vol);
    if (elements.osPricePerL) elements.osPricePerL.textContent = formatRp(price) + ' / Liter';
    if (elements.osSummaryPrice) elements.osSummaryPrice.textContent = formatRp(total);
    if (elements.osSummaryTotal) elements.osSummaryTotal.textContent = formatRp(total);
};

// ── Format Rupiah ──
window.formatRp = function(n) {
    return 'Rp ' + Math.round(n).toLocaleString('id-ID');
};

// ── Volume Selection ──
window.selectVol = function(el, vol) {
    document.querySelectorAll('.vol-tile').forEach(t => t.classList.remove('sel'));
    el.classList.add('sel');
    if (typeof AppState !== 'undefined') {
        AppState.setVolume(vol);   // tetap disimpan dalam Liter
    }
    // Reset tampilan tombol custom ke kondisi default
    const customDisplay = document.getElementById('customVolDisplay');
    const customLabel = document.getElementById('customVolLabel');
    if (customDisplay) customDisplay.textContent = '✏️';
    if (customLabel) customLabel.textContent = 'Custom Volume';
    updatePriceDisplay();
};

// ── Custom Keyboard (skala ml: 100-2000ml, bilangan bulat) ──
window.openCustomKeyboard = function() {
    const modal = document.getElementById('customKbModal');
    if (modal) modal.classList.add('show');
    // Mulai dari kosong — JANGAN pre-fill dengan nilai lama, karena ckbPress
    // hanya mengganti buffer saat persis "0". Kalau diisi "500" lalu user
    // menekan 8,8,0, hasilnya akan menyambung jadi "5008", bukan "880".
    window._ckbStr = '0';
    updateCkbDisplay();
};

window.ckbPress = function(ch) {
    const errEl = document.getElementById('ckbError');
    if (errEl) errEl.classList.remove('show');

    let str = window._ckbStr || '0';
    if (str === '0') str = ch;
    else str += ch;
    // Maks 4 digit (2000 ml)
    if (str.length > 4) str = str.slice(0, 4);

    window._ckbStr = str;
    updateCkbDisplay();
};

window.ckbDel = function() {
    const errEl = document.getElementById('ckbError');
    if (errEl) errEl.classList.remove('show');

    let str = window._ckbStr || '0';
    if (str.length <= 1) str = '0';
    else str = str.slice(0, -1);
    window._ckbStr = str;
    updateCkbDisplay();
};

function updateCkbDisplay() {
    const valEl = document.getElementById('ckbValue');
    const hintEl = document.getElementById('ckbPriceHint');
    const mlVal = parseInt(window._ckbStr || '0', 10) || 0;
    if (valEl) valEl.textContent = mlVal;
    if (hintEl) {
        const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;
        const liter = mlToLiter(mlVal);
        hintEl.textContent = '= ' + formatRp(liter * price);
    }
}

window.ckbCancel = function() {
    const modal = document.getElementById('customKbModal');
    if (modal) modal.classList.remove('show');
};

window.ckbOk = function() {
    const mlVal = parseInt(window._ckbStr || '0', 10) || 0;
    const errEl = document.getElementById('ckbError');
    if (mlVal < 100 || mlVal > 2000) {
        if (errEl) errEl.classList.add('show');
        return;
    }

    const liter = mlToLiter(mlVal);   // konversi ke Liter — inilah yang disimpan
    if (typeof AppState !== 'undefined') {
        AppState.setVolume(liter);
    }
    document.querySelectorAll('.vol-tile').forEach(t => t.classList.remove('sel'));
    const customTile = document.getElementById('customVolTile');
    if (customTile) customTile.classList.add('sel');

    const display = document.getElementById('customVolDisplay');
    const label = document.getElementById('customVolLabel');
    if (display) display.textContent = mlVal + ' ml';
    if (label) label.textContent = 'Custom Volume';

    updatePriceDisplay();
    document.getElementById('customKbModal')?.classList.remove('show');
};

// ── Wallet Selection ──
window.selectWallet = function(el, name) {
    document.querySelectorAll('.pay-method').forEach(m => m.classList.remove('sel'));
    el.classList.add('sel');
    if (typeof AppState !== 'undefined') {
        AppState.selectedWallet = name;
    }
};

// ── QR Code ──

// Render QR asli ke canvas #qrCanvas dari sebuah string (qr_string Xendit,
// atau string apapun untuk mode demo/fallback). Pakai QRious (canvas-based) —
// lihat index.html untuk tag <script> CDN-nya.
window.renderPaymentQR = function(qrValue) {
    const canvas = document.getElementById('qrCanvas');
    if (!canvas) return;

    if (!qrValue) {
        console.warn('[QR] qr_string kosong, tidak ada yang bisa dirender');
        return;
    }

    if (typeof QRious === 'undefined') {
        console.error('[QR] Library QRious belum termuat (cek koneksi internet kios)');
        return;
    }

    try {
        new QRious({
            element:    canvas,
            value:      qrValue,
            size:       180,
            background: '#ffffff',
            foreground: '#1A3A52',
            level:      'M',
            padding:    8,
        });
    } catch (err) {
        console.error('[QR] Gagal render QR:', err);
    }
};

window.goToQR = function() {
    const vol = typeof AppState !== 'undefined' ? AppState.selectedVolume : 5;
    const wallet = typeof AppState !== 'undefined' ? AppState.selectedWallet : 'QRIS Universal';
    const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;

    // Show loading
    showToast('⏳ Memproses pembayaran...');

    if (typeof API !== 'undefined') {
        API.createPayment(vol, 'qris', wallet)
            .then(data => {
                // Update QR display
                const orderIdEl = document.getElementById('qrOrderId');
                const amountEl = document.getElementById('qrAmount');
                const walletEl = document.getElementById('qrWalletName');
                const badgeEl = document.getElementById('qrBadge');

                if (orderIdEl) orderIdEl.textContent = data.order_id;
                if (amountEl) amountEl.textContent = formatRp(data.amount);
                if (walletEl) walletEl.textContent = data.wallet_name || wallet;
                if (badgeEl) badgeEl.innerHTML = '💳 ' + (data.wallet_name || wallet);

                // Render QR asli dari qr_string (Xendit QRIS) — bisa discan
                // langsung pakai e-wallet/m-banking apapun yang support QRIS.
                renderPaymentQR(data.qr_string);

                if (typeof AppState !== 'undefined') {
                    AppState.setOrder(data.order_id, data.session_id);
                }

                startQRTimer();
                goTo('page-qr');
                showToast('Scan QR menggunakan e-wallet Anda');
            })
            .catch(err => {
                console.error('[Payment] Error:', err);
                // PENTING: FastAPI membungkus HTTPException(detail={...}) jadi
                // {"detail": {...}} di body response — sebelumnya kode di sini
                // baca err.data.error (selalu undefined, tidak pernah cocok).
                // Detail sebenarnya ada di err.data.detail.
                const errDetail = (err.data && err.data.detail) || {};
                if (errDetail.error === 'GALON_INSUFFICIENT') {
                    showToast('❌ Stok air tidak mencukupi! Tersedia: ' +
                        (errDetail.available_liters || 0) + 'L');
                } else if (errDetail.error === 'MACHINE_BUSY') {
                    showToast('⏳ Mesin sedang memproses transaksi lain, coba beberapa saat lagi');
                    setTimeout(() => goToStandby(), 2000);
                } else {
                    showToast('❌ Gagal memproses pembayaran: ' + err.message);
                }
            });
    } else {
        // Fallback: simulasi
        const orderId = 'TYM-' + Date.now().toString().slice(-6);
        document.getElementById('qrOrderId').textContent = orderId;
        document.getElementById('qrAmount').textContent = formatRp(vol * price);
        document.getElementById('qrWalletName').textContent = wallet;
        document.getElementById('qrBadge').innerHTML = '💳 ' + wallet;
        renderPaymentQR('toyamas-demo://' + orderId);
        startQRTimer();
        goTo('page-qr');
        showToast('Scan QR menggunakan e-wallet Anda (DEMO)');
    }
};

window.startQRTimer = function() {
    clearInterval(window._qrTimerInt);
    let sec = 300;
    const tick = () => {
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        const el = document.getElementById('qrTimer');
        if (el) {
            el.textContent = m + ':' + s;
            el.classList.toggle('urgent', sec <= 30);
        }
        if (sec <= 0) {
            clearInterval(window._qrTimerInt);
            showToast('QR kedaluwarsa. Silakan coba lagi.');
            setTimeout(() => goTo('page-payment'), 1500);
        }
        sec--;
    };
    tick();
    window._qrTimerInt = setInterval(tick, 1000);
};

// ── Payment Success Simulation ──
window.simulatePaymentSuccess = function() {
    clearInterval(window._qrTimerInt);
    showToast('✓ Pembayaran berhasil dikonfirmasi!');
    // Reset state transaksi sebelumnya
    resetTransactionState();

    setTimeout(() => {
        // Set state baru untuk transaksi ini
        const orderId = typeof AppState !== 'undefined' ? AppState.currentOrderId : 'TYM-DEMO-' + Date.now().toString().slice(-6);
        const volume = typeof AppState !== 'undefined' ? AppState.selectedVolume : 5;
        const sessionId = typeof AppState !== 'undefined' ? AppState.currentSessionId : 'sess_demo';
        
        window._pendingOrderId = orderId;
        window._pendingVolume = volume;
        window._pendingSessionId = sessionId;

    // Kirim event ke API jika ada
        if (typeof API !== 'undefined') {
            API._emit('payment_confirmed', {
                order_id: orderId,
                volume_liter: volume,
                session_id: sessionId,
            });
        }
        goTo('page-guide');

        // Reset checklist guide
        for (let i = 1; i <= 3; i++) {
            const item = document.getElementById('gcl' + i);
            const chk = document.getElementById('gck' + i);
            if (item) item.classList.remove('done');
            if (chk) chk.textContent = '○';
        }
        _guideCheckedCount = 0;

        setTimeout(() => {
            tickGuideCheck(0);
            setTimeout(() => tickGuideCheck(1), 800);
            setTimeout(() => tickGuideCheck(2), 1600);
        }, 500);
    }, 1200);
};

// ── Guide / Checklist ──
let _guideCheckedCount = 0;

window.tickGuideCheck = function(idx) {
    const id = idx + 1;
    const item = document.getElementById('gcl' + id);
    const chk = document.getElementById('gck' + id);
    if (item) item.classList.add('done');
    if (chk) chk.textContent = '✓';
    _guideCheckedCount++;
};

// app.js - perbaiki confirmGuideAndFill

window.confirmGuideAndFill = function() {
    const btn = document.getElementById('btnGuideStart');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="white"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg> Menghitung mundur...`;
    }

    // Ambil order_id yang disimpan
    const orderId = window._pendingOrderId
        || (typeof AppState !== 'undefined' ? AppState.currentOrderId : null);

    if (!orderId) {
        showToast('❌ Sesi tidak valid. Kembali ke menu.');
        setTimeout(() => goToStandby(), 1500);
        return;
    }

    // Kirim konfirmasi ke backend
    fetch('/api/payment/confirm-dispense', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: orderId }),
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'ok') {
            // Mulai countdown 10 detik
            const wrap = document.getElementById('guideCountdownWrap');
            if (wrap) wrap.style.display = 'block';

            let sec = 10;
            const tick = () => {
                const disp = document.getElementById('guideCountDisp');
                const secEl = document.getElementById('guideCountSec');
                const fill = document.getElementById('guideCountFill');
                if (disp) disp.textContent = sec;
                if (secEl) secEl.textContent = sec;
                if (fill) fill.style.width = (sec / 10 * 100) + '%';

                if (sec <= 0) {
                    clearInterval(window._guideCountdownInt);
                    
                    // Reset countdown display
                    if (wrap) wrap.style.display = 'none';
                    
                    // Pindah ke halaman filling
                    goTo('page-filling');
                    const vol = window._pendingVolume
                        || (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);
                    if (typeof FillingUI !== 'undefined' && FillingUI.start) {
                        FillingUI.start({ target_liters: vol, order_id: orderId });
                    }

                    // Kirim DISPENSE ke ESP32
                    fetch('/api/payment/start-dispense', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ order_id: orderId }),
                    })
                    .then(res => res.json())
                    .then(data => {
                        if (data.status === 'ok') {
                            console.log('[Filling] Dispense dimulai:', data.order_id);
                        } else {
                            showToast('⚠️ Gagal memulai dispense: ' + (data.detail || data.message));
                        }
                    })
                    .catch(err => {
                        showToast('⚠️ Koneksi terputus saat memulai dispense');
                        console.error('[Filling] start-dispense error:', err);
                    });
                }
                sec--;
            };
            
            // Jalankan countdown
            tick();
            if (window._guideCountdownInt) {
                clearInterval(window._guideCountdownInt);
            }
            window._guideCountdownInt = setInterval(tick, 1000);

        } else {
            if (btn) { 
                btn.disabled = false; 
                btn.innerHTML = 'Sudah Siap — Mulai Isi Air'; 
            }
            showToast('❌ ' + (data.detail || data.message || 'Gagal mengirim perintah'));
        }
    })
    .catch(err => {
        if (btn) { 
            btn.disabled = false; 
            btn.innerHTML = 'Sudah Siap — Mulai Isi Air'; 
        }
        showToast('❌ Koneksi ke server gagal. Coba lagi.');
        console.error('[Guide] confirm-dispense error:', err);
    });
};

window.cancelGuide = function() {
    clearInterval(window._guideCountdownInt);
    resetTransactionState();
    showToast('Transaksi dibatalkan. Kembali ke menu.');
    setTimeout(() => goToStandby(), 1000);
};

// app.js - tambahkan fungsi resetTransaksiState()

window.resetTransactionState = function() {
    // Reset semua state transaksi
    window._pendingOrderId = null;
    window._pendingVolume = null;
    window._pendingSessionId = null;
    window._guideCheckedCount = 0;
    
    // Reset timer
    clearInterval(window._qrTimerInt);
    clearInterval(window._guideCountdownInt);
    clearInterval(window._fillSimInterval);
    
    // Reset UI elements
    const guideCountdownWrap = document.getElementById('guideCountdownWrap');
    if (guideCountdownWrap) guideCountdownWrap.style.display = 'none';
    
    const guideCountFill = document.getElementById('guideCountFill');
    if (guideCountFill) guideCountFill.style.width = '100%';
    
    const guideCountDisp = document.getElementById('guideCountDisp');
    if (guideCountDisp) guideCountDisp.textContent = '10';
    
    // Reset checklist guide
    for (let i = 1; i <= 3; i++) {
        const item = document.getElementById('gcl' + i);
        const chk = document.getElementById('gck' + i);
        if (item) item.classList.remove('done');
        if (chk) chk.textContent = '○';
    }
    
    // Reset tombol guide
    const btnGuide = document.getElementById('btnGuideStart');
    if (btnGuide) {
        btnGuide.disabled = false;
        btnGuide.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
                <path d="M8 5v14l11-7z"/>
            </svg>
            Sudah Siap — Mulai Isi Air
        `;
    }
    
    if (typeof AppState !== 'undefined') {
        AppState.reset();
    }
    
    console.log('[App] Transaction state reset');
};



// ── Filling Simulation Fallback ──
function simulateFillingFallback() {
    const target = typeof AppState !== 'undefined' ? AppState.selectedVolume : 5;
    let current = 0;
    const step = target / 200;

    if (typeof FillingUI !== 'undefined' && FillingUI.start) {
        FillingUI.start({ target_liters: target });
    }

    const el = {
        bigFill: document.getElementById('bigFill'),
        tankLabel: document.getElementById('tankLabel'),
        fillBar: document.getElementById('fillBar'),
        fillPct: document.getElementById('fillPct'),
        fillCurrent: document.getElementById('fillCurrent'),
        fillTarget: document.getElementById('fillTarget'),
        fillTitle: document.getElementById('fillTitle'),
        fillSub: document.getElementById('fillSub'),
        fillStatusBadge: document.getElementById('fillStatusBadge'),
        bigTank: document.getElementById('bigTank'),
        successIcon: document.getElementById('successIcon'),
        fillDoneBtn: document.getElementById('fillDoneBtn'),
    };

    if (el.fillTarget) el.fillTarget.textContent = target.toFixed(1);

    clearInterval(window._fillSimInterval);
    window._fillSimInterval = setInterval(() => {
        current = Math.min(current + step, target);
        const pct = (current / target) * 100;

        if (el.bigFill) el.bigFill.style.height = pct + '%';
        if (el.tankLabel) el.tankLabel.textContent = Math.round(pct) + '%';
        if (el.fillBar) el.fillBar.style.width = pct + '%';
        if (el.fillPct) el.fillPct.textContent = Math.round(pct) + '%';
        if (el.fillCurrent) el.fillCurrent.textContent = current.toFixed(2);

        if (current >= target) {
            clearInterval(window._fillSimInterval);
            // Complete
            if (el.fillTitle) el.fillTitle.textContent = 'Pengisian Selesai!';
            if (el.fillSub) {
                const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;
                el.fillSub.textContent = formatRp(target * price) + ' · ' + target.toFixed(1) + ' Liter Air RO';
            }
            if (el.fillStatusBadge) {
                el.fillStatusBadge.textContent = 'Selesai ✓';
                el.fillStatusBadge.style.background = '#e6f9f0';
                el.fillStatusBadge.style.color = '#34C38F';
            }
            if (el.bigTank) el.bigTank.style.display = 'none';
            if (el.successIcon) el.successIcon.style.display = 'flex';
            if (el.fillDoneBtn) el.fillDoneBtn.style.display = 'block';

            if (typeof API !== 'undefined') {
                API._emit('dispense_complete', {
                    actual_liters: target,
                    duration_sec: 120,
                });
            }
        }
    }, 100);
}

// ── Ticket Functions ──
window.goToTicketSync = function() {
    if (typeof TicketUI !== 'undefined' && TicketUI.open) {
        TicketUI.open();
    } else {
        // Fallback jika TicketUI belum siap
        goTo('page-ticket-code');
        setTimeout(function() {
            var input = document.getElementById('ticketCodeInput');
            if (input) input.focus();
        }, 300);
    }
};

// ── Simulasi Scan Tiket HP — VERSI REAL (hit backend sungguhan) ──
// Dipanggil tombol "📱 Simulasi Deteksi Scan Tiket HP" di page-ticket.
// Beda dari simulateTicketScanSuccess() di bawah (yang cuma fake UI lokal):
// fungsi ini benar-benar POST ke backend (/api/ticket/dev-simulate-redeem,
// aktif hanya saat APP_ENV=development), yang di dalamnya menjalankan alur
// redeem_ticket() ASLI — verifikasi session, redeem tiket, cek galon,
// broadcast WS 'ticket_verified', kirim MQTT DISPENSE ke ESP32.
// Setelah fetch ini sukses, TIDAK ada handling tambahan di sini — modal
// verifikasi + pindah ke page-guide dipicu oleh listener WS yang sudah ada
// (API.on('ticket_verified', ...)), persis seperti kalau HP asli yang scan.
window.simulateTicketScanFromPhone = function() {
    const btn = document.querySelector('#page-ticket .btn-pay');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Mensimulasikan scan HP...';
    }

    fetch('/api/ticket/dev-simulate-redeem', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            machine_id:   typeof API !== 'undefined' ? API.machineId : undefined,
            volume_liter: typeof AppState !== 'undefined' ? AppState.selectedVolume : undefined,
        }),
    })
    .then(res => res.json().then(data => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '📱 Simulasi Deteksi Scan Tiket HP';
        }
        if (!ok) {
            const detail = (data && data.detail) || {};
            showToast('❌ ' + (detail.message || data.message || 'Simulasi scan tiket gagal'));
            console.warn('[DevSim] Ticket redeem gagal:', data);
            return;
        }
        console.log('[DevSim] Ticket redeem terkirim, menunggu event WS ticket_verified:', data);
    })
    .catch(err => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '📱 Simulasi Deteksi Scan Tiket HP';
        }
        showToast('❌ Koneksi ke server gagal saat simulasi scan tiket');
        console.error('[DevSim] ticket redeem error:', err);
    });
};


function goToGuidePage() {
    goTo('page-guide');
    setTimeout(() => {
        tickGuideCheck(0);
        setTimeout(() => tickGuideCheck(1), 800);
        setTimeout(() => tickGuideCheck(2), 1600);
    }, 500);
}

// ── Admin Functions ──
window.openAdmin = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI.open) {
        AdminUI.open();
    } else {
        // Fallback: langsung buka modal PIN
        const modal = document.getElementById('pinModal');
        if (modal) {
            modal.classList.add('show');
            window._pinStr = '';
            updatePinDisplay();
        } else {
            alert('Panel admin tidak tersedia');
        }
    }
};

// PIN Modal handlers — delegasikan ke AdminUI jika ada
window.closePinModal = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI.closePinModal) {
        AdminUI.closePinModal();
    } else {
        const modal = document.getElementById('pinModal');
        if (modal) modal.classList.remove('show');
        window._pinStr = '';
        updatePinDisplay();
    }
};

window.pinInput = function(d) {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinInput) {
        AdminUI._pinInput(d);
    } else {
        if (window._pinStr.length >= 4) return;
        window._pinStr += d;
        updatePinDisplay();
    }
};

window.pinDel = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinDel) {
        AdminUI._pinDel();
    } else {
        window._pinStr = window._pinStr.slice(0, -1);
        updatePinDisplay();
    }
};

window.pinEnter = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinEnter) {
        AdminUI._pinEnter();
    } else {
        // Fallback lama (tidak aman) — tetap panggil backend via AdminUI jika ada
        if (typeof AdminUI !== 'undefined' && AdminUI._verifyPinWithBackend) {
            AdminUI._verifyPinWithBackend(window._pinStr || '');
        } else {
            const pin = window._pinStr || '';
            const adminPin = typeof AppState !== 'undefined' ? AppState.adminPin : '1234';
            if (pin === adminPin) {
                closePinModal();
                goTo('page-admin');
            } else {
                window._pinStr = '';
                updatePinDisplay();
                showToast('PIN salah. Coba lagi.');
            }
        }
    }
};

function updatePinDisplay() {
    for (let i = 0; i < 4; i++) {
        const dot = document.getElementById('pd' + i);
        if (dot) {
            dot.classList.toggle('filled', i < (window._pinStr || '').length);
        }
    }
}

// ── Admin PIN Modal ──
window.openAdmin = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI.open) {
        AdminUI.open();
    } else {
        // Fallback: langsung buka modal PIN
        const modal = document.getElementById('pinModal');
        if (modal) {
            modal.classList.add('show');
            window._pinStr = '';
            updatePinDisplay();
        } else {
            alert('Panel admin tidak tersedia');
        }
    }
};

// PIN Modal handlers — delegasikan ke AdminUI jika ada
window.closePinModal = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI.closePinModal) {
        AdminUI.closePinModal();
    } else {
        const modal = document.getElementById('pinModal');
        if (modal) modal.classList.remove('show');
        window._pinStr = '';
        updatePinDisplay();
    }
};

window.pinInput = function(d) {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinInput) {
        AdminUI._pinInput(d);
    } else {
        if (window._pinStr.length >= 4) return;
        window._pinStr += d;
        updatePinDisplay();
    }
};

window.pinDel = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinDel) {
        AdminUI._pinDel();
    } else {
        window._pinStr = window._pinStr.slice(0, -1);
        updatePinDisplay();
    }
};

window.pinEnter = function() {
    if (typeof AdminUI !== 'undefined' && AdminUI._pinEnter) {
        AdminUI._pinEnter();
    } else {
        // Fallback lama (tidak aman) — tetap panggil backend via AdminUI jika ada
        if (typeof AdminUI !== 'undefined' && AdminUI._verifyPinWithBackend) {
            AdminUI._verifyPinWithBackend(window._pinStr || '');
        } else {
            const pin = window._pinStr || '';
            const adminPin = typeof AppState !== 'undefined' ? AppState.adminPin : '1234';
            if (pin === adminPin) {
                closePinModal();
                goTo('page-admin');
            } else {
                window._pinStr = '';
                updatePinDisplay();
                showToast('PIN salah. Coba lagi.');
            }
        }
    }
};

function updatePinDisplay() {
    for (let i = 0; i < 4; i++) {
        const dot = document.getElementById('pd' + i);
        if (dot) {
            dot.classList.toggle('filled', i < (window._pinStr || '').length);
        }
    }
}

// ── Standby Timer ──
let _standbyTimer = null;
let _standbyTimeoutSeconds = 30; // default, akan diupdate dari AppState

// Halaman yang TIDAK BOLEH kena timeout standby generik (30 detik) karena
// sedang dalam proses pembayaran/pengisian yang aktif:
//
//   page-qr      → sudah punya timer sendiri 5 menit (lihat startQRTimer()),
//                  yang otomatis redirect ke page-payment saat QR benar2
//                  kedaluwarsa. Kalau timer standby generik ikut jalan di
//                  sini, user bisa dilempar ke layar utama padahal QR-nya
//                  masih valid dan baru saja mau discan — order jadi
//                  "hilang" dari sudut pandang user walau transaksi masih
//                  PENDING di database.
//
//   page-filling → proses dispensing dikendalikan oleh event dispense_complete
//                  dari ESP32 (lihat filling.js), BUKAN oleh timer arbitrer.
//                  Kalau timer standby ikut menang duluan di sini, UI kembali
//                  ke standby padahal air masih mengalir secara fisik — bisa
//                  bikin pelanggan bingung (dikira gagal/dibatalkan), dan
//                  yang lebih berbahaya: AppState di-reset seolah kios bebas,
//                  berisiko pelanggan berikutnya "merebut" kios saat galon
//                  pelanggan sebelumnya belum selesai terisi. Halaman ini
//                  hanya boleh keluar lewat tombol "Selesai" (goToStandby())
//                  setelah dispense_complete diterima.
const _NO_STANDBY_TIMEOUT_PAGES = new Set(['page-qr', 'page-ticket', 'page-filling']);

// page-guide: user sudah BAYAR, tinggal jalan ke mesin & tekan tombol
// konfirmasi. Beri waktu jauh lebih longgar dari 30 detik default supaya
// tidak dilempar ke standby padahal pembayaran sudah berhasil masuk.
const _PAGE_TIMEOUT_OVERRIDE_SECONDS = {
    'page-guide': 180, // 3 menit
};

function resetStandbyTimer() {
    clearTimeout(_standbyTimer);
    const currentPage = document.querySelector('.page.active')?.id;

    // Sudah di standby → tidak perlu timer sama sekali
    if (currentPage === 'page-standby') return;

    // Halaman dengan proses aktif (QR/filling) → jangan pasang timer generik
    if (_NO_STANDBY_TIMEOUT_PAGES.has(currentPage)) return;

    const timeout = _PAGE_TIMEOUT_OVERRIDE_SECONDS[currentPage]
        || (typeof AppState !== 'undefined' ? AppState.standbyTimeout : 30);

    _standbyTimer = setTimeout(() => {
        // Kembali ke standby
        if (typeof goToStandby === 'function') {
            goToStandby();
            showToast('⏰ Kembali ke layar utama karena tidak ada aktivitas');
        }
    }, timeout * 1000);
}

function startStandbyTimer() {
    // Reset timer saat ada aktivitas
    resetStandbyTimer();
}

// Event listener untuk reset timer pada setiap interaksi user
function bindStandbyEvents() {
    const events = ['click', 'touchstart', 'keydown', 'mousemove'];
    events.forEach(evt => {
        document.addEventListener(evt, function() {
            // Jangan reset di halaman standby atau halaman dengan proses aktif
            // (resetStandbyTimer() sendiri juga sudah menjaga ini, dicek dobel
            // di sini supaya tidak ada overhead clearTimeout/setTimeout sia-sia)
            const page = document.querySelector('.page.active')?.id;
            if (page === 'page-standby' || _NO_STANDBY_TIMEOUT_PAGES.has(page)) return;
            resetStandbyTimer();
        }, { passive: true });
    });
}

function clearStandbyTimer() {
    clearTimeout(_standbyTimer);
}

// ── Toast ──
window.showToast = function(msg, dur = 2600) {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._timeout);
    el._timeout = setTimeout(() => el.classList.remove('show'), dur);
};

// ── Full Screen Toggle ──
window.toggleFullPreview = function() {
    const scr = document.getElementById('screen');
    const btn = document.getElementById('btnExpand');
    if (scr) {
        if (scr.style.width === '100vw') {
            scr.style.cssText = '';
            if (btn) btn.textContent = '🖥 Full Screen Preview';
        } else {
            scr.style.cssText = 'width:100vw;height:100vh;border-radius:0;';
            if (btn) btn.textContent = '🗗 Reset Preview';
        }
    }
};

// ──────────────────────────────────────────────
// SECRET TAP ZONES — akses tersembunyi di halaman standby
// Kiri bawah (5x tap) → PIN modal → Admin
// Kanan bawah (5x tap) → langsung Full Screen Preview
// ──────────────────────────────────────────────
(function initSecretTapZones() {

    // State untuk masing-masing zona
    const state = {
        admin:   { count: 0, timer: null },
        preview: { count: 0, timer: null },
    };

    const REQUIRED_TAPS  = 5;    // jumlah tap yang dibutuhkan
    const RESET_DELAY_MS = 3000; // waktu reset jika tap berhenti (ms)

    function handleTap(zone) {
        // Hanya aktif saat di halaman standby
        const currentPage = typeof AppState !== 'undefined'
            ? AppState.currentPage
            : document.querySelector('.page.active')?.id;
        if (currentPage !== 'page-standby') return;

        const s = state[zone];

        // Reset timer
        clearTimeout(s.timer);
        s.count++;

        if (s.count >= REQUIRED_TAPS) {
            // Reset counter
            s.count = 0;

            if (zone === 'admin') {
                // Buka PIN modal
                const modal = document.getElementById('pinModal');
                if (modal) {
                    modal.classList.add('show');
                    window._pinStr = '';
                    updatePinDisplay();
                }
            } else if (zone === 'preview') {
                // Langsung toggle full screen, tanpa PIN
                toggleFullPreview();
            }
        } else {
            // Reset count jika tidak ada tap lagi dalam RESET_DELAY_MS
            s.timer = setTimeout(() => {
                s.count = 0;
            }, RESET_DELAY_MS);
        }
    }

    // Pasang event listener setelah DOM siap
    function bindZones() {
        const zoneAdmin   = document.getElementById('tapZoneAdmin');
        const zonePreview = document.getElementById('tapZonePreview');

        if (zoneAdmin) {
            // Pakai touchstart untuk touchscreen, click untuk mouse/dev
            zoneAdmin.addEventListener('touchstart', () => handleTap('admin'), { passive: true });
            zoneAdmin.addEventListener('click',      () => handleTap('admin'));
        }

        if (zonePreview) {
            zonePreview.addEventListener('touchstart', () => handleTap('preview'), { passive: true });
            zonePreview.addEventListener('click',      () => handleTap('preview'));
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindZones);
    } else {
        bindZones();
    }

})();

// ── Video Upload ──
window.handleVideoUpload = function(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Delegasikan sepenuhnya ke SignageUI yang sudah punya logic lengkap
    if (typeof SignageUI !== 'undefined' && SignageUI.handleVideoUpload) {
        SignageUI.handleVideoUpload(file);
    }
};

// ──────────────────────────────────────────────
// INITIALIZATION
// ──────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    console.log('[Toyamas] Bridge initializing...');

    // PERBAIKAN (multi-mesin): machine_id dulu hardcode 'TYM-001', jadi
    // satu build kiosk UI ini cuma bisa dipakai untuk satu mesin fisik.
    // Sekarang diambil dari query string URL kios, mis.:
    //   https://server-kamu/frontend/?machine=TYM-002
    // supaya file HTML/JS yang SAMA bisa dipakai di semua unit — tinggal
    // beda link/bookmark browser kiosk di tiap lokasi. Fallback ke
    // 'TYM-001' kalau parameter tidak ada (mis. saat development lokal).
    const MACHINE_ID = new URLSearchParams(window.location.search).get('machine') || 'TYM-001';
    console.log('[Toyamas] machine_id aktif:', MACHINE_ID);

    // 1. Initialize state
    if (typeof AppState !== 'undefined') {
        AppState.init(MACHINE_ID);
    }

    // 2. Initialize API
    if (typeof API !== 'undefined') {
        API.init(MACHINE_ID);
    }

    // 3. Initialize UI modules dengan pengecekan yang lebih baik
    console.log('[Toyamas] Initializing UI modules...');
    
    // ClockUI - inisialisasi manual
    if (typeof ClockUI !== 'undefined' && ClockUI.init) {
        try {
            ClockUI.init();
            console.log('[Toyamas] ClockUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] ClockUI init failed:', e);
            // Fallback: buat clock manual
            setupClockFallback();
        }
    } else {
        console.warn('[Toyamas] ClockUI not found, using fallback');
        setupClockFallback();
    }

    // GalonUI
    if (typeof GalonUI !== 'undefined' && GalonUI.init) {
        try {
            GalonUI.init();
            console.log('[Toyamas] GalonUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] GalonUI init failed:', e);
        }
    }

    // SignageUI
    if (typeof SignageUI !== 'undefined' && SignageUI.init) {
        try {
            SignageUI.init();
            console.log('[Toyamas] SignageUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] SignageUI init failed:', e);
        }
    }

    // FillingUI
    if (typeof FillingUI !== 'undefined' && FillingUI.init) {
        try {
            FillingUI.init();
            console.log('[Toyamas] FillingUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] FillingUI init failed:', e);
        }
    }

    // TicketUI
    if (typeof TicketUI !== 'undefined' && TicketUI.init) {
        try {
            TicketUI.init();
            console.log('[Toyamas] TicketUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] TicketUI init failed:', e);
        }
    }

    // AdminUI - inisialisasi manual
    if (typeof AdminUI !== 'undefined' && AdminUI.init) {
        try {
            AdminUI.init();
            console.log('[Toyamas] AdminUI initialized ✓');
        } catch (e) {
            console.warn('[Toyamas] AdminUI init failed:', e);
        }
    } else {
        console.warn('[Toyamas] AdminUI not found');
    }

    // Reset state setiap kali halaman standby diaktifkan
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const standbyPage = document.getElementById('page-standby');
                if (standbyPage && standbyPage.classList.contains('active')) {
                    resetTransactionState();
                }
            }
        });
    });
    
        const standbyPage = document.getElementById('page-standby');
        if (standbyPage) {
            observer.observe(standbyPage, { attributes: true });
        }
    bindStandbyEvents();
    // Set timer awal
    resetStandbyTimer();

    // 4. Connect WebSocket
    if (typeof API !== 'undefined' && API.connectWebSocket) {
        API.connectWebSocket();
    }

    API.on('config_update', function(data) {
    console.log('[App] Config update received:', data);
    if (typeof SignageUI !== 'undefined' && SignageUI.handleConfigUpdate) {
        SignageUI.handleConfigUpdate(data);
    }
    if (typeof AppState !== 'undefined') {
        if (data.price_per_liter) AppState.pricePerLiter = parseInt(data.price_per_liter);
        if (data.standby_timeout_sec) AppState.standbyTimeout = parseInt(data.standby_timeout_sec);
        if (data.slide_duration_ms) AppState.slideDuration = parseInt(data.slide_duration_ms);
        if (data.signage_enabled !== undefined) AppState.signageEnabled = parseInt(data.signage_enabled);
        if (data.ticker_text) AppState.tickerText = data.ticker_text;
    }
    if (data.mode !== undefined) {
        AppState.mode = data.mode;
        // Update UI admin read-only jika di halaman admin
        const modeEl = document.getElementById('adminCurrentMode');
        if (modeEl) modeEl.textContent = data.mode;
    }
    // Update harga di UI
    if (typeof updatePriceDisplay === 'function') updatePriceDisplay();
    
    if (data.standby_timeout_sec) {
        AppState.standbyTimeout = parseInt(data.standby_timeout_sec);
        resetStandbyTimer(); // reset dengan timeout baru
    }
    });

    API.on('signage_update', function(data) {
        console.log('[App] Signage update received:', data);
        if (typeof SignageUI !== 'undefined' && SignageUI.handleSignageUpdate) {
            SignageUI.handleSignageUpdate(data);
        }
    });

    // 5. Load machine status
    if (typeof API !== 'undefined' && API.getMachineStatus) {
        API.getMachineStatus()
            .then(data => {
                console.log('[Toyamas] Machine status:', data);
                if (data.galon && typeof GalonUI !== 'undefined' && GalonUI.update) {
                    GalonUI.update(
                        data.galon.g1_level_pct || 75,
                        data.galon.g2_level_pct || 45
                    );
                }
                if (data.price_per_liter && typeof AppState !== 'undefined') {
                    AppState.setPrice(data.price_per_liter);
                    updatePriceDisplay();
                }
            })
            .catch(err => {
                console.warn('[Toyamas] Status load failed:', err);
                // Use default values
            });
    }

    // 6. WebSocket event handlers
    if (typeof API !== 'undefined') {
        API.on('machine_status', function(data) {
            if (data.g1_level_pct !== undefined && typeof GalonUI !== 'undefined') {
                GalonUI.update(data.g1_level_pct, data.g2_level_pct);
                if (typeof AppState !== 'undefined') {
                    AppState.setGalon(1, data.g1_level_pct, data.g1_status);
                    AppState.setGalon(2, data.g2_level_pct, data.g2_status);
                }
            }
        });

        API.on('payment_confirmed', function(data) {
            // Reset state transaksi sebelumnya
            resetTransactionState();
            // Pembayaran dikonfirmasi — tampilkan halaman guide dulu
            // JANGAN kirim DISPENSE ke ESP32 sebelum user klik tombol "Sudah Siap"
            clearInterval(window._qrTimerInt);
            showToast('✓ Pembayaran berhasil! Ikuti panduan pengisian.');

            if (typeof AppState !== 'undefined') {
                AppState.setOrder(data.order_id, data.session_id);
                // Simpan volume untuk ditampilkan di guide
                AppState.targetLiters = data.volume_liter || AppState.selectedVolume;
            }

            // Store order_id untuk dikirim saat user klik tombol
            window._pendingOrderId  = data.order_id;
            window._pendingVolume   = data.volume_liter;
            window._pendingSessionId = data.session_id;

            setTimeout(() => {
                goTo('page-guide');
                // Reset checklist
                for (let i = 1; i <= 3; i++) {
                    const item = document.getElementById('gcl' + i);
                    const chk = document.getElementById('gck' + i);
                    if (item) item.classList.remove('done');
                    if (chk) chk.textContent = '○';
                }
                _guideCheckedCount = 0;
                // Centang checklist guide secara berurutan
                setTimeout(() => {
                    tickGuideCheck(0);
                    setTimeout(() => tickGuideCheck(1), 800);
                    setTimeout(() => tickGuideCheck(2), 1600);
                }, 500);
            }, 1000);
        });

        API.on('payment_failed', function(data) {
            showToast('❌ Pembayaran gagal: ' + (data.reason || 'Coba lagi'));
        });

        API.on('ticket_verified', function(data) {
            if (typeof TicketUI !== 'undefined' && TicketUI.showVerificationSuccess) {
                TicketUI.showVerificationSuccess(data);
            } 
        });

        API.on('dispense_started', function(data) {
            if (typeof FillingUI !== 'undefined' && FillingUI.start) {
                FillingUI.start(data);
            }
        });

        // TAMPILKAN BARIS INI: Menerima progres dari ESP32
        API.on('realtime_flow', function(data) {
            if (typeof FillingUI !== 'undefined' && FillingUI.onRealtimeFlow) {
                FillingUI.onRealtimeFlow(data);
            }
        });

        API.on('dispense_complete', function(data) {
            if (typeof FillingUI !== 'undefined' && FillingUI.complete) {
                FillingUI.complete(data);
            }
            showToast('✓ Pengisian selesai! Ambil galon Anda.');
        });

        API.on('alarm', function(data) {
            if (data.severity === 'ERROR') {
                showToast('⚠️ ' + (data.message || 'Alarm sistem!'));
            }
        });
    }

    // 7. Update price display
    updatePriceDisplay();

    // 8. Start auto-refill simulation
    setInterval(() => {
        if (typeof AppState !== 'undefined') {
            const page = document.querySelector('.page.active');
            if (page && page.id === 'page-standby') {
                if (AppState.galon.g1.level < 95) {
                    AppState.galon.g1.level = Math.min(95, AppState.galon.g1.level + 0.15);
                }
                if (AppState.galon.g2.level < 88) {
                    AppState.galon.g2.level = Math.min(88, AppState.galon.g2.level + 0.1);
                }
                if (typeof GalonUI !== 'undefined' && GalonUI.update) {
                    GalonUI.update(AppState.galon.g1.level, AppState.galon.g2.level);
                }
            }
        }
    }, 3000);

    console.log('[Toyamas] Bridge initialized ✓');
});


// ── Fallback Clock ──
function setupClockFallback() {
    console.log('[Toyamas] Setting up clock fallback');
    const sClock = document.getElementById('sClock');
    const sDate = document.getElementById('sDate');
    
    function updateClock() {
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
            if (sClock) sClock.textContent = t;
            if (sDate) sDate.textContent = dt.toUpperCase();
        } catch (e) {
            // Ignore
        }
    }
    
    updateClock();
    setInterval(updateClock, 1000);
    console.log('[Toyamas] Clock fallback running');
}

// ── Fallback Admin ──
// Pastikan fungsi openAdmin tetap tersedia
if (typeof window.openAdmin === 'undefined') {
    window.openAdmin = function() {
        console.log('[Toyamas] openAdmin called (fallback)');
        if (typeof AdminUI !== 'undefined' && AdminUI.open) {
            AdminUI.open();
        } else {
            // Fallback: langsung buka modal PIN
            const modal = document.getElementById('pinModal');
            if (modal) {
                modal.classList.add('show');
                window._pinStr = '';
                updatePinDisplay();
            } else {
                alert('Panel admin tidak tersedia');
            }
        }
    };
}

// ── Expose untuk debugging ──
window._debug = {
    AppState: typeof AppState !== 'undefined' ? AppState : null,
    API: typeof API !== 'undefined' ? API : null,
    modules: {
        ClockUI: typeof ClockUI !== 'undefined' ? ClockUI : null,
        GalonUI: typeof GalonUI !== 'undefined' ? GalonUI : null,
        SignageUI: typeof SignageUI !== 'undefined' ? SignageUI : null,
        FillingUI: typeof FillingUI !== 'undefined' ? FillingUI : null,
        TicketUI: typeof TicketUI !== 'undefined' ? TicketUI : null,
        AdminUI: typeof AdminUI !== 'undefined' ? AdminUI : null,
    }
};