# Reuse Report

Phase 0 found multiple reusable projects under `C:\Users\User\Documents`. Old
projects are source material only. They must not be copied wholesale into this
repository.

| Project | Purpose | Technology | Reusable Parts | Risk | Recommendation |
|---|---|---|---|---|---|
| `Mobile shop software/Inaam Warehouse` | Warehouse/shop desktop system | Python, FastAPI, PySide6, SQLAlchemy, Alembic, pytest | Backend layering, RBAC, licensing, desktop API client, offline warning/store, sync helpers, tests | Specific 1 warehouse/3 shops assumptions, runtime files, possible secrets | Primary reference for patterns |
| `Shoes Shop Store/Inaam Footware Software` | Footwear retail system | Python, FastAPI, PySide6, Alembic, barcode/QR, packaging | Retail flows, barcode/QR, packaging, peer sync ideas | Footwear-specific assumptions, runtime files | Secondary reference |
| `Whatsapp Fro V9` | WhatsApp automation | Node.js, whatsapp-web.js, local HTTP server | Local status/API endpoints, QR/pairing, campaign controls | Unofficial WhatsApp automation and sensitive auth cache | Integrate through adapter only |
| `Inaam's Restaurant Management System` | Restaurant POS | FastAPI, SQLite, React, Electron | LAN operation, backup/restore, local queue, release process | Seeded users and restaurant-specific design | Reuse operational ideas |
| `ChoiceOye Theme etc` | WooCommerce storefront | WordPress, PHP, WooCommerce, JS/CSS | WooCommerce attributes/meta and import tooling | Storefront code is not ERP connector code | Use for mapping knowledge |
| `Ai Talking cs Chatbot` | AI kiosk/chatbot | FastAPI, Gemini, Android/deploy scripts | Future AI/mobile/deploy patterns | Not V1 and contains runtime data | Defer to V3 |

This Phase 1 scaffold uses patterns from the Python projects but copies no old
code, secrets, databases, auth caches, or release artifacts.

## Prompt 6 WhatsApp Reuse Note

Additional read-only inspection found:

- `C:\Users\User\Documents\Whatsapp Fro`
- `Mobile shop software/Inaam Warehouse/src/inaam_backend/services/whatsapp_service.py`
- `Mobile shop software/Inaam Warehouse/src/inaam_desktop_shared/whatsapp_runtime.py`
- `Mobile shop software/Inaam Warehouse/src/inaam_desktop_shared/whatsapp_startup.py`

Reusable idea: keep a local adapter/dashboard boundary with runtime health,
startup settings, and queue status. Risk: old projects contain unofficial
WhatsApp automation, auth caches, installers, and runtime state. Recommendation:
do not copy old code; integrate later through a narrow local adapter after
explicit approval.
