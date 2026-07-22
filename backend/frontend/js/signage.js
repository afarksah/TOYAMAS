// frontend/js/signage.js
/**
 * Signage Module
 * Handle slideshow, digital signage, dan media (gambar/video) dari backend
 */

(function() {
    'use strict';

    const SignageUI = {
        _elements: {},
        _interval: null,
        _currentSlide: 0,
        _totalSlides: 4,
        _duration: 5000,          // default ms
        _isVideoMode: false,
        _isImageMode: false,
        _backendSlides: [],       // daftar slide dari backend
        _slideshowInterval: null,
        _currentImageIndex: 0,
        _isInitialized: false,
        _playlist: [],            // daftar slide aktif (gambar+video campur), terurut slide_order
        _playlistIndex: 0,        // posisi slide yang sedang tampil di playlist
        _slideTimer: null,        // timer untuk durasi tampil gambar / fallback video

        // ──────────────────────────────────────────────

        init() {
            if (this._isInitialized) return;
            console.log('[SignageUI] Initializing...');
            this._cacheElements();
            this._bindEvents();
            // Ambil durasi dari AppState jika ada
            if (typeof AppState !== 'undefined' && AppState.slideDuration) {
                this._duration = AppState.slideDuration;
            }
            // Mulai slideshow teks default dulu
            this.start();
            // Fetch slide dari backend
            this._fetchSlides();
            // Update info config read-only di admin
            this._updateAdminConfig();
            this._isInitialized = true;
        },

        _cacheElements() {
            this._elements = {
                slides: document.querySelectorAll('.slide-card'),
                dots: document.querySelectorAll('.sdot'),
                videoSignage: document.getElementById('videoSignage'),
                imageSignage: document.getElementById('imageSignage'),
                standbyPage: document.getElementById('page-standby'),
                logoContainer: document.querySelector('.logo-container'),
                slideArea: document.querySelector('.slide-area'),
                waveBg: document.querySelector('.wave-bg'),
                dropsDeco: document.getElementById('dropsDeco'),
                signageHeader: document.querySelector('.signage-header'),
                tapPrompt: document.querySelector('.tap-prompt'),
            };
            this._totalSlides = this._elements.slides.length || 4;
        },

        _bindEvents() {
            // Klik pada standby page -> ke method (kecuali klik video/slide)
            const standby = this._elements.standbyPage;
            if (standby) {
                standby.addEventListener('click', (e) => {
                    if (e.target.closest('video') || e.target.closest('.slide-card')) {
                        return;
                    }
                    if (typeof goTo === 'function') {
                        goTo('page-method');
                    }
                });
            }

            // Event dari AppState untuk perubahan config
            if (typeof AppState !== 'undefined') {
                AppState.on('config_change', (data) => {
                    if (data.key === 'slide_duration') {
                        this._duration = parseInt(data.value) || 5000;
                        if (this._isImageMode) {
                            // Jadwalkan ulang slide gambar yang sedang tampil dengan durasi baru
                            clearTimeout(this._slideTimer);
                            this._slideTimer = setTimeout(() => this._advancePlaylist(), this._duration);
                        } else if (!this._isVideoMode) {
                            // Jika mode teks, restart interval slideshow teks
                            this.stop();
                            this.start();
                        }
                    }
                    if (data.key === 'signage_enabled') {
                        const enabled = parseInt(data.value) !== 0;
                        if (!enabled) {
                            // Nonaktifkan semua media, kembali ke teks
                            this._disableMediaMode();
                            this.start();
                        } else {
                            // Aktifkan kembali, fetch ulang slides
                            this._fetchSlides();
                        }
                    }
                });
            }

            // Event dari WebSocket untuk update signage
            if (typeof API !== 'undefined') {
                API.on('signage_update', (data) => {
                    this.handleSignageUpdate(data);
                });
                API.on('config_update', (data) => {
                    this.handleConfigUpdate(data);
                });
            }
        },

        // ──────────────────────────────────────────────
        // SLIDESHOW TEKS DEFAULT
        // ──────────────────────────────────────────────

        start() {
            // Hanya jalankan jika tidak dalam mode media (video/gambar)
            if (this._isVideoMode || this._isImageMode) return;
            this.stop();
            this._interval = setInterval(() => {
                this.next();
            }, this._duration);
        },

        stop() {
            clearInterval(this._interval);
        },

        restart() {
            this.stop();
            this.start();
        },

        next() {
            const slides = this._elements.slides;
            const dots = this._elements.dots;
            if (!slides || slides.length === 0) return;

            slides.forEach(s => s.classList.remove('active'));
            dots.forEach(d => d.classList.remove('on'));

            this._currentSlide = (this._currentSlide + 1) % this._totalSlides;
            if (slides[this._currentSlide]) slides[this._currentSlide].classList.add('active');
            if (dots[this._currentSlide]) dots[this._currentSlide].classList.add('on');
        },

        goTo(index) {
            if (index < 0 || index >= this._totalSlides) return;
            const slides = this._elements.slides;
            const dots = this._elements.dots;
            slides.forEach(s => s.classList.remove('active'));
            dots.forEach(d => d.classList.remove('on'));
            this._currentSlide = index;
            if (slides[index]) slides[index].classList.add('active');
            if (dots[index]) dots[index].classList.add('on');
        },

        reset() {
            const slides = this._elements.slides;
            const dots = this._elements.dots;
            slides.forEach(s => s.classList.remove('active'));
            dots.forEach(d => d.classList.remove('on'));
            this._currentSlide = 0;
            if (slides[0]) slides[0].classList.add('active');
            if (dots[0]) dots[0].classList.add('on');
        },

        // ──────────────────────────────────────────────
        // FETCH SLIDES DARI BACKEND
        // ──────────────────────────────────────────────

        async _fetchSlides() {
            try {
                const data = await API.getMachineStatus();
                console.log('[Signage] Fetched status:', data);
                if (data && data.signage_slides && data.signage_slides.length > 0) {
                    console.log('[Signage] Slides found:', data.signage_slides);
                    this._backendSlides = data.signage_slides;
                    this._applyMediaSlides();
                } else {
                    console.log('[Signage] No slides, using default text slides');
                    this._backendSlides = [];
                    this._disableMediaMode();
                    this.start();
                }
                // Update admin read-only config
                if (data && data.settings) {
                    this._updateAdminConfig(data.settings);
                }
            } catch (e) {
                console.warn('[Signage] Fetch slides error:', e);
                this._backendSlides = [];
                this._disableMediaMode();
                this.start();
            }
        },

        // ──────────────────────────────────────────────
        // TERAPKAN MEDIA SLIDES (gambar/video)
        // ──────────────────────────────────────────────

        _applyMediaSlides() {
            // Cek apakah signage diaktifkan
            const enabled = (typeof AppState !== 'undefined' && AppState.signageEnabled !== undefined)
                ? AppState.signageEnabled
                : 1;
            if (!enabled) {
                this._disableMediaMode();
                this.start();
                return;
            }

            const activeSlides = this._backendSlides.filter(s => s.is_active !== 0);
            if (activeSlides.length === 0) {
                this._disableMediaMode();
                this.start();
                return;
            }

            // Urutkan gambar & video campur sesuai urutan (slide_order), lalu mainkan
            // sebagai satu playlist bergantian — bukan cuma video pertama yang ditemukan.
            const sorted = [...activeSlides].sort((a, b) => (a.order || 0) - (b.order || 0));

            this._isImageMode = false;
            this._isVideoMode = false;
            this._hideDecoElements();
            this._showHeaderAndTap();
            this.stop(); // hentikan slideshow teks

            this._playlist = sorted;
            this._playlistIndex = 0;
            this._playCurrentSlide();
        },

        // ──────────────────────────────────────────────
        // PLAYLIST: gambar & video bergantian sesuai urutan
        // ──────────────────────────────────────────────

        _playCurrentSlide() {
            clearTimeout(this._slideTimer);
            const slide = this._playlist[this._playlistIndex];
            if (!slide) {
                this._disableMediaMode();
                this.start();
                return;
            }
            if (slide.media_type === 'video') {
                this._isVideoMode = true;
                this._isImageMode = false;
                this._playVideoSlide(slide);
            } else {
                this._isImageMode = true;
                this._isVideoMode = false;
                this._playImageSlide(slide);
            }
        },

        _advancePlaylist() {
            clearTimeout(this._slideTimer);
            if (!this._playlist || this._playlist.length === 0) {
                this._disableMediaMode();
                this.start();
                return;
            }
            this._playlistIndex = (this._playlistIndex + 1) % this._playlist.length;
            this._playCurrentSlide();
        },

        // ──────────────────────────────────────────────
        // MODE VIDEO (satu slide dalam playlist)
        // ──────────────────────────────────────────────

        _playVideoSlide(slide) {
            const video = this._elements.videoSignage;
            const image = this._elements.imageSignage;
            const standby = this._elements.standbyPage;
            // Sembunyikan gambar sisa slide sebelumnya
            if (image) {
                image.style.display = 'none';
                image.src = '';
            }
            if (!video) {
                // Tidak ada elemen video, lewati ke slide berikutnya supaya tidak macet
                this._slideTimer = setTimeout(() => this._advancePlaylist(), this._duration || 5000);
                return;
            }

            video.style.display = 'block';
            video.style.position = 'absolute';
            video.style.top = '0';
            video.style.left = '0';
            video.style.width = '100%';
            video.style.height = '100%';
            video.style.objectFit = 'cover';
            video.style.zIndex = '0';
            video.muted = true;
            video.loop = false; // jangan diulang - lanjut ke slide berikutnya saat selesai
            video.onended = null;
            video.onended = () => this._advancePlaylist();
            video.src = slide.url;
            video.play().catch(e => {
                console.warn('[Signage] Video autoplay error:', e);
                // Fallback: jika autoplay gagal, tetap lanjut agar playlist tidak macet
                this._slideTimer = setTimeout(() => this._advancePlaylist(), this._duration || 5000);
            });

            if (standby) {
                standby.classList.add('video-mode');
            }

            console.log('[Signage] Playing video slide:', slide.url);
        },

        // ──────────────────────────────────────────────
        // MODE GAMBAR (satu slide dalam playlist)
        // ──────────────────────────────────────────────

        _playImageSlide(slide) {

            // Pastikan header & tap tetap terlihat
            this._showHeaderAndTap();
            const video = this._elements.videoSignage;
            if (video) {
                video.onended = null;
                video.pause();
                video.removeAttribute('src');
                video.load();
                video.style.display = 'none';
            }

            const image = this._elements.imageSignage;
            if (image) {
                image.src = slide.url;
                image.style.display = 'block';
                image.style.zIndex = '0'; // sudah defaultimage.src = slide.url;
                
                image.style.position = 'absolute';
                image.style.top = '0';
                image.style.left = '0';
                image.style.width = '100%';
                image.style.height = '100%';
                image.style.objectFit = 'cover';
               // Pastikan di bawah header/tap
            }

            const standby = this._elements.standbyPage;
            if (standby) {
                standby.classList.add('video-mode'); // reuse class
            }
            const header = this._elements.signageHeader;
            if (header) {
                header.style.zIndex = '10';
            }
            const tap = this._elements.tapPrompt;
            if (tap) {
                tap.style.zIndex = '10';
            }
            

            // Durasi Slide (ms) aktif hanya untuk gambar
            const duration = this._duration || 5000;
            this._slideTimer = setTimeout(() => this._advancePlaylist(), duration);

            console.log('[Signage] Showing image slide:', slide.url, 'for', duration, 'ms');
        },

        // ──────────────────────────────────────────────
        // MODE VIDEO — fallback lokal (upload kiosk, bukan dari backend)
        // ──────────────────────────────────────────────

        _enableVideoMode(videoUrl) {
            this._disableMediaMode(); // reset dulu
            this._isVideoMode = true;
            this._isImageMode = false;

            const video = this._elements.videoSignage;
            if (!video) return;

            video.src = videoUrl;
            video.style.display = 'block';
            video.style.position = 'absolute';
            video.style.top = '0';
            video.style.left = '0';
            video.style.width = '100%';
            video.style.height = '100%';
            video.style.objectFit = 'cover';
            video.style.zIndex = '0';
            video.muted = true;
            video.loop = true;
            video.play().catch(e => console.warn('[Signage] Video autoplay error:', e));

            // Tambahkan class video-mode ke standby page
            const standby = this._elements.standbyPage;
            if (standby) {
                standby.classList.add('video-mode');
                standby.style.background = 'transparent';
            }

            // Sembunyikan elemen dekoratif
            this._hideDecoElements();
            // Tampilkan header dan tap prompt
            this._showHeaderAndTap();

            // Hentikan slideshow teks
            this.stop();
            console.log('[Signage] Enabling video mode with URL:', videoUrl);
        },

        // ──────────────────────────────────────────────
        // NONAKTIFKAN MODE MEDIA (kembali ke teks)
        // ──────────────────────────────────────────────

        _disableMediaMode() {
            this._isVideoMode = false;
            this._isImageMode = false;
            clearInterval(this._slideshowInterval);
            this._slideshowInterval = null;
            clearTimeout(this._slideTimer);
            this._slideTimer = null;
            this._playlist = [];
            this._playlistIndex = 0;

            // Hentikan video
            const video = this._elements.videoSignage;
            if (video) {
                video.onended = null;
                video.pause();
                video.src = '';
                video.style.display = 'none';
                video.style.position = '';
                video.style.top = '';
                video.style.left = '';
                video.style.width = '';
                video.style.height = '';
                video.style.objectFit = '';
                video.style.zIndex = '';
            }

            // Sembunyikan gambar signage
            const image = this._elements.imageSignage;
            if (image) {
                image.style.display = 'none';
                image.src = '';
            }

            // Reset background standby
            const standby = this._elements.standbyPage;
            if (standby) {
                standby.classList.remove('video-mode');
                standby.style.backgroundImage = '';
                standby.style.background = 'linear-gradient(180deg, #0d4f7c 0%, #1a7fc1 45%, #5bb8f5 100%)';
            }

            // Tampilkan semua elemen
            const logo = this._elements.logoContainer;
            if (logo) {
                logo.style.display = '';
                logo.style.visibility = '';
            }
            const slideArea = this._elements.slideArea;
            if (slideArea) {
                slideArea.style.display = '';
                slideArea.style.visibility = '';
            }
            const waveBg = this._elements.waveBg;
            if (waveBg) {
                waveBg.style.display = '';
                waveBg.style.visibility = '';
            }
            const drops = this._elements.dropsDeco;
            if (drops) {
                drops.style.display = '';
                drops.style.visibility = '';
            }
            // Reset slide cards
            document.querySelectorAll('.slide-card').forEach(c => {
                c.style.display = '';
                c.style.visibility = '';
            });
            document.querySelectorAll('.slide-dots, .sdot').forEach(el => {
                el.style.display = '';
                el.style.visibility = '';
            });

            // Reset header & tap prompt
            const header = this._elements.signageHeader;
            if (header) {
                header.style.display = '';
                header.style.position = '';
                header.style.zIndex = '';
                header.style.visibility = '';
            }
            const tap = this._elements.tapPrompt;
            if (tap) {
                tap.style.display = '';
                tap.style.position = '';
                tap.style.zIndex = '';
                tap.style.visibility = '';
            }

            // Reset slide ke slide pertama
            this.reset();
            console.log('[Signage] Media mode disabled, back to text slideshow');
        },

        // ──────────────────────────────────────────────
        // HELPER: sembunyikan elemen dekoratif
        // ──────────────────────────────────────────────

        _hideDecoElements() {
            const logo = this._elements.logoContainer;
            if (logo) {
                logo.style.setProperty('display', 'none', 'important');
                logo.style.visibility = 'hidden';
            }
            const slideArea = this._elements.slideArea;
            if (slideArea) {
                slideArea.style.setProperty('display', 'none', 'important');
                slideArea.style.visibility = 'hidden';
            }
            const waveBg = this._elements.waveBg;
            if (waveBg) {
                waveBg.style.setProperty('display', 'none', 'important');
                waveBg.style.visibility = 'hidden';
            }
            const drops = this._elements.dropsDeco;
            if (drops) {
                drops.style.setProperty('display', 'none', 'important');
                drops.style.visibility = 'hidden';
            }
            // Sembunyikan slide cards dan dots
            document.querySelectorAll('.slide-card').forEach(c => {
                c.style.setProperty('display', 'none', 'important');
                c.style.visibility = 'hidden';
            });
            document.querySelectorAll('.slide-dots, .sdot').forEach(el => {
                el.style.setProperty('display', 'none', 'important');
                el.style.visibility = 'hidden';
            });
        },

        _showHeaderAndTap() {
            const header = this._elements.signageHeader;
            if (header) {
                header.style.setProperty('display', 'flex', 'important');
                header.style.position = 'relative';
                header.style.zIndex = '2';
                header.style.visibility = 'visible';
            }
            const tap = this._elements.tapPrompt;
            if (tap) {
                tap.style.setProperty('display', 'block', 'important');
                tap.style.position = 'relative';
                tap.style.zIndex = '2';
                tap.style.visibility = 'visible';
            }
        },

        // ──────────────────────────────────────────────
        // HANDLER EVENT WEBSOCKET
        // ──────────────────────────────────────────────

        handleSignageUpdate(data) {
            console.log('[Signage] Received signage_update:', data);
            if (data && data.length > 0) {
                this._backendSlides = data;
                this._applyMediaSlides();
            } else {
                this._backendSlides = [];
                this._disableMediaMode();
                this.start();
            }
        },

        handleConfigUpdate(config) {
            console.log('[Signage] Received config_update:', config);
            if (config) {
                if (config.slide_duration_ms) {
                    this._duration = parseInt(config.slide_duration_ms);
                    if (this._isImageMode) {
                        // Jadwalkan ulang slide gambar yang sedang tampil dengan durasi baru
                        clearTimeout(this._slideTimer);
                        this._slideTimer = setTimeout(() => this._advancePlaylist(), this._duration);
                    } else if (!this._isVideoMode) {
                        this.restart();
                    }
                }
                if (config.signage_enabled !== undefined) {
                    const enabled = parseInt(config.signage_enabled) !== 0;
                    if (!enabled) {
                        this._disableMediaMode();
                        this.start();
                    } else {
                        // Refresh slides
                        this._fetchSlides();
                    }
                }
                // Update admin read-only
                this._updateAdminConfig(config);
            }
        },

        // ──────────────────────────────────────────────
        // UPDATE ADMIN READ-ONLY CONFIG
        // ──────────────────────────────────────────────

        _updateAdminConfig(config) {
            // Update elemen di halaman admin (read-only)
            if (!config) {
                // Ambil dari AppState jika ada
                if (typeof AppState !== 'undefined') {
                    const price = AppState.pricePerLiter || 500;
                    const timeout = AppState.standbyTimeout || 30;
                    const signage = AppState.signageEnabled !== undefined ? AppState.signageEnabled : 1;
                    this._setAdminDisplay(price, timeout, signage);
                }
                return;
            }
            const price = config.price_per_liter || 500;
            const timeout = config.standby_timeout_sec || 30;
            const signage = config.signage_enabled !== undefined ? config.signage_enabled : 1;
            this._setAdminDisplay(price, timeout, signage);
        },

        _setAdminDisplay(price, timeout, signage) {
            const priceEl = document.getElementById('adminCurrentPrice');
            if (priceEl) priceEl.textContent = 'Rp ' + Number(price).toLocaleString('id-ID');
            const timeoutEl = document.getElementById('adminCurrentTimeout');
            if (timeoutEl) {
                const t = Number(timeout);
                timeoutEl.textContent = t < 60 ? t + ' detik' : (t/60) + ' menit';
            }
            const signageEl = document.getElementById('adminCurrentSignage');
            if (signageEl) {
                signageEl.textContent = signage ? '✅ Aktif' : '❌ Nonaktif';
            }
        },

        // ──────────────────────────────────────────────
        // VIDEO UPLOAD (dari kiosk — sudah dihapus, tapi biarkan sebagai fallback)
        // ──────────────────────────────────────────────

        handleVideoUpload(file) {
            if (!file) return;
            if (!file.type.startsWith('video/')) {
                showToast('Hanya file video yang didukung (MP4)');
                return;
            }
            if (file.size > 500 * 1024 * 1024) {
                showToast('File terlalu besar (max 500MB)');
                return;
            }
            const url = URL.createObjectURL(file);
            this._enableVideoMode(url);
            showToast('Video promosi berhasil diperbarui (sementara)');
        },

        // ──────────────────────────────────────────────
        // RESET SIGNAGE (dari admin kiosk — fallback)
        // ──────────────────────────────────────────────

        resetSignage() {
            this._disableMediaMode();
            this._backendSlides = [];
            const videoInput = document.getElementById('videoInput');
            if (videoInput) videoInput.value = '';
            this.reset();
            this.start();
            if (typeof showToast === 'function') {
                showToast('✓ Signage direset ke default');
            }
            console.log('[Signage] Reset to default');
        }
    };

    // Ekspos ke global
    window.SignageUI = SignageUI;

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            if (window.SignageUI && window.SignageUI.init) {
                window.SignageUI.init();
            }
        });
    } else {
        if (window.SignageUI && window.SignageUI.init) {
            window.SignageUI.init();
        }
    }

    console.log('[SignageUI] Module loaded');
})();