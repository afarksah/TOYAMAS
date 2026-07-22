/**
 * auth.js — Authentication dengan username/password
 * TOYAMAS IoT Dashboard
 */

const Auth = (() => {
    const API_BASE = window.location.origin;

    let _token = null;
    let _user = null;

    // ──────────────────────────────────────
    // Login
    // ──────────────────────────────────────

    async function login(username, password) {
        try {
            const response = await fetch(`${API_BASE}/auth/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'ngrok-skip-browser-warning': 'true', // no-op kalau bukan lewat ngrok, aman dibiarkan
                },
                body: JSON.stringify({ username, password })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Login gagal');
            }

            const data = await response.json();

            _token = data.token;
            _user = {
                username: data.username,
                name: data.name,
                role: data.role,
            };

            localStorage.setItem('toyamas_admin_token', JSON.stringify({
                token: _token,
                user: _user,
                expires_at: Date.now() + (data.expires_in || 7200) * 1000
            }));

            return data;
        } catch (error) {
            console.error('[Auth] Login error:', error);
            throw error;
        }
    }

    // ──────────────────────────────────────
    // Session Management
    // ──────────────────────────────────────

    function init() {
        const saved = localStorage.getItem('toyamas_admin_token');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                if (data.token && data.expires_at > Date.now()) {
                    _token = data.token;
                    _user = data.user;
                    return true;
                }
            } catch (e) {
                logout();
            }
        }
        return false;
    }

    function getToken() {
        // Refresh token jika mendekati expired (opsional, bisa diimplementasikan)
        const saved = localStorage.getItem('toyamas_admin_token');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                if (data.expires_at > Date.now() + 60000) {
                    return data.token;
                }
                // Jika near expiry, bisa refresh (belum diimplementasikan)
            } catch (e) {
                logout();
            }
        }
        return _token;
    }

    function getUser() {
        if (!_user) {
            const saved = localStorage.getItem('toyamas_admin_token');
            if (saved) {
                try {
                    const data = JSON.parse(saved);
                    _user = data.user;
                } catch (e) {}
            }
        }
        return _user;
    }

    function isAuthenticated() {
        const token = getToken();
        return !!token;
    }

    function logout() {
        const token = _token; // simpan token sebelum dihapus
        _token = null;
        _user = null;
        localStorage.removeItem('toyamas_admin_token');

        // Opsional: panggil logout endpoint dengan token yang masih valid
        if (token) {
            fetch(`${API_BASE}/auth/logout`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            }).catch(() => {
                // Abaikan error, karena kita sudah logout di client
            });
        }
    }
    // ──────────────────────────────────────
    // HTTP Helpers
    // ──────────────────────────────────────

    function authHeaders() {
        const token = getToken();
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': 'true', // no-op kalau bukan lewat ngrok, aman dibiarkan
        };
    }

    async function fetchWithAuth(endpoint, options = {}) {
        const token = getToken();
        if (!token) {
            throw new Error('Not authenticated');
        }

        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: {
                ...authHeaders(),
                ...(options.headers || {}),
            }
        });

        if (response.status === 401) {
            // Token expired — logout
            logout();
            throw new Error('Sesi habis, silakan login ulang');
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || error.message || 'Request failed');
        }

        return response.json();
    }

    // ──────────────────────────────────────
    // Public API
    // ──────────────────────────────────────

    return {
        init,
        login,
        getToken,
        getUser,
        isAuthenticated,
        logout,
        fetchWithAuth,
        authHeaders,
    };

})();

window.Auth = Auth;