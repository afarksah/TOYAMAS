/**
 * filling.js — Filling Page Module
 * TOYAMAS Vending Dispenser UI
 *
 * Tanggung jawab:
 *  - Terima data start (target_liters, order_id) dari app.js
 *  - Terima event realtime_flow dari api.js → update animasi
 *  - Terima event dispense_complete → tampilkan selesai
 *  - Fallback simulasi lokal jika WebSocket tidak terhubung
 *
 * PERBAIKAN dari versi sebelumnya:
 *   - start() sekarang MENERIMA parameter { target_liters, order_id }
 *     (sebelumnya kosong, sehingga data dari app.js dibuang)
 *   - API.isWsReady() → API.isWebSocketConnected()
 *     (isWsReady tidak ada di api.js, menyebabkan TypeError dan start() crash)
 *   - API.dev.simulateRealtimeFlow() dihapus — namespace API.dev tidak ada
 *   - Semua referensi State.xxx / Utils.xxx / Galon.xxx diganti ke
 *     AppState.xxx / window.formatRp / GalonUI.update yang benar-benar ada
 */

const Filling = (() => {

  let _simInterval   = null;   // Interval simulasi lokal (fallback)
  let _isRealtime     = false; // true = terima data dari WS, false = simulasi
  let _lastFlowTime   = 0;     // Timestamp terakhir terima realtime_flow
  let _watchdogTimer  = null;  // Timer untuk deteksi WS flow berhenti
  let _targetLiters   = 5;     // Target volume sesi filling saat ini
  let _currentOrderId = null;  // order_id sesi filling saat ini

  /* ─────────────────────────────────────────
     MULAI FILLING
     Dipanggil dari app.js setelah countdown guide selesai, dengan:
       FillingUI.start({ target_liters, order_id })
  ───────────────────────────────────────── */

  function start(opts) {
    opts = opts || {};

    // Simpan target & order_id dari pemanggil — sebelumnya dibuang
    // karena start() tidak punya parameter sama sekali.
    _targetLiters = opts.target_liters
      || (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);
    _currentOrderId = opts.order_id || null;

    _lastFlowTime = Date.now();

    // Reset tampilan ke 0% sebelum mulai
    _renderProgress({ current: 0, target: _targetLiters, pct: 0, rate: 0 });

    // FIX: isWsReady() tidak ada di api.js, fungsi yang benar adalah
    // isWebSocketConnected(). Pakai optional chaining + fallback aman
    // supaya tidak throw kalau API belum siap.
    _isRealtime = (typeof API !== 'undefined' && typeof API.isWebSocketConnected === 'function')
      ? API.isWebSocketConnected()
      : false;

    if (_isRealtime) {
      // Mode realtime: animasi digerakkan oleh event realtime_flow dari ESP32
      console.log('[Filling] Realtime mode via WebSocket. target=' + _targetLiters + 'L order=' + _currentOrderId);
      _startWatchdog();
    } else {
      // Fallback: simulasi lokal (WS belum connect / backend offline)
      console.warn('[Filling] WebSocket tidak siap, pakai simulasi lokal sementara');
      _startSimulation();
      // Tetap nyalakan watchdog — begitu WS connect & flow data masuk,
      // onRealtimeFlow() akan otomatis menghentikan simulasi (lihat di bawah)
      _startWatchdog();
    }
  }

  /* ─────────────────────────────────────────
     HANDLER: realtime_flow (dari api.js/WebSocket)
     Data datang tiap ~100ms saat ESP32 DISPENSING
  ───────────────────────────────────────── */

  function onRealtimeFlow(data) {
    _lastFlowTime = Date.now();
    _isRealtime   = true;
    clearInterval(_simInterval);  // Hentikan simulasi lokal jika sempat jalan
    _simInterval = null;

    const fallbackTarget = _targetLiters
      || (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);

    // ESP32 kadang kirim target_liters=0 di payload pertama sebelum
    // targetLiters ter-set sempurna — jangan biarkan itu menimpa target asli.
    const target = data.target_liters || fallbackTarget;
    if (data.target_liters) _targetLiters = data.target_liters;

    _renderProgress({
      current: data.current_liters || 0,
      target:  target,
      pct:     data.pct_complete   || 0,
      rate:    data.flow_rate_lpm  || 0,
    });
  }

  /* ─────────────────────────────────────────
     HANDLER: dispense_complete (dari api.js/WebSocket)
     Dipanggil saat ESP32 menyelesaikan pengisian
  ───────────────────────────────────────── */

  function onComplete(data) {
    _stopAll();

    const actualLiters = (data && data.actual_liters) || _targetLiters;

    // Pastikan UI 100% penuh dulu, baru tampilkan halaman selesai
    _renderProgress({ current: actualLiters, target: actualLiters, pct: 100 });
    setTimeout(_showDone, 600);

    // Catatan: level galon yang akurat akan diperbarui otomatis lewat
    // event machine_status (lihat handler API.on('machine_status', ...) di app.js)
    // jadi tidak perlu estimasi manual di sini.
  }

  /* ─────────────────────────────────────────
     RENDER PROGRESS UI
  ───────────────────────────────────────── */

  function _renderProgress({ current, target, pct, rate }) {
    const pctClamped = Math.min(100, Math.max(0, pct || 0));
    const heights     = pctClamped + '%';

    const safeTarget = target
      || _targetLiters
      || (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);

    _set('bigFill',     el => el.style.height = heights);
    _set('tankLabel',   el => el.textContent  = Math.round(pctClamped) + '%');
    _set('fillBar',     el => el.style.width  = heights);
    _set('fillPct',     el => el.textContent  = Math.round(pctClamped) + '%');
    _set('fillCurrent', el => el.textContent  = (current || 0).toFixed(2));
    _set('fillTarget',  el => el.textContent  = safeTarget.toFixed(1));

    if (rate) {
      _set('fillRateBadge', el => el.textContent = rate.toFixed(2) + ' L/min');
    }
  }

  function _showDone() {
    const target = _targetLiters
      || (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);
    const price = typeof AppState !== 'undefined' ? AppState.pricePerLiter : 500;

    const hargaStr = (typeof window.formatRp === 'function')
      ? window.formatRp(target * price)
      : 'Rp ' + Math.round(target * price).toLocaleString('id-ID');

    _set('fillTitle', el => el.textContent = 'Pengisian Selesai!');
    _set('fillSub',   el => el.textContent = hargaStr + ' · ' + target.toFixed(1) + ' Liter Air RO');
    _set('fillStatusBadge', el => {
      el.textContent      = 'Selesai ✓';
      el.style.background = '#e6f9f0';
      el.style.color      = '#34C38F';
    });
    _set('bigTank',     el => el.style.display = 'none');
    _set('successIcon', el => el.style.display = 'flex');
    _set('fillDoneBtn', el => el.style.display = 'block');
  }

  /* ─────────────────────────────────────────
     SIMULASI LOKAL (fallback — dipakai jika WS belum/tidak connect)
  ───────────────────────────────────────── */

  function _startSimulation() {
    let current   = 0;
    const total   = _targetLiters || 5;
    const step    = total / 60;   // selesai dalam ~9 detik (150ms x 60)

    clearInterval(_simInterval);
    _simInterval = setInterval(() => {
      current = Math.min(current + step, total);
      const pct = (current / total) * 100;
      _renderProgress({ current, target: total, pct, rate: 1.2 });
      if (current >= total) {
        clearInterval(_simInterval);
        _simInterval = null;
        onComplete({ actual_liters: total });
      }
    }, 150);
  }

  /* ─────────────────────────────────────────
     WATCHDOG — deteksi jika WS flow berhenti / belum pernah masuk
  ───────────────────────────────────────── */

  function _startWatchdog() {
    clearInterval(_watchdogTimer);
    _watchdogTimer = setInterval(() => {
      const elapsed = Date.now() - _lastFlowTime;
      if (elapsed > 3000) {  // 3 detik tanpa data realtime_flow
        console.warn('[Filling] Watchdog: tidak ada data realtime_flow, fallback simulasi');
        clearInterval(_watchdogTimer);
        _watchdogTimer = null;
        if (!_simInterval) _startSimulation();
      }
    }, 1000);
  }

  function _stopAll() {
    clearInterval(_simInterval);
    clearInterval(_watchdogTimer);
    _simInterval   = null;
    _watchdogTimer = null;
    _isRealtime    = false;
  }

  function _reset() {
    _stopAll();
    _targetLiters   = (typeof AppState !== 'undefined' ? AppState.selectedVolume : 5);
    _currentOrderId = null;
  }

  function _set(id, fn) {
    const el = document.getElementById(id);
    if (el) fn(el);
  }

  return {
    init: function () { console.log('[FillingUI] Initialized'); },
    start,
    onRealtimeFlow,
    complete: onComplete,   // dipanggil app.js sebagai FillingUI.complete(data)
    stop: _stopAll,
    reset: _reset,
  };

})();

// Ekspos ke global — SATU baris ekspor saja (versi sebelumnya double-assign
// yang membingungkan: window.FillingUI = FillingUI lalu ditimpa lagi)
window.FillingUI = Filling;

// Auto-init
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    if (window.FillingUI && window.FillingUI.init) window.FillingUI.init();
  });
} else {
  if (window.FillingUI && window.FillingUI.init) window.FillingUI.init();
}

console.log('[FillingUI] Module loaded');
