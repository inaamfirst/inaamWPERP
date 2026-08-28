from __future__ import annotations

import json
import os
import secrets
import uuid
from pathlib import Path

from erp.apps.desktop.main import main


def package_keyring_smoke() -> str:
    """Round-trip one disposable secret through the packaged OS keyring backend."""

    import keyring

    service = f"choiceoye-packaged-desktop-smoke-{uuid.uuid4().hex}"
    account = "refresh_token"
    value = secrets.token_urlsafe(32)
    written = False
    try:
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:
            raise RuntimeError("A secure operating-system keyring backend is unavailable.")
        keyring.set_password(service, account, value)
        written = True
        if keyring.get_password(service, account) != value:
            raise RuntimeError("The operating-system keyring round-trip failed.")
        return f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    finally:
        if written:
            keyring.delete_password(service, account)


def package_smoke() -> None:
    """Exercise the packaged desktop import path without opening a GUI."""
    from erp.apps.desktop.main import navigation_items

    payload = {
        "status": "ok",
        "navigation_items": list(navigation_items()),
        "keyring_status": "ok",
        "keyring_backend": package_keyring_smoke(),
    }
    marker = os.environ.get("ERP_DESKTOP_SMOKE_FILE", "").strip()
    if marker:
        Path(marker).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    print("Desktop package smoke: " + ", ".join(payload["navigation_items"]))


if __name__ == "__main__":
    if os.environ.get("ERP_DESKTOP_SMOKE") == "1":
        package_smoke()
    else:
        main()
