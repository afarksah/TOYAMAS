/**
 * transactions.js — Transactions Table
 * TOYAMAS IoT Dashboard
 */

const TransactionsUI = (() => {

    // ──────────────────────────────────────
    // Helper: parse timestamp UTC dari backend (lihat catatan di app.js)
    // ──────────────────────────────────────
    function parseServerTime(ts) {
        if (!ts) return null;
        let iso = String(ts).trim();
        if (iso.includes(' ') && !iso.includes('T')) iso = iso.replace(' ', 'T');
        if (!/Z$|[+-]\d{2}:?\d{2}$/.test(iso)) iso += 'Z';
        return new Date(iso);
    }

    let _currentPage = 1;
    let _totalPages = 1;
    let _filters = {
        machineId: '',
        status: '',
        startDate: '',
        endDate: '',
    };

    // ──────────────────────────────────────

    function render(transactions, pagination) {
        const tbody = document.getElementById('transactionsBody');
        if (!tbody) return;

        if (!transactions || transactions.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" style="text-align:center;padding:40px;color:var(--text-light);">
                        <i class="fas fa-inbox" style="font-size:1.5rem;display:block;margin-bottom:8px;"></i>
                        Belum ada transaksi
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = transactions.map(t => {
            const statusClass = {
                'PAID': 'paid',
                'PENDING': 'pending',
                'FAILED': 'failed',
                'EXPIRED': 'failed',
                'COMPLETE': 'complete',
                'DISPENSING': 'dispensing',
                'ABORTED': 'aborted',
                'WAITING': 'waiting',
            }[t.payment_status || t.dispense_status] || 'waiting';

            const statusLabel = t.payment_status || t.dispense_status || 'UNKNOWN';

            const time = t.created_at ? parseServerTime(t.created_at).toLocaleString('id-ID', {
                hour: '2-digit',
                minute: '2-digit',
                day: '2-digit',
                month: 'short',
            }) : '-';

            const volume = t.volume_actual || t.volume_requested || 0;
            const amount = t.amount || 0;

            return `
                <tr>
                    <td>${time}</td>
                    <td><code style="font-size:0.7rem;background:var(--bg);padding:2px 8px;border-radius:4px;">${t.order_id || '-'}</code></td>
                    <td>${t.machine_id || '-'}</td>
                    <td>${t.source || '-'}</td>
                    <td>${volume.toFixed(1)} L</td>
                    <td>Rp ${amount.toLocaleString('id-ID')}</td>
                    <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
                    <td><span class="status-badge ${statusClass}">${t.dispense_status || '-'}</span></td>
                </tr>
            `;
        }).join('');

        // Render pagination
        if (pagination) {
            renderPagination(pagination);
        }
    }

    function renderPagination(pagination) {
        const container = document.getElementById('transactionsPagination');
        if (!container) return;

        _currentPage = pagination.page || 1;
        _totalPages = pagination.total_pages || 1;

        const start = ((pagination.page - 1) * pagination.limit) + 1;
        const end = Math.min(pagination.page * pagination.limit, pagination.total);

        let html = `
            <span>Menampilkan ${start}-${end} dari ${pagination.total} transaksi</span>
            <div class="pagination-buttons">
        `;

        // Previous
        html += `
            <button class="pagination-btn" 
                    data-page="${pagination.page - 1}" 
                    ${pagination.page <= 1 ? 'disabled' : ''}>
                ←
            </button>
        `;

        // Page numbers (show max 5)
        const maxVisible = 5;
        let startPage = Math.max(1, pagination.page - 2);
        let endPage = Math.min(pagination.total_pages, startPage + maxVisible - 1);
        if (endPage - startPage < maxVisible - 1) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }

        if (startPage > 1) {
            html += `<button class="pagination-btn" data-page="1">1</button>`;
            if (startPage > 2) html += `<span style="padding:0 4px;color:var(--text-light);">…</span>`;
        }

        for (let i = startPage; i <= endPage; i++) {
            html += `
                <button class="pagination-btn ${i === pagination.page ? 'active' : ''}" 
                        data-page="${i}">
                    ${i}
                </button>
            `;
        }

        if (endPage < pagination.total_pages) {
            if (endPage < pagination.total_pages - 1) {
                html += `<span style="padding:0 4px;color:var(--text-light);">…</span>`;
            }
            html += `<button class="pagination-btn" data-page="${pagination.total_pages}">${pagination.total_pages}</button>`;
        }

        // Next
        html += `
            <button class="pagination-btn" 
                    data-page="${pagination.page + 1}" 
                    ${pagination.page >= pagination.total_pages ? 'disabled' : ''}>
                →
            </button>
        `;

        html += `</div>`;
        container.innerHTML = html;

        // Event listeners untuk pagination
        container.querySelectorAll('.pagination-btn:not([disabled])').forEach(btn => {
            btn.addEventListener('click', () => {
                const page = parseInt(btn.dataset.page);
                if (page && page !== _currentPage) {
                    loadTransactions(page);
                }
            });
        });
    }

    function renderRecent(transactions) {
        const tbody = document.getElementById('recentTransactionsBody');
        if (!tbody) return;

        if (!transactions || transactions.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align:center;padding:24px;color:var(--text-light);">
                        Belum ada transaksi
                    </td>
                </tr>
            `;
            return;
        }

        // Hanya tampilkan 5 terbaru
        const recent = transactions.slice(0, 5);

        tbody.innerHTML = recent.map(t => {
            const statusClass = {
                'PAID': 'paid',
                'COMPLETE': 'complete',
                'PENDING': 'pending',
                'FAILED': 'failed',
                'DISPENSING': 'dispensing',
                'ABORTED': 'aborted',
            }[t.payment_status || t.dispense_status] || 'waiting';

            const statusLabel = t.payment_status || t.dispense_status || 'UNKNOWN';

            const time = t.created_at ? parseServerTime(t.created_at).toLocaleString('id-ID', {
                hour: '2-digit',
                minute: '2-digit',
            }) : '-';

            const volume = t.volume_actual || t.volume_requested || 0;
            const amount = t.amount || 0;

            return `
                <tr>
                    <td>${time}</td>
                    <td><code style="font-size:0.65rem;background:var(--bg);padding:2px 6px;border-radius:4px;">${t.order_id || '-'}</code></td>
                    <td>${t.machine_id || '-'}</td>
                    <td>${volume.toFixed(1)} L</td>
                    <td>Rp ${amount.toLocaleString('id-ID')}</td>
                    <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
                </tr>
            `;
        }).join('');
    }

    function setFilters(filters) {
        _filters = { ..._filters, ...filters };
    }

    function getFilters() {
        return _filters;
    }

    function resetFilters() {
        _filters = {
            machineId: '',
            status: '',
            startDate: '',
            endDate: '',
        };
        _currentPage = 1;
        // Reset UI
        document.getElementById('filterMachine').value = '';
        document.getElementById('filterStatus').value = '';
        document.getElementById('filterStartDate').value = '';
        document.getElementById('filterEndDate').value = '';
    }

    function getParams() {
        const params = new URLSearchParams();
        if (_filters.machineId) params.append('machine_id', _filters.machineId);
        if (_filters.status) params.append('status', _filters.status);
        if (_filters.startDate) params.append('start_date', _filters.startDate);
        if (_filters.endDate) params.append('end_date', _filters.endDate);
        params.append('page', _currentPage);
        params.append('limit', 20);
        return params;
    }

    // ──────────────────────────────────────
    // Load Transactions from API
    // ──────────────────────────────────────

    async function loadTransactions(page = 1) {
        _currentPage = page;
        const params = getParams();

        try {
            const data = await Auth.fetchWithAuth(`/api/iot/transactions?${params}`);
            render(data.transactions, data.pagination);
            return data;
        } catch (error) {
            console.error('[Transactions] Load error:', error);
            return null;
        }
    }

    async function loadRecent() {
        try {
            const params = new URLSearchParams();
            params.append('limit', '10');
            const data = await Auth.fetchWithAuth(`/api/iot/transactions?${params}`);
            renderRecent(data.transactions);
            return data;
        } catch (error) {
            console.error('[Transactions] Load recent error:', error);
            return null;
        }
    }

    // ──────────────────────────────────────
    // Public API
    // ──────────────────────────────────────

    return {
        render,
        renderRecent,
        renderPagination,
        loadTransactions,
        loadRecent,
        setFilters,
        getFilters,
        resetFilters,
        getParams,
    };

})();

window.TransactionsUI = TransactionsUI;