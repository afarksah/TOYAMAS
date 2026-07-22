/**
 * app.js — Main Dashboard Application
 * TOYAMAS IoT Dashboard
 */

(function() {

    'use strict';

    // ──────────────────────────────────────
    // Helper: parse timestamp UTC dari backend
    // ──────────────────────────────────────
    function parseServerTime(ts) {
        if (!ts) return null;
        let iso = String(ts).trim();
        if (iso.includes(' ') && !iso.includes('T')) iso = iso.replace(' ', 'T');
        if (!/Z$|[+-]\d{2}:?\d{2}$/.test(iso)) iso += 'Z';
        return new Date(iso);
    }

    // ──────────────────────────────────────
    // DOM References
    // ──────────────────────────────────────

    const DOM = {
        loginPage: document.getElementById('loginPage'),
        dashboardPage: document.getElementById('dashboardPage'),
        loginError: document.getElementById('loginError'),
        loginBtn: document.getElementById('loginBtn'), // tambahkan
        loginForm: document.getElementById('loginForm'), // tambahkan
        loginUsername: document.getElementById('loginUsername'), // tambahkan
        loginPassword: document.getElementById('loginPassword'), // tambahkan
        logoutBtn: document.getElementById('logoutBtn'),
        sidebarToggle: document.getElementById('sidebarToggle'),
        topbarTime: document.getElementById('topbarTime'),
        wsStatusText: document.getElementById('wsStatusText'),
        wsStatusDot: document.getElementById('wsStatusDot'),
        machineCount: document.getElementById('machineCount'),
        pageTitle: document.getElementById('pageTitle'),

        // Stats
        statVolume: document.getElementById('statVolume'),
        statRevenue: document.getElementById('statRevenue'),
        statTransactions: document.getElementById('statTransactions'),
        statMachines: document.getElementById('statMachines'),

        // Machines
        machinesGrid: document.getElementById('machinesGrid'),
        filterMachine: document.getElementById('filterMachine'),
        reportMachineFilter: document.getElementById('reportMachineFilter'),

        // Add Machine Modal
        addMachineBtn: document.getElementById('addMachineBtn'),
        addMachineModal: document.getElementById('addMachineModal'),
        addMachineForm: document.getElementById('addMachineFormFields'),
        addMachineError: document.getElementById('addMachineError'),
        addMachineCloseBtn: document.getElementById('addMachineCloseBtn'),
        addMachineCancelBtn: document.getElementById('addMachineCancelBtn'),
        addMachineSubmitBtn: document.getElementById('addMachineSubmitBtn'),
        addMachineSuccessState: document.getElementById('addMachineSuccessState'),
        addMachineFormFooter: document.getElementById('addMachineFormFooter'),
        addMachineSuccessFooter: document.getElementById('addMachineSuccessFooter'),
        addMachineDoneBtn: document.getElementById('addMachineDoneBtn'),
        successMachineId: document.getElementById('successMachineId'),
        successMachineSecret: document.getElementById('successMachineSecret'),
        copySecretBtn: document.getElementById('copySecretBtn'),

        // Settings
        settingsFirmware: document.getElementById('settingsFirmware'),
        settingsBackend: document.getElementById('settingsBackend'),
        settingsWebsocket: document.getElementById('settingsWebsocket'),

        // Toggles
        toggleAlarm: document.getElementById('toggleAlarm'),
        toggleLowGalon: document.getElementById('toggleLowGalon'),
        toggleOffline: document.getElementById('toggleOffline'),

        // Location page
        addLocationBtn: document.getElementById('addLocationBtn'),
        refreshMapBtn: document.getElementById('refreshMapBtn'),
        mapSearchInput: document.getElementById('mapSearchInput'),
        mapSearchBtn: document.getElementById('mapSearchBtn'),

        // Location Modal
        locationModal: document.getElementById('locationModal'),
        locationModalTitle: document.getElementById('locationModalTitle'),
        locationForm: document.getElementById('locationFormFields'),
        locationError: document.getElementById('locationError'),
        locationCloseBtn: document.getElementById('locationCloseBtn'),
        locationCancelBtn: document.getElementById('locationCancelBtn'),
        locationSubmitBtn: document.getElementById('locationSubmitBtn'),
        deleteMachineBtn: document.getElementById('deleteMachineBtn'),
        pickFromMapBtn: document.getElementById('pickFromMapBtn'),
        pickFromMapHint: document.getElementById('pickFromMapHint'),
        fldLocMachine: document.getElementById('fldLocMachine'),
        fldLocAddress: document.getElementById('fldLocAddress'),
        fldLocLat: document.getElementById('fldLocLat'),
        fldLocLng: document.getElementById('fldLocLng'),
    };

    // ──────────────────────────────────────
    // State
    // ──────────────────────────────────────

    let _currentPage = 'overview';
    let _machineData = [];
    let _salesData = {};
    let _locationsData = [];       // cache lokasi terakhir (dipakai gabungan update WS)
    let _editingMachineId = null;  // null = mode Tambah, terisi = mode Edit

    // ──────────────────────────────────────
    // Auth Check
    // ──────────────────────────────────────


    async function checkAuth() {
        const authenticated = Auth.isAuthenticated();

        if (authenticated) {
            showDashboard();
        } else {
            showLogin();
        }
    }
    function showLogin() {
        DOM.loginPage.style.display = 'flex';
        DOM.dashboardPage.style.display = 'none';
        // Hapus baris: DOM.googleLoginBtn.disabled = false;
        // Karena tombol login sekarang di-handle oleh loginBtn
        if (DOM.loginBtn) DOM.loginBtn.disabled = false;
         if (DOM.loginForm) DOM.loginForm.reset();
    }   

    function showDashboard() {
        const user = Auth.getUser();

        DOM.loginPage.style.display = 'none';
        DOM.dashboardPage.style.display = 'flex';

        if (user && DOM.userName) {
            DOM.userName.textContent = user.name || user.username || 'Admin';
        }
        // Connect WebSocket
        const email = user?.email || 'admin';
        IoTWebSocket.connect(email);

        // Load initial data
        loadDashboardData();
        loadRecentTransactions();

        // Start clock
        startClock();

        // Init sidebar state
        initSidebarState();
    }

    // ──────────────────────────────────────
    // Data Loading
    // ──────────────────────────────────────

    async function loadDashboardData() {
        try {
            const data = await Auth.fetchWithAuth('/api/iot/dashboard');
            
            const summary = data.summary || {};
            DOM.statVolume.textContent = (summary.volume_liters || 0).toFixed(1) + ' L';
            DOM.statRevenue.textContent = 'Rp ' + (summary.revenue || 0).toLocaleString('id-ID');
            DOM.statTransactions.textContent = summary.transactions || 0;

            _machineData = data.machines || [];
            renderMachines(_machineData);
            renderMonitoring(_machineData);
            populateMachineFilters();
            populateSettingsMachineSelect();

            const online = _machineData.filter(m => m.online).length;
            DOM.statMachines.textContent = `${online}/${_machineData.length}`;
            DOM.machineCount.textContent = _machineData.length;

            if (data.hourly_sales) {
                _salesData = {
                    labels: data.hourly_sales.map(d => `${d.hour}:00`),
                    datasets: {
                        volume: data.hourly_sales.map(d => d.volume_liters || 0),
                        transactions: data.hourly_sales.map(d => d.transactions || 0),
                        revenue: data.hourly_sales.map(d => d.revenue || 0),
                    }
                };
                Charts.renderSalesChart(_salesData, 'hourly');
            }

            if (data.locations) {
                _locationsData = data.locations;
                LocationMap.render(data.locations);
                if (_currentPage === 'locations') {
                    LocationMap.renderTable(data.locations);
                }
            }

        } catch (error) {
            console.error('[App] Load dashboard error:', error);
        }
    }

    async function loadRecentTransactions() {
        try {
            await TransactionsUI.loadRecent();
        } catch (error) {
            console.error('[App] Load recent transactions error:', error);
        }
    }

    // ──────────────────────────────────────
    // Render Machines
    // ──────────────────────────────────────

    function renderMachines(machines) {
        if (!DOM.machinesGrid) return;

        if (!machines || machines.length === 0) {
            DOM.machinesGrid.innerHTML = `
                <div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-light);">
                    <i class="fas fa-microchip" style="font-size:2rem;display:block;margin-bottom:8px;"></i>
                    Belum ada mesin terdaftar
                </div>
            `;
            return;
        }

        DOM.machinesGrid.innerHTML = machines.map(m => {
            const isOnline = m.online === 1 || m.online === true;
            const g1 = m.g1_level_pct || 0;
            const g2 = m.g2_level_pct || 0;
            const g1Status = g1 < 5 ? 'danger' : g1 < 20 ? 'warning' : 'ok';
            const g2Status = g2 < 5 ? 'danger' : g2 < 20 ? 'warning' : 'ok';

            return `
                <div class="machine-card ${isOnline ? '' : 'offline'}">
                    <div class="machine-header">
                        <span class="machine-name">${m.machine_id}</span>
                        <span class="machine-status ${isOnline ? 'online' : 'offline'}">
                            ${isOnline ? '🟢 Online' : '🔴 Offline'}
                        </span>
                    </div>
                    <div class="machine-galon">
                        <div class="galon-item">
                            <div class="galon-label">Galon 1</div>
                            <div class="galon-bar">
                                <div class="galon-fill ${g1Status}" style="width:${Math.min(g1, 100)}%"></div>
                            </div>
                            <div class="galon-value">${g1.toFixed(1)}%</div>
                        </div>
                        <div class="galon-item">
                            <div class="galon-label">Galon 2</div>
                            <div class="galon-bar">
                                <div class="galon-fill ${g2Status}" style="width:${Math.min(g2, 100)}%"></div>
                            </div>
                            <div class="galon-value">${g2.toFixed(1)}%</div>
                        </div>
                    </div>
                    <div class="machine-detail">
                        <span><i class="fas fa-tag"></i> ${m.mode || 'RO'}</span>
                        <span><i class="fas fa-microchip"></i> ${m.state || 'IDLE'}</span>
                        <span><i class="fas fa-tint"></i> ${(m.total_available_liters || 0).toFixed(1)} L</span>
                        ${m.last_seen ? `<span><i class="far fa-clock"></i> ${parseServerTime(m.last_seen).toLocaleTimeString('id-ID')}</span>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }

    // ──────────────────────────────────────
    // Add Machine Modal
    // ──────────────────────────────────────

    function openAddMachineModal() {
        DOM.addMachineForm.reset();
        DOM.addMachineError.style.display = 'none';
        DOM.addMachineError.textContent = '';
        // Selalu mulai dari tampilan form (bukan state sukses sisa sebelumnya)
        showAddMachineFormView();
        DOM.addMachineModal.classList.add('show');
        document.getElementById('fldMachineId')?.focus();
    }

    function closeAddMachineModal() {
        DOM.addMachineModal.classList.remove('show');
    }

    function showAddMachineFormView() {
        DOM.addMachineForm.style.display = '';
        DOM.addMachineSuccessState.style.display = 'none';
        DOM.addMachineFormFooter.style.display = '';
        DOM.addMachineSuccessFooter.style.display = 'none';
    }

    function showAddMachineSuccessView(machineId, secret) {
        DOM.successMachineId.textContent = machineId;
        DOM.successMachineSecret.value = secret;
        DOM.addMachineForm.style.display = 'none';
        DOM.addMachineSuccessState.style.display = 'block';
        DOM.addMachineFormFooter.style.display = 'none';
        DOM.addMachineSuccessFooter.style.display = 'flex';
    }

    async function handleAddMachineSubmit(e) {
        e.preventDefault();

        const payload = {
            machine_id: document.getElementById('fldMachineId').value.trim(),
            name: document.getElementById('fldMachineName').value.trim(),
            admin_pin: document.getElementById('fldMachinePin').value.trim(),
            mode: document.getElementById('fldMachineMode').value,
            price_per_liter: parseInt(document.getElementById('fldMachinePrice').value, 10) || 500,
            location: document.getElementById('fldMachineLocation').value.trim() || null,
        };

        if (!/^\d{4}$/.test(payload.admin_pin)) {
            DOM.addMachineError.textContent = 'PIN admin harus 4 digit angka.';
            DOM.addMachineError.style.display = 'block';
            return;
        }

        DOM.addMachineSubmitBtn.disabled = true;
        DOM.addMachineSubmitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
        DOM.addMachineError.style.display = 'none';

        try {
            const res = await Auth.fetchWithAuth('/api/iot/machines', {
                method: 'POST',
                body: JSON.stringify(payload),
            });

            // PENTING: tampilkan secret yang di-generate backend (kolom
            // machines.secret, lihat create_machine()) di modal — kalau
            // cuma toast (hilang 3 detik), admin tidak sempat menyalinnya
            // ke MACHINE_SECRET firmware unit ini.
            showAddMachineSuccessView(payload.machine_id, res.machine?.secret || '(tidak tersedia)');
            showToast(`✅ Mesin ${payload.machine_id} berhasil ditambahkan`);

            // Refresh grid mesin supaya mesin baru langsung tampil di
            // background (modal tetap terbuka sampai admin klik "Selesai")
            await loadDashboardData();

        } catch (error) {
            console.error('[App] Add machine error:', error);
            DOM.addMachineError.textContent = error.message || 'Gagal menambahkan mesin. Coba lagi.';
            DOM.addMachineError.style.display = 'block';
        } finally {
            DOM.addMachineSubmitBtn.disabled = false;
            DOM.addMachineSubmitBtn.innerHTML = '<i class="fas fa-plus"></i> Simpan Mesin';
        }
    }

    function handleCopySecret() {
        DOM.successMachineSecret.select();
        navigator.clipboard?.writeText(DOM.successMachineSecret.value)
            .then(() => showToast('📋 Secret disalin ke clipboard'))
            .catch(() => {
                // Fallback browser lama: teks sudah ke-select, tinggal Ctrl+C manual
                showToast('Tekan Ctrl+C untuk menyalin (auto-copy tidak didukung browser ini)');
            });
    }

    // ──────────────────────────────────────
    // Location Page — load data
    // ──────────────────────────────────────

    async function loadLocationsPageData() {
        try {
            const data = await Auth.fetchWithAuth('/api/iot/locations');
            _locationsData = data.locations || [];
            LocationMap.render(_locationsData);
            LocationMap.renderTable(_locationsData);
        } catch (error) {
            console.error('[App] Load locations error:', error);
            showToast('⚠️ Gagal memuat data lokasi');
        }
    }

    // ──────────────────────────────────────
    // Location Modal — Tambah / Edit
    // ──────────────────────────────────────

    async function populateLocationMachineDropdown(preselectMachineId) {
        DOM.fldLocMachine.innerHTML = '<option value="">Memuat daftar mesin...</option>';
        try {
            const data = await Auth.fetchWithAuth('/api/iot/machines');
            const machines = data.machines || [];

            if (machines.length === 0) {
                DOM.fldLocMachine.innerHTML = '<option value="">Belum ada mesin terdaftar</option>';
                return;
            }

            DOM.fldLocMachine.innerHTML = machines.map(m => {
                const hasLocation = m.latitude && m.longitude && m.latitude !== 0 && m.longitude !== 0;
                const label = `${m.machine_id} — ${m.name || 'Dispenser'}${hasLocation ? ' (sudah ada lokasi)' : ''}`;
                return `<option value="${m.machine_id}">${label}</option>`;
            }).join('');

            if (preselectMachineId) {
                DOM.fldLocMachine.value = preselectMachineId;
            }
        } catch (error) {
            console.error('[App] Load machines dropdown error:', error);
            DOM.fldLocMachine.innerHTML = '<option value="">Gagal memuat daftar mesin</option>';
        }
    }

    function fillLocationFormFromCache(machineId) {
        const loc = _locationsData.find(l => l.machine_id === machineId);
        if (!loc) return;
        DOM.fldLocAddress.value = loc.address || '';
        DOM.fldLocLat.value = (loc.latitude && loc.latitude !== 0) ? loc.latitude : '';
        DOM.fldLocLng.value = (loc.longitude && loc.longitude !== 0) ? loc.longitude : '';
    }

    async function openLocationModal(machineId) {
        _editingMachineId = machineId || null;
        DOM.locationForm.reset();
        DOM.locationError.style.display = 'none';
        DOM.locationError.textContent = '';
        LocationMap.disablePickMode();
        LocationMap.setSuppressFit(true);
        DOM.pickFromMapHint.style.display = 'none';

        DOM.locationModalTitle.textContent = _editingMachineId ? 'Edit Lokasi' : 'Tambah Lokasi';
        DOM.deleteMachineBtn.style.display = _editingMachineId ? 'inline-flex' : 'none';

        await populateLocationMachineDropdown(_editingMachineId);

        if (_editingMachineId) {
            // Mode edit: mesin sudah ditentukan (dari popup/tabel), kunci dropdown-nya.
            DOM.fldLocMachine.disabled = true;
            fillLocationFormFromCache(_editingMachineId);
        } else {
            DOM.fldLocMachine.disabled = false;
        }

        DOM.locationModal.classList.add('show');
    }

    function closeLocationModal() {
        DOM.locationModal.classList.remove('show');
        LocationMap.disablePickMode();
        LocationMap.setSuppressFit(false);
        DOM.pickFromMapHint.style.display = 'none';
        _editingMachineId = null;
    }

    async function handleLocationFormSubmit(e) {
        e.preventDefault();

        const machineId = DOM.fldLocMachine.value;
        const address = DOM.fldLocAddress.value.trim();
        const lat = parseFloat(DOM.fldLocLat.value);
        const lng = parseFloat(DOM.fldLocLng.value);

        if (!machineId) {
            DOM.locationError.textContent = 'Pilih mesin terlebih dahulu.';
            DOM.locationError.style.display = 'block';
            return;
        }
        if (isNaN(lat) || isNaN(lng)) {
            DOM.locationError.textContent = 'Latitude/Longitude harus diisi. Ketik manual atau pakai "Ambil dari Peta".';
            DOM.locationError.style.display = 'block';
            return;
        }

        DOM.locationSubmitBtn.disabled = true;
        DOM.locationSubmitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Menyimpan...';
        DOM.locationError.style.display = 'none';

        try {
            const params = new URLSearchParams({ lat, lng });
            if (address) params.set('address', address);

            await Auth.fetchWithAuth(`/api/iot/locations/${machineId}?${params.toString()}`, {
                method: 'POST',
            });

            showToast(`✅ Lokasi ${machineId} berhasil disimpan`);
            closeLocationModal();
            await loadLocationsPageData();

        } catch (error) {
            console.error('[App] Save location error:', error);
            DOM.locationError.textContent = error.message || 'Gagal menyimpan lokasi. Coba lagi.';
            DOM.locationError.style.display = 'block';
        } finally {
            DOM.locationSubmitBtn.disabled = false;
            DOM.locationSubmitBtn.innerHTML = '<i class="fas fa-check"></i> Simpan Lokasi';
        }
    }

    async function handleDeleteMachine(machineId, machineName) {
        if (!machineId) return;

        const confirmed = confirm(
            `Hapus mesin ${machineName || machineId}?\n\n` +
            `Mesin akan hilang dari daftar aktif, peta, dan dropdown. ` +
            `Riwayat transaksi/laporan yang sudah ada TETAP tersimpan dan ` +
            `tetap tampil apa adanya di halaman Laporan.\n\n` +
            `Tindakan ini tidak bisa dibatalkan sendiri lewat dashboard. Lanjutkan?`
        );
        if (!confirmed) return;

        try {
            await Auth.fetchWithAuth(`/api/iot/machines/${machineId}`, { method: 'DELETE' });
            showToast(`🗑️ Mesin ${machineId} berhasil dihapus`);
            closeLocationModal();
            await loadLocationsPageData();
            await loadDashboardData(); // sinkron: mesin juga hilang dari Overview
        } catch (error) {
            console.error('[App] Delete machine error:', error);
            showToast('⚠️ ' + (error.message || 'Gagal menghapus mesin'));
        }
    }

    function handlePickFromMapClick() {
        DOM.pickFromMapHint.style.display = 'block';
        showToast('Klik pada peta untuk mengisi koordinat...');

        // Modal overlay menutupi peta — sembunyikan sementara (bukan
        // ditutup penuh, form tetap terjaga) supaya peta di baliknya
        // bisa diklik langsung oleh admin.
        DOM.locationModal.style.display = 'none';

        LocationMap.enablePickMode((lat, lng) => {
            DOM.fldLocLat.value = lat.toFixed(6);
            DOM.fldLocLng.value = lng.toFixed(6);
            LocationMap.showPickPreview(lat, lng);
            LocationMap.disablePickMode();
            DOM.pickFromMapHint.style.display = 'none';
            DOM.locationModal.style.display = '';
            showToast('📍 Koordinat terisi dari peta');
        });
    }

    async function handleMapSearch() {
        const query = DOM.mapSearchInput.value.trim();
        if (!query) return;

        DOM.mapSearchBtn.disabled = true;
        try {
            const result = await LocationMap.searchAddress(query);
            if (!result) {
                showToast('Alamat tidak ditemukan');
            }
        } catch (error) {
            console.error('[App] Search address error:', error);
            showToast('⚠️ Gagal mencari alamat');
        } finally {
            DOM.mapSearchBtn.disabled = false;
        }
    }

    // ──────────────────────────────────────
    // Render Monitoring
    // ──────────────────────────────────────

    function renderMonitoring(machines) {
        const container = document.getElementById('monitoringContent');
        if (!container) return;

        if (!machines || machines.length === 0) {
            container.innerHTML = `
                <div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--text-light);">
                    <i class="fas fa-microchip" style="font-size:3rem;display:block;margin-bottom:16px;opacity:0.3;"></i>
                    <h3 style="font-weight:600;margin-bottom:8px;">Belum ada data mesin</h3>
                    <p style="font-size:0.85rem;">Tunggu data dari firmware ESP32 atau refresh halaman</p>
                    <button onclick="location.reload()" style="margin-top:16px;padding:8px 24px;background:var(--primary);color:white;border:none;border-radius:8px;cursor:pointer;font-family:var(--font);">
                        <i class="fas fa-sync-alt"></i> Refresh
                    </button>
                </div>
            `;
            return;
        }

        container.innerHTML = `<div class="monitoring-grid">${
            machines.map(m => {
                const isOnline = m.online === 1 || m.online === true;
                const g1 = m.g1_level_pct || 0;
                const g2 = m.g2_level_pct || 0;
                const g1Status = g1 < 5 ? 'danger' : g1 < 20 ? 'warning' : 'ok';
                const g2Status = g2 < 5 ? 'danger' : g2 < 20 ? 'warning' : 'ok';

                let rawData = {};
                try {
                    if (m.raw_json) {
                        rawData = typeof m.raw_json === 'string' ? JSON.parse(m.raw_json) : m.raw_json;
                    }
                } catch (e) {}

                const actuators = rawData.actuators || {};
                const system = rawData.system || {};
                const galon = rawData.galon || {};

                const state = m.state || 'UNKNOWN';
                const mode = m.mode || 'RO';
                const totalLiters = m.total_available_liters || 0;

                const pump = actuators.pump_dc ? 'ON' : 'OFF';
                const uv = actuators.uv_lamp ? 'ON' : 'OFF';
                const sol1 = actuators.solenoid_ro1 ? 'ON' : 'OFF';
                const sol2 = actuators.solenoid_ro2 ? 'ON' : 'OFF';
                const solP1 = actuators.solenoid_pump1 ? 'ON' : 'OFF';
                const solP2 = actuators.solenoid_pump2 ? 'ON' : 'OFF';

                const lastSeen = m.last_seen ? parseServerTime(m.last_seen).toLocaleString('id-ID') : '-';

                return `
                    <div class="monitoring-card ${isOnline ? '' : 'offline'}">
                        <div class="monitoring-header">
                            <span class="machine-name">
                                <i class="fas fa-microchip"></i> ${m.machine_id}
                                <span style="font-weight:400;font-size:0.7rem;color:var(--text-light);margin-left:4px;">
                                    (${m.name || 'Dispenser'})
                                </span>
                            </span>
                            <span class="machine-status ${isOnline ? 'online' : 'offline'}">
                                ${isOnline ? '🟢 Online' : '🔴 Offline'}
                            </span>
                        </div>

                        <div class="monitoring-galon">
                            <div class="galon-item">
                                <div class="galon-label">Galon 1</div>
                                <div class="galon-bar">
                                    <div class="galon-fill ${g1Status}" style="width:${Math.min(g1, 100)}%"></div>
                                </div>
                                <div class="galon-value">${g1.toFixed(1)}%</div>
                            </div>
                            <div class="galon-item">
                                <div class="galon-label">Galon 2</div>
                                <div class="galon-bar">
                                    <div class="galon-fill ${g2Status}" style="width:${Math.min(g2, 100)}%"></div>
                                </div>
                                <div class="galon-value">${g2.toFixed(1)}%</div>
                            </div>
                        </div>

                        <div class="monitoring-body">
                            <div class="monitoring-section">
                                <h4><i class="fas fa-thermometer-half"></i> Sensor</h4>
                                <div class="sensor-item">
                                    <span class="label">State</span>
                                    <span class="value">${state}</span>
                                </div>
                                <div class="sensor-item">
                                    <span class="label">Mode</span>
                                    <span class="value">${mode}</span>
                                </div>
                                <div class="sensor-item">
                                    <span class="label">Total Air</span>
                                    <span class="value">${totalLiters.toFixed(1)} L</span>
                                </div>
                                <div class="sensor-item">
                                    <span class="label">Active Galon</span>
                                    <span class="value">G${galon.active_galon || 1}</span>
                                </div>
                                ${system.wifi_rssi !== undefined ? `
                                <div class="sensor-item">
                                    <span class="label">WiFi RSSI</span>
                                    <span class="value ${system.wifi_rssi < -70 ? 'warning' : ''}">${system.wifi_rssi} dBm</span>
                                </div>
                                ` : ''}
                                ${system.uptime_sec ? `
                                <div class="sensor-item">
                                    <span class="label">Uptime</span>
                                    <span class="value">${formatUptime(system.uptime_sec)}</span>
                                </div>
                                ` : ''}
                            </div>

                            <div class="monitoring-section">
                                <h4><i class="fas fa-plug"></i> Aktuator</h4>
                                <div class="actuator-item">
                                    <span class="label">Pump DC</span>
                                    <span class="value ${pump === 'ON' ? 'on' : 'off'}">${pump}</span>
                                </div>
                                <div class="actuator-item">
                                    <span class="label">UV Lamp</span>
                                    <span class="value ${uv === 'ON' ? 'on' : 'off'}">${uv}</span>
                                </div>
                                <div class="actuator-item">
                                    <span class="label">Solenoid RO1</span>
                                    <span class="value ${sol1 === 'ON' ? 'on' : 'off'}">${sol1}</span>
                                </div>
                                <div class="actuator-item">
                                    <span class="label">Solenoid RO2</span>
                                    <span class="value ${sol2 === 'ON' ? 'on' : 'off'}">${sol2}</span>
                                </div>
                                <div class="actuator-item">
                                    <span class="label">Solenoid Pump1</span>
                                    <span class="value ${solP1 === 'ON' ? 'on' : 'off'}">${solP1}</span>
                                </div>
                                <div class="actuator-item">
                                    <span class="label">Solenoid Pump2</span>
                                    <span class="value ${solP2 === 'ON' ? 'on' : 'off'}">${solP2}</span>
                                </div>
                            </div>
                        </div>

                        <div class="monitoring-log" id="log-${m.machine_id}">
                            <div class="log-entry">
                                <span class="log-time">${lastSeen}</span>
                                <span class="log-level-${isOnline ? 'INFO' : 'ERROR'}">[${isOnline ? 'INFO' : 'ERROR'}]</span>
                                ${isOnline ? 'Online' : 'Offline'}
                            </div>
                            <div class="log-entry">
                                <span class="log-time">${lastSeen}</span>
                                <span class="log-level-INFO">[INFO]</span>
                                State: ${state} | Mode: ${mode}
                            </div>
                            <div class="log-entry">
                                <span class="log-time">${lastSeen}</span>
                                <span class="log-level-${g1 < 20 ? 'WARNING' : 'INFO'}">[${g1 < 20 ? 'WARNING' : 'INFO'}]</span>
                                G1: ${g1.toFixed(1)}% ${g1 < 20 ? '⚠️ Rendah' : '✓'}
                            </div>
                            <div class="log-entry">
                                <span class="log-time">${lastSeen}</span>
                                <span class="log-level-${g2 < 20 ? 'WARNING' : 'INFO'}">[${g2 < 20 ? 'WARNING' : 'INFO'}]</span>
                                G2: ${g2.toFixed(1)}% ${g2 < 20 ? '⚠️ Rendah' : '✓'}
                            </div>
                            ${system.firmware_ver ? `
                            <div class="log-entry">
                                <span class="log-time">${lastSeen}</span>
                                <span class="log-level-INFO">[INFO]</span>
                                Firmware: ${system.firmware_ver}
                            </div>
                            ` : ''}
                        </div>

                        <div class="monitoring-footer">
                            <span class="last-seen">
                                <i class="far fa-clock"></i>
                                Last: ${lastSeen}
                            </span>
                            <span>
                                <i class="fas fa-code"></i>
                                FW: ${system.firmware_ver || 'v1.3.4'}
                            </span>
                        </div>
                    </div>
                `;
            }).join('')
        }</div>`;
    }

    function formatUptime(seconds) {
        if (!seconds) return '-';
        const d = Math.floor(seconds / 86400);
        const h = Math.floor((seconds % 86400) / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        const parts = [];
        if (d > 0) parts.push(d + 'd');
        if (h > 0) parts.push(h + 'h');
        if (m > 0) parts.push(m + 'm');
        if (s > 0 || parts.length === 0) parts.push(s + 's');
        return parts.join(' ');
    }

    // ──────────────────────────────────────
    // WebSocket Event Handlers
    // ──────────────────────────────────────

    function setupWebSocketHandlers() {
        IoTWebSocket.on('connected', () => {
            DOM.wsStatusText.textContent = 'Connected';
            DOM.wsStatusDot.className = 'status-dot online';
            if (DOM.settingsWebsocket) {
                DOM.settingsWebsocket.textContent = '✅ Connected';
                DOM.settingsWebsocket.className = 'status-online';
            }
        });

        IoTWebSocket.on('disconnected', () => {
            DOM.wsStatusText.textContent = 'Disconnected';
            DOM.wsStatusDot.className = 'status-dot offline';
            if (DOM.settingsWebsocket) {
                DOM.settingsWebsocket.textContent = '❌ Disconnected';
                DOM.settingsWebsocket.className = 'status-offline';
            }
        });

        IoTWebSocket.on('machine_status', (data) => {
            if (data.machines) {
                _machineData = data.machines;
                renderMachines(_machineData);
                
                const online = _machineData.filter(m => m.online).length;
                DOM.statMachines.textContent = `${online}/${_machineData.length}`;
                DOM.machineCount.textContent = _machineData.length;

                if (_currentPage === 'monitoring') {
                    renderMonitoring(_machineData);
                }

                if (_currentPage === 'locations' && _locationsData.length > 0) {
                    // PENTING: payload 'machine_status' dari WebSocket cuma
                    // berisi status online/level galon dkk, TIDAK ada
                    // lat/lng/address. Gabungkan status online-nya saja ke
                    // cache lokasi yang sudah ada, jangan timpa langsung
                    // (dulu di sini `LocationMap.render(data.machines)`
                    // menyebabkan semua pin hilang dari peta).
                    const onlineById = new Map(data.machines.map(m => [m.machine_id, m.online]));
                    _locationsData = _locationsData.map(loc => ({
                        ...loc,
                        online: onlineById.has(loc.machine_id) ? onlineById.get(loc.machine_id) : loc.online,
                    }));
                    LocationMap.render(_locationsData);
                    LocationMap.renderTable(_locationsData);
                }
            }
        });

        IoTWebSocket.on('sales_update', (data) => {
            if (data.summary) {
                DOM.statVolume.textContent = (data.summary.volume_liters || 0).toFixed(1) + ' L';
                DOM.statRevenue.textContent = 'Rp ' + (data.summary.revenue || 0).toLocaleString('id-ID');
                DOM.statTransactions.textContent = data.summary.transactions || 0;
            }

            if (data.recent_transactions) {
                TransactionsUI.renderRecent(data.recent_transactions);
            }
        });

        IoTWebSocket.on('alarm', (data) => {
            const alarm = data.alarm || {};
            const msg = alarm.message || 'Alarm dari mesin ' + (data.machine_id || '');
            showToast(`🔔 ${msg}`, 4000);
        });

        IoTWebSocket.on('realtime_flow', (data) => {
            // Handle flow data if needed
        });

        IoTWebSocket.on('error', (data) => {
            console.error('[WS] Error:', data);
            showToast('⚠️ WebSocket error: ' + (data.error || 'Unknown'), 3000);
        });

        IoTWebSocket.on('reconnect_failed', () => {
            showToast('⚠️ Gagal reconnect WebSocket. Refresh halaman.', 5000);
        });
    }

    // ──────────────────────────────────────
    // Navigation
    // ──────────────────────────────────────

    function navigateTo(page) {
        _currentPage = page;

        document.querySelectorAll('.menu-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        document.querySelectorAll('.page-content').forEach(el => {
            el.classList.toggle('active', el.id === `page-${page}`);
        });

        const titles = {
            overview: 'Overview',
            monitoring: 'Monitoring Mesin',
            transactions: 'Riwayat Transaksi',
            reports: 'Laporan Penjualan',
            locations: 'Lokasi Mesin',
            settings: 'Pengaturan',
        };
        DOM.pageTitle.textContent = titles[page] || page;

        if (page === 'locations') {
            setTimeout(() => LocationMap.refresh(), 300);
            loadLocationsPageData();
        }
        if (page === 'transactions') {
            TransactionsUI.loadTransactions();
        }
        if (page === 'reports') {
            loadReportData('today');
        }
        if (page === 'monitoring') {
            renderMonitoring(_machineData);
            if (_machineData.length === 0) {
                loadDashboardData();
            }
        }
    }

    // ──────────────────────────────────────
    // Report Page
    // ──────────────────────────────────────

    async function loadReportData(period) {
        try {
            const machineId = DOM.reportMachineFilter?.value || '';
            const machineQuery = machineId ? `&machine_id=${encodeURIComponent(machineId)}` : '';

            const data = await Auth.fetchWithAuth(`/api/iot/summary?period=${period}${machineQuery}`);
            
            document.getElementById('reportVolume').textContent = (data.volume_liters || 0).toFixed(1) + ' L';
            document.getElementById('reportRevenue').textContent = 'Rp ' + (data.revenue || 0).toLocaleString('id-ID');
            document.getElementById('reportTransactions').textContent = data.transactions || 0;
            document.getElementById('reportAvg').textContent = 'Rp ' + (data.avg_revenue_per_trx || 0).toLocaleString('id-ID');

            const chartType = period === 'today' ? 'hourly' : period === 'week' ? 'weekly' : 'monthly';
            const chartData = await Auth.fetchWithAuth(`/api/iot/charts?chart_type=${chartType}${machineQuery}`);
            Charts.renderReportChart(chartData, period);

        } catch (error) {
            console.error('[App] Load report error:', error);
        }
    }

    // ──────────────────────────────────────
    // Toast Notification
    // ──────────────────────────────────────

    function showToast(message, duration = 3000) {
        const existing = document.querySelector('.toast-notification');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = 'toast-notification';
        toast.style.cssText = `
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #1A3A52;
            color: white;
            padding: 14px 20px;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 500;
            z-index: 9999;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            max-width: 400px;
            animation: slideUp 0.3s ease;
            font-family: 'Plus Jakarta Sans', sans-serif;
        `;
        toast.textContent = message;

        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideUp {
                from { transform: translateY(20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ──────────────────────────────────────
    // Clock
    // ──────────────────────────────────────

    function startClock() {
        function update() {
            const now = new Date();
            DOM.topbarTime.textContent = now.toLocaleTimeString('id-ID', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
        }
        update();
        setInterval(update, 1000);
    }

    // ──────────────────────────────────────
    // Sidebar Functions
    // ──────────────────────────────────────

    function initSidebarState() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        const isMobile = window.innerWidth <= 768;
        
        if (isMobile) {
            // Mobile: sidebar tertutup
            if (sidebar) {
                sidebar.classList.remove('open');
                sidebar.classList.remove('collapsed');
                sidebar.style.width = '';
                sidebar.style.minWidth = '';
                sidebar.style.overflow = '';
                sidebar.style.borderRight = '';
            }
            if (overlay) {
                overlay.style.display = 'block';
                overlay.classList.remove('show');
            }
        } else {
            // Desktop: sidebar terbuka
            if (sidebar) {
                sidebar.classList.remove('collapsed');
                sidebar.classList.remove('open');
                sidebar.style.width = '';
                sidebar.style.minWidth = '';
                sidebar.style.overflow = '';
                sidebar.style.borderRight = '';
            }
            if (overlay) {
                overlay.style.display = 'none';
                overlay.classList.remove('show');
            }
        }
    }

    function toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        
        if (!sidebar) return;
        
        const isMobile = window.innerWidth <= 768;
        
        if (isMobile) {
            // Mobile: toggle class 'open'
            sidebar.classList.toggle('open');
            if (overlay) {
                overlay.classList.toggle('show');
                // Scroll body agar tidak scroll saat sidebar terbuka
                document.body.style.overflow = sidebar.classList.contains('open') ? 'hidden' : '';
            }
        } else {
            // Desktop: toggle class 'collapsed'
            sidebar.classList.toggle('collapsed');
            if (sidebar.classList.contains('collapsed')) {
                sidebar.style.width = '0';
                sidebar.style.minWidth = '0';
                sidebar.style.overflow = 'hidden';
                sidebar.style.borderRight = 'none';
            } else {
                sidebar.style.width = '';
                sidebar.style.minWidth = '';
                sidebar.style.overflow = '';
                sidebar.style.borderRight = '';
            }
        }
    }

    function closeSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        const isMobile = window.innerWidth <= 768;
        
        if (isMobile && sidebar) {
            sidebar.classList.remove('open');
            if (overlay) {
                overlay.classList.remove('show');
            }
            document.body.style.overflow = '';
        }
    }

    // ──────────────────────────────────────
    // Settings
    // ──────────────────────────────────────
    // ── Settings Page ──

    let _currentSettingsMachine = null;

    function populateSettingsMachineSelect() {
        const select = document.getElementById('settingsMachineSelect');
        if (!select) return;
        // Simpan pilihan sebelumnya
        const current = select.value;
        select.innerHTML = '<option value="">Pilih Mesin...</option>';
        _machineData.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.machine_id;
            opt.textContent = `${m.machine_id} — ${m.name || ''}`;
            select.appendChild(opt);
        });
        if (current && _machineData.some(m => m.machine_id === current)) {
            select.value = current;
        }
    }

    async function loadSettingsForMachine(machineId) {
        if (!machineId) return;
        _currentSettingsMachine = machineId;
        try {
            const data = await Auth.fetchWithAuth(`/api/iot/settings/${machineId}`);
            const config = data.config || {};
            // Set mode dropdown
            const modeSelect = document.getElementById('setMode');
            if (modeSelect && config.mode) {
                modeSelect.value = config.mode;
            }
                        // Isi form
            document.getElementById('setPrice').value = config.price_per_liter || 500;
            document.getElementById('setTimeout').value = config.standby_timeout_sec || 30;
            document.getElementById('setSlideDuration').value = config.slide_duration_ms || 5000;
            const toggle = document.getElementById('setSignageToggle');
            if (toggle) {
                toggle.classList.toggle('on', config.signage_enabled != 0);
            }
            // Tampilkan form
            document.getElementById('settingsFormContainer').style.display = 'block';
            // Muat daftar slide
            renderSlideList(data.slides || []);

            // Setelah config diisi, periksa apakah ada slide aktif
            const activeSlides = (data.slides || []).filter(s => s.is_active == 1);
            if (toggle) {
                // Jika ada slide aktif, toggle on; jika tidak ada, toggle off (kecuali config menyatakan on)
                const hasActiveSlide = activeSlides.length > 0;
                const configEnabled = config.signage_enabled != 0;
                // Prioritas: jika tidak ada slide, signage tidak aktif
                if (!hasActiveSlide) {
                    toggle.classList.remove('on');
                    // Update config di backend? Tidak, biarkan user yang mengaktifkan setelah upload.
                } else {
                    // Jika ada slide, ikuti config
                    if (configEnabled) toggle.classList.add('on');
                    else toggle.classList.remove('on');
                }
            }
        } catch (error) {
            console.error('[Settings] Load error:', error);
            showToast('⚠️ Gagal memuat pengaturan');
        }
    }

    async function saveSettings() {
        const machineId = _currentSettingsMachine;
        if (!machineId) return;
        const payload = {
            price_per_liter: parseInt(document.getElementById('setPrice').value) || 500,
            standby_timeout_sec: parseInt(document.getElementById('setTimeout').value) || 30,
            slide_duration_ms: parseInt(document.getElementById('setSlideDuration').value) || 5000,
            signage_enabled: document.getElementById('setSignageToggle').classList.contains('on') ? 1 : 0,
            mode: document.getElementById('setMode').value,
        };
        try {
            const result = await Auth.fetchWithAuth(`/api/iot/settings/${machineId}`, {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            if (result.mode_warning) {
                // Config lain tersimpan, tapi perintah ganti mode gagal terkirim ke mesin
                document.getElementById('settingsSaveResult').innerHTML = `<span style="color:var(--warning);">⚠️ ${result.mode_warning}</span>`;
                showToast('⚠️ Mode gagal dikirim ke mesin — cek koneksi MQTT');
            } else {
                document.getElementById('settingsSaveResult').innerHTML = `<span style="color:var(--success);">✅ Pengaturan disimpan</span>`;
                showToast('✅ Pengaturan berhasil disimpan');
            }
            // Refresh data settings
            await loadSettingsForMachine(machineId);
            // Refresh dashboard juga
            await loadDashboardData();
        } catch (error) {
            document.getElementById('settingsSaveResult').innerHTML = `<span style="color:var(--danger);">❌ ${error.message}</span>`;
            showToast('⚠️ Gagal simpan pengaturan');
        }
    }

    async function changePin() {
        const machineId = _currentSettingsMachine;
        if (!machineId) return;
        const oldPin = document.getElementById('setOldPin').value.trim();
        const newPin = document.getElementById('setNewPin').value.trim();
        const confirmPin = document.getElementById('setConfirmPin').value.trim();
        if (!oldPin || !newPin || !confirmPin) {
            document.getElementById('settingsPinResult').innerHTML = `<span style="color:var(--danger);">Semua field PIN harus diisi</span>`;
            return;
        }
        if (newPin !== confirmPin) {
            document.getElementById('settingsPinResult').innerHTML = `<span style="color:var(--danger);">Konfirmasi PIN tidak cocok</span>`;
            return;
        }
        if (newPin.length !== 4 || !/^\d{4}$/.test(newPin)) {
            document.getElementById('settingsPinResult').innerHTML = `<span style="color:var(--danger);">PIN baru harus 4 digit angka</span>`;
            return;
        }
        try {
            await Auth.fetchWithAuth(`/api/iot/settings/${machineId}/pin`, {
                method: 'POST',
                body: JSON.stringify({ old_pin: oldPin, new_pin: newPin, confirm_pin: confirmPin }),
            });
            document.getElementById('settingsPinResult').innerHTML = `<span style="color:var(--success);">✅ PIN berhasil diubah</span>`;
            showToast('✅ PIN admin berhasil diubah');
            // Kosongkan field
            document.getElementById('setOldPin').value = '';
            document.getElementById('setNewPin').value = '';
            document.getElementById('setConfirmPin').value = '';
        } catch (error) {
            document.getElementById('settingsPinResult').innerHTML = `<span style="color:var(--danger);">❌ ${error.message}</span>`;
            showToast('⚠️ Gagal ubah PIN');
        }
    }

    // ── Slide Management ──

    function renderSlideList(slides) {
        const container = document.getElementById('slideListContainer');
        if (!container) return;
        if (!slides || slides.length === 0) {
            container.innerHTML = `<p style="color:var(--text-light);">Belum ada slide. Upload gambar/video di bawah.</p>`;
            return;
        }
        let html = `<div style="display:flex; flex-direction:column; gap:8px;">`;
        slides.forEach((slide, idx) => {
            const isVideo = slide.media_type === 'video';
            const preview = isVideo ? '🎬 Video' : `<img src="${slide.url}" style="height:60px; width:auto; object-fit:cover; border-radius:4px;">`;
            html += `
                <div style="display:flex; align-items:center; gap:12px; background:var(--bg); padding:8px 12px; border-radius:8px;" data-order="${slide.slide_order || 0}">
                    <div style="width:80px; flex-shrink:0;">${preview}</div>
                    <div style="flex:1;">
                        <div style="font-weight:600;">${slide.media_type.toUpperCase()} #${slide.id}</div>
                        <div style="font-size:0.7rem; color:var(--text-light);">${slide.caption || ''}</div>
                        <div style="font-size:0.65rem; color:var(--text-light);">Urutan: ${slide.slide_order || 0} | Aktif: ${slide.is_active ? '✅' : '❌'}</div>
                    </div>
                    <div style="display:flex; gap:4px;">
                        <button class="icon-btn slide-up" data-id="${slide.id}" title="Naikkan urutan"><i class="fas fa-arrow-up"></i></button>
                        <button class="icon-btn slide-down" data-id="${slide.id}" title="Turunkan urutan"><i class="fas fa-arrow-down"></i></button>
                        <button class="icon-btn slide-toggle" data-id="${slide.id}" data-active="${slide.is_active}" title="Toggle aktif"><i class="fas ${slide.is_active ? 'fa-toggle-on' : 'fa-toggle-off'}"></i></button>
                        <button class="icon-btn danger slide-delete" data-id="${slide.id}" title="Hapus"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            `;
        });
        html += `</div>`;
        container.innerHTML = html;

        // Pasang event listener untuk tombol
        container.querySelectorAll('.slide-up').forEach(btn => {
            btn.addEventListener('click', () => reorderSlide(btn.dataset.id, 'up'));
        });
        container.querySelectorAll('.slide-down').forEach(btn => {
            btn.addEventListener('click', () => reorderSlide(btn.dataset.id, 'down'));
        });
        container.querySelectorAll('.slide-toggle').forEach(btn => {
            btn.addEventListener('click', () => toggleSlideActive(btn.dataset.id, btn.dataset.active));
        });
        container.querySelectorAll('.slide-delete').forEach(btn => {
            btn.addEventListener('click', () => deleteSlide(btn.dataset.id));
        });
    }

    async function reorderSlide(slideId, direction) {
        const machineId = _currentSettingsMachine;
        if (!machineId) return;
        // Ambil slide saat ini
        const container = document.getElementById('slideListContainer');
        // Cari slide di DOM atau dari data terakhir
        // Lebih sederhana: kita panggil ulang load settings setelah update.
        // Untuk demo, kita update order dengan +1 atau -1
        try {
            // Dapatkan slide saat ini dari container
            const slideElement = document.querySelector(`[data-id="${slideId}"]`)?.closest('div[data-order]');
            const currentOrder = parseInt(slideElement?.dataset.order || 0);
            const newOrder = direction === 'up' ? Math.max(0, currentOrder - 1) : currentOrder + 1;
            await Auth.fetchWithAuth(`/api/iot/settings/${machineId}/signage/${slideId}`, {
                method: 'PATCH',
                body: JSON.stringify({ slide_order: newOrder }),
            });
            // Reload settings
            await loadSettingsForMachine(machineId);
            showToast('✅ Urutan slide diperbarui');
        } catch (error) {
            showToast('⚠️ Gagal update urutan: ' + error.message);
        }
    }

    async function toggleSlideActive(slideId, currentActive) {
        const machineId = _currentSettingsMachine;
        if (!machineId) return;
        const newActive = currentActive == 1 ? 0 : 1;
        try {
            await Auth.fetchWithAuth(`/api/iot/settings/${machineId}/signage/${slideId}`, {
                method: 'PATCH',
                body: JSON.stringify({ is_active: newActive }),
            });
            await loadSettingsForMachine(machineId);
            showToast(`Slide ${newActive ? 'diaktifkan' : 'dinonaktifkan'}`);
        } catch (error) {
            showToast('⚠️ Gagal toggle slide: ' + error.message);
        }
    }

    async function deleteSlide(slideId) {
        if (!confirm('Hapus slide ini?')) return;
        const machineId = _currentSettingsMachine;
        if (!machineId) return;
        try {
            await Auth.fetchWithAuth(`/api/iot/settings/${machineId}/signage/${slideId}`, {
                method: 'DELETE',
            });
            await loadSettingsForMachine(machineId);
            showToast('✅ Slide dihapus');
        } catch (error) {
            showToast('⚠️ Gagal hapus slide: ' + error.message);
        }
    }

    // ── Upload Slide ──

    let _pendingSlideFile = null;

    document.getElementById('slideUploadBtn')?.addEventListener('click', () => {
        document.getElementById('slideFileInput').click();
    });

    document.getElementById('slideFileInput')?.addEventListener('change', (e) => {
        _pendingSlideFile = e.target.files[0];
        if (_pendingSlideFile) {
            document.getElementById('slideUploadBtn').innerHTML = `<i class="fas fa-file"></i> ${_pendingSlideFile.name}`;
        }
    });

    document.getElementById('slideUploadConfirm')?.addEventListener('click', async () => {
        const machineId = _currentSettingsMachine;
        if (!machineId) {
            showToast('Pilih mesin terlebih dahulu');
            return;
        }
        if (!_pendingSlideFile) {
            showToast('Pilih file terlebih dahulu');
            return;
        }
        const caption = document.getElementById('slideCaptionInput').value.trim();
        const formData = new FormData();
        formData.append('file', _pendingSlideFile);
        if (caption) formData.append('caption', caption);
        
        try {
            const token = Auth.getToken();
            if (!token) throw new Error('Token tidak ditemukan');
            
            const response = await fetch(`/api/iot/settings/${machineId}/signage`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'ngrok-skip-browser-warning': 'true', // no-op kalau bukan lewat ngrok, aman dibiarkan
                    // JANGAN set Content-Type
                },
                body: formData,
            });
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || error.message || 'Upload gagal');
            }
            
            const result = await response.json();
            document.getElementById('slideUploadResult').innerHTML = `<span style="color:var(--success);">✅ Upload berhasil</span>`;
            showToast('✅ Slide berhasil diupload');
            // Reset
            _pendingSlideFile = null;
            document.getElementById('slideFileInput').value = '';
            document.getElementById('slideUploadBtn').innerHTML = `<i class="fas fa-upload"></i> Upload Slide`;
            document.getElementById('slideCaptionInput').value = '';
            // Reload settings
            await loadSettingsForMachine(machineId);
        } catch (error) {
            document.getElementById('slideUploadResult').innerHTML = `<span style="color:var(--danger);">❌ ${error.message}</span>`;
            showToast('⚠️ Gagal upload: ' + error.message);
        }
    });

    // ── Event Binding untuk Settings ──

    document.getElementById('settingsMachineSelect')?.addEventListener('change', function() {
        const val = this.value;
        if (val) {
            loadSettingsForMachine(val);
        } else {
            document.getElementById('settingsFormContainer').style.display = 'none';
        }
    });

    document.getElementById('settingsLoadBtn')?.addEventListener('click', function() {
        const select = document.getElementById('settingsMachineSelect');
        const val = select.value;
        if (val) {
            loadSettingsForMachine(val);
        } else {
            showToast('Pilih mesin terlebih dahulu');
        }
    });

    document.getElementById('settingsSaveBtn')?.addEventListener('click', saveSettings);
    document.getElementById('settingsPinBtn')?.addEventListener('click', changePin);

    // Toggle switch untuk signage
    document.getElementById('setSignageToggle')?.addEventListener('click', function() {
        this.classList.toggle('on');
    });

    function setupSettings() {
        document.getElementById('settingStatusRate')?.addEventListener('change', function() {
            const val = parseInt(this.value);
            showToast(`Status refresh diubah ke ${val} detik`);
        });

        document.getElementById('settingSalesRate')?.addEventListener('change', function() {
            const val = parseInt(this.value);
            showToast(`Sales refresh diubah ke ${val} detik`);
        });

        document.querySelectorAll('.toggle-switch').forEach(toggle => {
            toggle.addEventListener('click', function() {
                this.classList.toggle('on');
                const label = this.closest('.settings-item')?.querySelector('label')?.textContent || '';
                const isOn = this.classList.contains('on');
                showToast(`${isOn ? '✅' : '❌'} ${label} ${isOn ? 'diaktifkan' : 'dinonaktifkan'}`);
            });
        });
    }

    async function loadGlobalSettings() {
        try {
            const data = await Auth.fetchWithAuth('/api/iot/global/settings');
            document.getElementById('globalDefaultPrice').value = data.default_price || 500;
            document.getElementById('globalDefaultMode').value = data.default_mode || 'RO';
        } catch (error) {
            console.error('[Global] Load error:', error);
            showToast('⚠️ Gagal memuat pengaturan global');
        }
    }

    async function saveGlobalPrice() {
        const price = parseInt(document.getElementById('globalDefaultPrice').value);
        if (price < 1) {
            showToast('Harga tidak valid');
            return;
        }
        try {
            const result = await Auth.fetchWithAuth('/api/iot/global/settings', {
                method: 'POST',
                body: JSON.stringify({ default_price: price })
            });
            document.getElementById('globalSettingsResult').innerHTML =
                `<span style="color:var(--success);">✅ Harga default diupdate, mempengaruhi ${result.affected_machines} mesin</span>`;
            showToast('✅ Harga default disinkron ke semua mesin');
            // Reload daftar mesin & settings yang sedang terbuka
            await loadDashboardData();
            if (_currentSettingsMachine) {
                await loadSettingsForMachine(_currentSettingsMachine);
            }
        } catch (error) {
            document.getElementById('globalSettingsResult').innerHTML =
                `<span style="color:var(--danger);">❌ ${error.message}</span>`;
        }
    }

    async function saveGlobalMode() {
        const mode = document.getElementById('globalDefaultMode').value;
        try {
            const result = await Auth.fetchWithAuth('/api/iot/global/settings', {
                method: 'POST',
                body: JSON.stringify({ default_mode: mode })
            });
            document.getElementById('globalSettingsResult').innerHTML =
                `<span style="color:var(--success);">✅ Mode default diupdate, mempengaruhi ${result.affected_machines} mesin</span>`;
            showToast('✅ Mode default disinkron ke semua mesin');
            await loadDashboardData();
            if (_currentSettingsMachine) {
                await loadSettingsForMachine(_currentSettingsMachine);
            }
        } catch (error) {
            document.getElementById('globalSettingsResult').innerHTML =
                `<span style="color:var(--danger);">❌ ${error.message}</span>`;
        }
    }

    // ──────────────────────────────────────
    // Event Bindings
    // ──────────────────────────────────────

    function bindEvents() {
        
        const loginForm = document.getElementById('loginForm');
        const loginError = document.getElementById('loginError');
        const loginBtn = document.getElementById('loginBtn');

        // Tambahkan ini:
        DOM.loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = DOM.loginUsername.value.trim();
            const password = DOM.loginPassword.value.trim();

            if (!username || !password) {
                DOM.loginError.textContent = 'Username dan password harus diisi';
                DOM.loginError.style.display = 'block';
                return;
            }

            DOM.loginBtn.disabled = true;
            DOM.loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Login...';
            DOM.loginError.style.display = 'none';

            try {
                await Auth.login(username, password);
                showDashboard();
            } catch (error) {
                DOM.loginError.textContent = error.message || 'Login gagal, coba lagi';
                DOM.loginError.style.display = 'block';
            } finally {
                DOM.loginBtn.disabled = false;
                DOM.loginBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i> Login';
            }
        });

        DOM.logoutBtn.addEventListener('click', () => {
            console.log('[App] Logout clicked'); // untuk debugging
            Auth.logout();
            IoTWebSocket.disconnect();
            showLogin();
        });

        if (DOM.logoutBtn) {
            DOM.logoutBtn.addEventListener('click', () => {
                Auth.logout();
                IoTWebSocket.disconnect();
                showLogin();
            });
        } else {
            console.warn('[App] Logout button not found');
        }

        document.getElementById('globalSaveBtn')?.addEventListener('click', saveGlobalPrice);
        document.getElementById('globalModeSaveBtn')?.addEventListener('click', saveGlobalMode);


        // Sidebar navigation
        document.querySelectorAll('.menu-item').forEach(item => {
            item.addEventListener('click', () => {
                const page = item.dataset.page;
                if (page) {
                    navigateTo(page);
                    // Tutup sidebar di mobile setelah navigasi
                    if (window.innerWidth <= 768) {
                        closeSidebar();
                    }
                }
            });
        });

        // Sidebar toggle - PERBAIKAN UTAMA
        DOM.sidebarToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleSidebar();
        });

        // Tutup sidebar saat klik overlay
        document.getElementById('sidebarOverlay')?.addEventListener('click', function() {
            closeSidebar();
        });

        // Handle resize
        window.addEventListener('resize', function() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('sidebarOverlay');
            const isMobile = window.innerWidth <= 768;
            
            if (!isMobile) {
                // Pindah ke desktop - reset mobile state
                if (sidebar) {
                    sidebar.classList.remove('open');
                    // Jika sidebar collapsed di desktop, biarkan
                }
                if (overlay) {
                    overlay.classList.remove('show');
                    overlay.style.display = 'none';
                }
                document.body.style.overflow = '';
            } else {
                // Pindah ke mobile - tampilkan overlay
                if (overlay) {
                    overlay.style.display = 'block';
                }
                // Jika sidebar terbuka di desktop, tutup saat pindah ke mobile
                if (sidebar && !sidebar.classList.contains('collapsed')) {
                    // Biarkan terbuka jika user ingin
                }
            }
        });

        // Chart tabs
        document.querySelectorAll('.chart-tab').forEach(tab => {
            tab.addEventListener('click', async function() {
                document.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
                this.classList.add('active');

                const chartType = this.dataset.chart;
                try {
                    const data = await Auth.fetchWithAuth(`/api/iot/charts?chart_type=${chartType}`);
                    Charts.updateSalesChart(data, chartType);
                } catch (error) {
                    console.error('[App] Load chart error:', error);
                }
            });
        });

        // Report tabs
        document.querySelectorAll('.report-tab').forEach(tab => {
            tab.addEventListener('click', function() {
                document.querySelectorAll('.report-tab').forEach(t => t.classList.remove('active'));
                this.classList.add('active');
                const period = this.dataset.period;
                loadReportData(period);
            });
        });

        // Report machine filter — reload laporan untuk periode yang sedang aktif
        DOM.reportMachineFilter?.addEventListener('change', () => {
            const activeTab = document.querySelector('.report-tab.active');
            loadReportData(activeTab?.dataset.period || 'today');
        });

        // Filter apply
        document.getElementById('filterApply')?.addEventListener('click', () => {
            const filters = {
                machineId: document.getElementById('filterMachine').value,
                status: document.getElementById('filterStatus').value,
                startDate: document.getElementById('filterStartDate').value,
                endDate: document.getElementById('filterEndDate').value,
            };
            TransactionsUI.setFilters(filters);
            TransactionsUI.loadTransactions(1);
        });

        // Filter reset
        document.getElementById('filterReset')?.addEventListener('click', () => {
            TransactionsUI.resetFilters();
            TransactionsUI.loadTransactions(1);
        });

        // View all transactions
        document.querySelector('.view-all')?.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo('transactions');
        });

        // Tambah Mesin modal
        DOM.addMachineBtn?.addEventListener('click', openAddMachineModal);
        DOM.addMachineCloseBtn?.addEventListener('click', closeAddMachineModal);
        DOM.addMachineCancelBtn?.addEventListener('click', closeAddMachineModal);
        DOM.addMachineForm?.addEventListener('submit', handleAddMachineSubmit);
        DOM.addMachineDoneBtn?.addEventListener('click', closeAddMachineModal);
        DOM.copySecretBtn?.addEventListener('click', handleCopySecret);
        DOM.addMachineModal?.addEventListener('click', (e) => {
            // Klik area gelap di luar modal-card = tutup
            if (e.target === DOM.addMachineModal) closeAddMachineModal();
        });

        // Lokasi: toolbar
        DOM.addLocationBtn?.addEventListener('click', () => openLocationModal(null));
        DOM.refreshMapBtn?.addEventListener('click', () => {
            loadLocationsPageData();
            showToast('🔄 Data lokasi diperbarui');
        });
        DOM.mapSearchBtn?.addEventListener('click', handleMapSearch);
        DOM.mapSearchInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleMapSearch();
            }
        });

        // Lokasi: modal Tambah/Edit
        DOM.locationCloseBtn?.addEventListener('click', closeLocationModal);
        DOM.locationCancelBtn?.addEventListener('click', closeLocationModal);
        DOM.locationForm?.addEventListener('submit', handleLocationFormSubmit);
        DOM.pickFromMapBtn?.addEventListener('click', handlePickFromMapClick);
        DOM.deleteMachineBtn?.addEventListener('click', () => {
            const opt = DOM.fldLocMachine.selectedOptions[0];
            handleDeleteMachine(_editingMachineId, opt?.textContent);
        });
        DOM.fldLocMachine?.addEventListener('change', () => {
            // Mode Tambah: kalau admin pilih mesin yang ternyata sudah
            // punya lokasi, auto-isi form-nya (jadi efektif jadi edit).
            if (!_editingMachineId) fillLocationFormFromCache(DOM.fldLocMachine.value);
        });
        DOM.locationModal?.addEventListener('click', (e) => {
            if (e.target === DOM.locationModal) closeLocationModal();
        });

        // Popup marker & tombol tabel "Daftar Lokasi Mesin" (dispatch dari location.js)
        window.addEventListener('location:edit', (e) => openLocationModal(e.detail.machine_id));
        window.addEventListener('location:delete', (e) => handleDeleteMachine(e.detail.machine_id, e.detail.name));

        // Keyboard shortcut: Escape untuk tutup sidebar / modal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (DOM.addMachineModal?.classList.contains('show')) {
                    closeAddMachineModal();
                } else if (DOM.locationModal?.classList.contains('show')) {
                    closeLocationModal();
                } else {
                    closeSidebar();
                }
            }
        });

        // Toggle signage — langsung simpan saat diklik
        document.getElementById('setSignageToggle')?.addEventListener('click', function() {
            this.classList.toggle('on');
            const enabled = this.classList.contains('on') ? 1 : 0;
            const machineId = _currentSettingsMachine;
            if (!machineId) return;
            // Kirim update hanya signage_enabled
            Auth.fetchWithAuth(`/api/iot/settings/${machineId}`, {
                method: 'POST',
                body: JSON.stringify({ signage_enabled: enabled })
            })
            .then(() => {
                showToast('✅ Signage ' + (enabled ? 'diaktifkan' : 'dinonaktifkan'));
                // Reload settings untuk sinkron
                loadSettingsForMachine(machineId);
            })
            .catch(err => {
                showToast('⚠️ Gagal update signage: ' + err.message);
                // Kembalikan toggle ke keadaan semula
                this.classList.toggle('on');
            });
        });
    }

    // ──────────────────────────────────────
    // Initialize Machine Filters
    // ──────────────────────────────────────

    // PERBAIKAN: fungsi lama ini (initMachineFilter) ternyata TIDAK PERNAH
    // dipanggil di mana pun — jadi dropdown filter mesin di halaman
    // Transaksi selama ini selalu kosong (cuma opsi "Semua Mesin"), meski
    // mesinnya sudah terdaftar. Sekarang diganti populateMachineFilters(),
    // dipanggil ulang setiap loadDashboardData() (termasuk setelah
    // Tambah Mesin) supaya dropdown Transaksi & Laporan selalu sinkron
    // dengan daftar mesin terbaru. Dibuat idempotent (bersihkan opsi lama
    // dulu) supaya aman dipanggil berkali-kali tanpa duplikasi.
    function populateMachineFilters() {
        [DOM.filterMachine, DOM.reportMachineFilter].forEach(select => {
            if (!select) return;
            const currentValue = select.value;
            // Buang semua opsi dinamis, sisakan "Semua Mesin" (value="")
            select.querySelectorAll('option[value]:not([value=""])').forEach(opt => opt.remove());
            _machineData.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.machine_id;
                opt.textContent = m.machine_id;
                select.appendChild(opt);
            });
            // Pertahankan pilihan user kalau mesinnya masih ada di daftar
            if (currentValue && _machineData.some(m => m.machine_id === currentValue)) {
                select.value = currentValue;
            }
        });
    }

    // ──────────────────────────────────────
    // Init
    // ──────────────────────────────────────

    async function init() {
        console.log('[App] TOYAMAS IoT Dashboard v1.3');


        setupWebSocketHandlers();
        bindEvents();
        setupSettings();

        if (DOM.settingsFirmware) {
            DOM.settingsFirmware.textContent = 'v1.3.4';
        }

        await checkAuth();
        LocationMap.init();

        console.log('[App] Ready');
    }

    // Run
    document.addEventListener('DOMContentLoaded', init);

})();