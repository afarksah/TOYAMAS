-- Migration 008: tabel slide signage per mesin
-- Media: gambar (image) atau video (video) untuk ditampilkan sebagai background slideshow di kiosk

CREATE TABLE IF NOT EXISTS machine_signage_slides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id  TEXT NOT NULL,
    slide_order INTEGER NOT NULL DEFAULT 0,
    media_type  TEXT NOT NULL CHECK(media_type IN ('image','video')),
    file_path   TEXT NOT NULL,          -- path relatif terhadap folder uploads/signage/
    caption     TEXT,                   -- teks overlay opsional
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id) ON DELETE CASCADE
);

CREATE INDEX idx_signage_slides_machine ON machine_signage_slides(machine_id);
CREATE INDEX idx_signage_slides_order   ON machine_signage_slides(machine_id, slide_order);