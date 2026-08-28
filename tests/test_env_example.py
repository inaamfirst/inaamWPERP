from __future__ import annotations

from pathlib import Path

from erp.packages.core.config import Settings


def test_env_example_documents_all_settings() -> None:
    env_example = Path(".env.example")
    keys = {
        line.split("=", 1)[0]
        for line in env_example.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    expected_keys = {f"ERP_{field_name.upper()}" for field_name in Settings.model_fields}

    assert expected_keys <= keys
