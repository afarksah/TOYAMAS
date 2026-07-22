
```
toyamas-dispenser-v4.7.6.2
├─ backend
│  ├─ .env
│  ├─ config
│  │  ├─ settings.py
│  │  └─ __pycache__
│  │     └─ settings.cpython-313.pyc
│  ├─ create_admin.py
│  ├─ database
│  │  └─ toyamas_local.db
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
│  │  ├─ auth.py
│  │  └─ __pycache__
│  │     └─ auth.cpython-313.pyc
│  ├─ routes
│  │  ├─ auth.py
│  │  ├─ hardware.py
│  │  ├─ iot.py
│  │  ├─ iot_settings.py
│  │  ├─ payment.py
│  │  ├─ ticket.py
│  │  ├─ websocket.py
│  │  └─ __pycache__
│  │     ├─ auth.cpython-313.pyc
│  │     ├─ hardware.cpython-313.pyc
│  │     ├─ iot.cpython-313.pyc
│  │     ├─ iot_settings.cpython-313.pyc
│  │     ├─ payment.cpython-313.pyc
│  │     ├─ ticket.cpython-313.pyc
│  │     └─ websocket.cpython-313.pyc
│  ├─ services
│  │  ├─ database.py
│  │  ├─ mqtt_bridge.py
│  │  └─ __pycache__
│  │     ├─ database.cpython-313.pyc
│  │     └─ mqtt_bridge.cpython-313.pyc
│  ├─ uploads
│  │  └─ signage
│  │     ├─ TYM-001
│  │     ├─ TYM-002
│  │     └─ TYM-003
│  ├─ xendit_simulate_scan.py
│  ├─ xendit_ticket_sim.py
│  ├─ xendit_webhook_sim.py
│  └─ __pycache__
│     └─ main.cpython-313.pyc
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
│  │  └─ 010_migrate_to_xendit.sql
│  └─ schema_cloudflare_d1.sql
├─ PANDUAN_UPDATE_FIRMWARE_TOYAMAS.md
├─ PAYLOAD_SPEC.md
├─ requirements.txt
├─ SETUP_GUIDE.md
├─ struktur_folder.txt
└─ toyamas_mqtt_simulator_Mesin.py

```