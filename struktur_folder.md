
```
toyamas-dispenser-v4.7.6.2
├─ backend
│  ├─ config
│  │  └─ settings.py
│  ├─ create_admin.py
│  ├─ database
│  ├─ frontend
│  │  ├─ assets
│  │  │  └─ logo-toyamas.png
│  │  ├─ css
│  │  │  └─ style.css
│  │  ├─ index.html
│  │  └─ js
│  │     ├─ admin.js
│  │     ├─ api.js
│  │     ├─ app.js
│  │     ├─ clock.js
│  │     ├─ filling.js
│  │     ├─ galon.js
│  │     ├─ signage.js
│  │     ├─ state.js
│  │     ├─ ticket.js
│  │     └─ vendor_qrcode.js
│  ├─ generate_fake_tickets.py
│  ├─ iot
│  │  ├─ assets
│  │  │  └─ logo-toyamas.png
│  │  ├─ css
│  │  │  └─ dashboard.css
│  │  ├─ index.html
│  │  └─ js
│  │     ├─ app.js
│  │     ├─ auth.js
│  │     ├─ charts.js
│  │     ├─ location.js
│  │     ├─ transactions.js
│  │     └─ websocket.js
│  ├─ main.py
│  ├─ middleware
│  │  └─ auth.py
│  ├─ routes
│  │  ├─ auth.py
│  │  ├─ hardware.py
│  │  ├─ iot.py
│  │  ├─ iot_settings.py
│  │  ├─ payment.py
│  │  ├─ ticket.py
│  │  └─ websocket.py
│  ├─ services
│  │  ├─ database.py
│  │  └─ mqtt_bridge.py
│  ├─ xendit_simulate_scan.py
│  ├─ xendit_ticket_sim.py
│  └─ xendit_webhook_sim.py
├─ CHANGELOG_MULTI_MESIN.md
├─ database
│  ├─ 001_init.sql
│  ├─ migrations
│  │  ├─ 002_add_location.sql
│  │  ├─ 003_add_hourly_sales.sql
│  │  ├─ 004_add_admins.sql
│  │  ├─ 005_fix_sales_hourly_timezone.sql
│  │  ├─ 006_add_machine_secret.sql
│  │  ├─ 007_add_machine_soft_delete.sql
│  │  ├─ 008_add_signage_slides.sql
│  │  ├─ 009_add_app_config.sql
│  │  ├─ 010_migrate_to_xendit.sql
│  │  └─ 011_add_app_tickets.sql
│  └─ schema_cloudflare_d1.sql
├─ PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md
├─ PAYLOAD_SPEC.md
├─ requirements.txt
├─ SETUP_GUIDE.md
├─ struktur_folder.md
└─ toyamas_mqtt_simulator_Mesin.py

```