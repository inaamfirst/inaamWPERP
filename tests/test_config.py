from __future__ import annotations

import pytest
from pydantic import ValidationError

from erp.packages.core.config import Settings
from erp.packages.core.db.session import create_database_engine


def production_settings_kwargs() -> dict[str, object]:
    """Return the minimum safe configuration required by the production profile."""

    return {
        "env": "production",
        "database_url": "postgresql+psycopg://erp_app:strong-password@db.example.test:5432/erp",
        "api_base_url": "https://erp.example.test",
        "secret_key": "real-secret-key",
        "bootstrap_token": "a-separate-production-bootstrap-token-123456",
        "license_server_admin_key": "release-admin-key",
        "license_offline_signing_key": "release-signing-key",
        "trusted_hosts": ["erp.example.test"],
        "trusted_proxy_ips": ["127.0.0.1"],
        "force_https": True,
        "worker_loop": True,
    }


def test_settings_defaults_are_development_safe() -> None:
    settings = Settings()

    assert settings.env == "development"
    assert settings.api_prefix == "/api/v1"
    assert settings.api_base_url == ""
    assert settings.database_configured is True
    assert settings.secret_key == "dev-only-change-me"
    assert settings.effective_docs_enabled is True
    assert settings.effective_whatsapp_enabled is True
    assert settings.max_request_size_mb == 10


@pytest.mark.parametrize("value", [0, -1])
def test_max_request_size_must_be_positive(value: int) -> None:
    with pytest.raises(ValidationError, match="greater than or equal"):
        Settings(max_request_size_mb=value)


def test_production_requires_real_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(**{**production_settings_kwargs(), "secret_key": "dev-only-change-me"})


@pytest.mark.parametrize("bootstrap_token", ["", "too-short", "CHANGE_ME_BOOTSTRAP_TOKEN"])
def test_production_requires_protected_bootstrap_token(bootstrap_token: str) -> None:
    with pytest.raises(ValidationError, match="ERP_BOOTSTRAP_TOKEN"):
        Settings(**{**production_settings_kwargs(), "bootstrap_token": bootstrap_token})


def test_production_requires_real_license_keys() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **{**production_settings_kwargs(), "license_server_admin_key": "dev-license-admin-key"}
        )

    with pytest.raises(ValidationError):
        Settings(
            **{
                **production_settings_kwargs(),
                "license_offline_signing_key": "dev-offline-license-signing-key",
            }
        )

    settings = Settings(**production_settings_kwargs())
    assert settings.is_production is True
    assert settings.effective_docs_enabled is False
    assert settings.effective_whatsapp_enabled is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": "sqlite:///./runtime_data/erp.db"}, "ERP_DATABASE_URL"),
        ({"api_base_url": "http://erp.example.test"}, "ERP_API_BASE_URL"),
        ({"force_https": False}, "ERP_FORCE_HTTPS"),
        ({"trusted_hosts": ["*"]}, "ERP_TRUSTED_HOSTS"),
        ({"trusted_proxy_ips": []}, "ERP_TRUSTED_PROXY_IPS"),
        ({"worker_loop": False}, "ERP_WORKER_LOOP"),
    ],
)
def test_production_requires_deployment_safeguards(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**{**production_settings_kwargs(), **overrides})


def test_sqlite_engine_uses_write_friendly_connect_args() -> None:
    engine = create_database_engine(Settings(database_url="sqlite:///./runtime_data/test.db"))
    assert engine.url.drivername == "sqlite"
    with engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert str(journal_mode).lower() == "wal"
    assert int(foreign_keys) == 1
