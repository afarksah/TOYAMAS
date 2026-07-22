/**
 * location.js — Leaflet Map for Machine Locations
 * TOYAMAS IoT Dashboard
 */

const LocationMap = (() => {

    let _map = null;
    let _markers = [];
    let _initialized = false;
    let _lastLocations = [];

    // Mode "Ambil dari Peta" — saat aktif, klik berikutnya di peta akan
    // memanggil _pickCallback(lat, lng) alih-alih perilaku klik normal.
    let _pickMode = false;
    let _pickCallback = null;
    let _pickMarker = null;

    // Saat modal Tambah/Edit Lokasi terbuka, viewport peta TIDAK boleh
    // auto ter-refit (fitBounds) ke semua lokasi setiap ada update
    // realtime masuk — supaya posisi pan/zoom yang sedang dipakai admin
    // untuk menentukan titik lokasi tidak tiba-tiba berubah sendiri.
    // Di-set true saat modal dibuka, di-set false lagi saat modal
    // ditutup (baik karena Simpan berhasil maupun Batal/close).
    let _suppressFit = false;

    // ──────────────────────────────────────

    function init() {
        if (_initialized) return;

        const container = document.getElementById('locationMap');
        if (!container) return;

        // Default center: Indonesia
        _map = L.map(container, {
            center: [-2.5, 118.0],
            zoom: 5,
            zoomControl: true,
        });

        // Tile layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors',
        }).addTo(_map);

        _map.on('click', (e) => {
            if (_pickMode && _pickCallback) {
                _pickCallback(e.latlng.lat, e.latlng.lng);
            }
        });

        _initialized = true;
        console.log('[LocationMap] Initialized');
    }

    function render(locations) {
        if (!_initialized) init();

        _lastLocations = locations || [];

        // Clear existing markers
        _markers.forEach(m => _map.removeLayer(m));
        _markers = [];

        if (!locations || locations.length === 0) {
            console.warn('[LocationMap] No locations to render');
            updateLegend([]);
            return;
        }

        // Filter locations with coordinates
        const validLocations = locations.filter(l =>
            l.latitude && l.longitude && l.latitude !== 0 && l.longitude !== 0
        );

        if (validLocations.length === 0) {
            console.warn('[LocationMap] No valid coordinates');
            updateLegend([]);
            return;
        }

        // Add markers
        validLocations.forEach(loc => {
            const isOnline = loc.online === 1 || loc.online === true;
            const iconColor = isOnline ? '#34C38F' : '#E85D5D';

            const marker = L.circleMarker([loc.latitude, loc.longitude], {
                radius: 12,
                fillColor: iconColor,
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8,
            }).addTo(_map);

            marker.bindPopup(buildPopupContent(loc, isOnline), {
                maxWidth: 260,
                className: 'custom-popup',
            });

            // Event delegation: pasang listener tombol Edit/Hapus setiap
            // kali popup ini dibuka (konten popup di-render ulang tiap
            // buka, jadi listener lama otomatis lepas bersama DOM lama).
            marker.on('popupopen', (e) => {
                const el = e.popup.getElement();
                if (!el) return;
                const editBtn = el.querySelector('[data-popup-edit]');
                const delBtn = el.querySelector('[data-popup-delete]');
                if (editBtn) {
                    editBtn.addEventListener('click', () => {
                        marker.closePopup();
                        window.dispatchEvent(new CustomEvent('location:edit', { detail: { machine_id: loc.machine_id } }));
                    });
                }
                if (delBtn) {
                    delBtn.addEventListener('click', () => {
                        marker.closePopup();
                        window.dispatchEvent(new CustomEvent('location:delete', { detail: { machine_id: loc.machine_id, name: loc.name } }));
                    });
                }
            });

            _markers.push(marker);
        });

        // Fit map to markers — dilewati kalau modal Tambah/Edit Lokasi
        // sedang terbuka (_suppressFit), supaya posisi peta yang sedang
        // dipakai admin untuk menentukan titik tidak tiba-tiba berubah
        // gara-gara ada update realtime masuk di belakang layar.
        if (_markers.length > 0 && !_suppressFit) {
            const group = L.featureGroup(_markers);
            _map.fitBounds(group.getBounds(), { padding: [30, 30] });
        }

        // Update legend
        updateLegend(validLocations);
    }

    function buildPopupContent(loc, isOnline) {
        const statusText = isOnline ? '🟢 Online' : '🔴 Offline';
        return `
            <div style="font-family:'Plus Jakarta Sans',sans-serif;min-width:180px;">
                <div style="font-weight:700;font-size:1rem;color:#1A3A52;">${loc.machine_id}</div>
                <div style="font-size:0.8rem;color:#7AAEC8;">${loc.name || 'Dispenser'}</div>
                <div style="font-size:0.75rem;margin:4px 0;">${statusText}</div>
                ${loc.address ? `<div style="font-size:0.7rem;color:#7AAEC8;">📍 ${loc.address}</div>` : ''}
                <div style="font-size:0.65rem;color:#7AAEC8;">${loc.latitude.toFixed(6)}, ${loc.longitude.toFixed(6)}</div>
                <div class="popup-actions" style="display:flex;gap:6px;margin-top:8px;">
                    <button data-popup-edit style="flex:1;background:#2A91D8;color:#fff;border:none;border-radius:6px;padding:5px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">
                        ✏️ Edit
                    </button>
                    <button data-popup-delete style="flex:1;background:#FDEDED;color:#E85D5D;border:none;border-radius:6px;padding:5px 8px;font-size:0.7rem;font-weight:600;cursor:pointer;">
                        🗑️ Hapus
                    </button>
                </div>
            </div>
        `;
    }

    function renderTable(locations) {
        const tbody = document.getElementById('locationsTableBody');
        if (!tbody) return;

        if (!locations || locations.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-light);">Belum ada mesin terdaftar</td></tr>`;
            return;
        }

        tbody.innerHTML = locations.map((loc, idx) => {
            const hasCoords = loc.latitude && loc.longitude && loc.latitude !== 0 && loc.longitude !== 0;
            const isOnline = loc.online === 1 || loc.online === true;

            let statusBadge;
            if (!hasCoords) {
                statusBadge = `<span class="status-badge unset">Belum diatur</span>`;
            } else if (isOnline) {
                statusBadge = `<span class="status-badge online">🟢 Online</span>`;
            } else {
                statusBadge = `<span class="status-badge offline">🔴 Offline</span>`;
            }

            return `
                <tr>
                    <td>${idx + 1}</td>
                    <td><strong>${loc.machine_id}</strong><br><span style="color:var(--text-light);font-size:0.7rem;">${loc.name || ''}</span></td>
                    <td>${loc.address || '<span style="color:var(--text-light);">Belum diatur</span>'}</td>
                    <td>${statusBadge}</td>
                    <td>
                        <button class="icon-btn" data-table-edit="${loc.machine_id}" title="Edit lokasi">
                            <i class="fas fa-pen"></i>
                        </button>
                        <button class="icon-btn danger" data-table-delete="${loc.machine_id}" data-name="${loc.name || loc.machine_id}" title="Hapus mesin">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        // Delegasi event sekali per render (tbody diganti isinya tiap render,
        // jadi listener lama otomatis lepas bersama node lama).
        tbody.querySelectorAll('[data-table-edit]').forEach(btn => {
            btn.addEventListener('click', () => {
                window.dispatchEvent(new CustomEvent('location:edit', { detail: { machine_id: btn.dataset.tableEdit } }));
            });
        });
        tbody.querySelectorAll('[data-table-delete]').forEach(btn => {
            btn.addEventListener('click', () => {
                window.dispatchEvent(new CustomEvent('location:delete', {
                    detail: { machine_id: btn.dataset.tableDelete, name: btn.dataset.name }
                }));
            });
        });
    }

    function updateLegend(locations) {
        const container = document.getElementById('mapLegend');
        if (!container) return;

        const online = locations.filter(l => l.online === 1 || l.online === true);
        const offline = locations.filter(l => l.online !== 1 && l.online !== true);

        container.innerHTML = `
            <div class="legend-item">
                <span class="legend-dot online"></span>
                ${online.length} Mesin Online
            </div>
            <div class="legend-item">
                <span class="legend-dot offline"></span>
                ${offline.length} Mesin Offline
            </div>
            <div class="legend-item" style="margin-left:auto;font-size:0.65rem;color:var(--text-light);">
                <i class="fas fa-sync-alt"></i>
                Update otomatis
            </div>
        `;
    }

    function refresh() {
        if (_map) {
            _map.invalidateSize();
        }
    }

    // ──────────────────────────────────────
    // Mode "Ambil dari Peta"
    // ──────────────────────────────────────

    function enablePickMode(callback) {
        if (!_initialized) init();
        _pickMode = true;
        _pickCallback = callback;
        const container = document.getElementById('locationMap');
        if (container) container.classList.add('picking');
    }

    function disablePickMode() {
        _pickMode = false;
        _pickCallback = null;
        const container = document.getElementById('locationMap');
        if (container) container.classList.remove('picking');
        if (_pickMarker) {
            _map.removeLayer(_pickMarker);
            _pickMarker = null;
        }
    }

    function showPickPreview(lat, lng) {
        if (!_initialized) init();
        if (_pickMarker) _map.removeLayer(_pickMarker);
        _pickMarker = L.marker([lat, lng]).addTo(_map);
    }

    function setSuppressFit(value) {
        _suppressFit = !!value;
    }

    // ──────────────────────────────────────
    // Search / Geocoding (Nominatim — OpenStreetMap)
    // ──────────────────────────────────────

    async function searchAddress(query) {
        if (!query || !query.trim()) return null;
        if (!_initialized) init();

        const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`;
        const res = await fetch(url, {
            headers: { 'Accept-Language': 'id' }
        });
        if (!res.ok) throw new Error('Gagal menghubungi layanan pencarian alamat');

        const results = await res.json();
        if (!results || results.length === 0) return null;

        const { lat, lon, display_name } = results[0];
        _map.flyTo([parseFloat(lat), parseFloat(lon)], 15, { duration: 1 });

        return { lat: parseFloat(lat), lng: parseFloat(lon), display_name };
    }

    function flyTo(lat, lng, zoom = 15) {
        if (!_initialized) init();
        _map.flyTo([lat, lng], zoom, { duration: 1 });
    }

    // ──────────────────────────────────────
    // Public API
    // ──────────────────────────────────────

    return {
        init,
        render,
        renderTable,
        refresh,
        enablePickMode,
        disablePickMode,
        showPickPreview,
        setSuppressFit,
        searchAddress,
        flyTo,
        getLastLocations: () => _lastLocations,
    };

})();

window.LocationMap = LocationMap;
