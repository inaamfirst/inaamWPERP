from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings.

    Production must provide a real secret. Development defaults are intentionally
    non-secret and safe to commit.
    """

    model_config = SettingsConfigDict(
        env_prefix="ERP_",
        env_file=os.environ.get("ERP_CONFIG_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Enterprise Commerce ERP"
    env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = "/api/v1"
    api_base_url: str = ""
    database_url: str = "postgresql+psycopg://erp:erp@localhost:5432/enterprise_commerce_erp"
    local_sqlite_url: str = "sqlite:///./runtime_data/local_cache.db"
    secret_key: str = "dev-only-change-me"
    bootstrap_token: str = ""
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    access_token_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    refresh_token_ttl_hours: int = Field(default=24, ge=1, le=720)
    remember_me_ttl_days: int = Field(default=30, ge=1, le=90)
    action_token_ttl_minutes: int = Field(default=60, ge=5, le=1440)
    login_attempt_limit: int = Field(default=5, ge=2, le=100)
    login_attempt_window_minutes: int = Field(default=15, ge=1, le=1440)
    login_block_minutes: int = Field(default=15, ge=1, le=1440)
    auth_record_retention_days: int = Field(default=90, ge=7, le=3650)
    auth_throttle_retention_days: int = Field(default=30, ge=1, le=365)
    allow_negative_vendor_stock: bool = False
    base_currency: str = Field(default="PKR", min_length=3, max_length=3)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    log_level: str = "INFO"
    log_dir: str = "runtime_data/logs"
    log_max_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024)
    log_backup_count: int = Field(default=5, ge=1, le=50)
    license_server_url: str = ""
    license_server_admin_key: str = "dev-license-admin-key"
    license_offline_signing_key: str = "dev-offline-license-signing-key"
    license_device_id: str = "dev-device"
    license_offline_file: str = "runtime_data/license/offline_license.json"
    support_diagnostics_dir: str = "runtime_data/diagnostics"
    media_upload_dir: str = "runtime_data/uploads"
    docs_enabled: bool | None = None
    cors_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])
    force_https: bool = False
    whatsapp_enabled: bool | None = None
    push_enabled: bool = False
    push_vapid_public_key: str = ""
    push_vapid_private_key: str = ""
    push_vapid_subject: str = "mailto:admin@example.com"
    push_ttl_seconds: int = Field(default=300, ge=60, le=86400)
    push_max_attempts: int = Field(default=5, ge=1, le=20)
    push_poll_seconds: int = Field(default=5, ge=1, le=300)
    worker_loop: bool = False
    worker_poll_seconds: int = Field(default=10, ge=5, le=86400)
    worker_heartbeat_file: str = "runtime_data/worker_heartbeat.json"
    postgres_backup_dir: str = "runtime_data/backups"
    trusted_proxy_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])
    max_request_size_mb: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_production_secret(self) -> Settings:
        if self.env.lower() == "production":
            placeholders = (
                "",
                "dev-only-change-me",
                "dev-license-admin-key",
                "dev-offline-license-signing-key",
            )
            for field_name, value in (
                ("ERP_SECRET_KEY", self.secret_key),
                ("ERP_BOOTSTRAP_TOKEN", self.bootstrap_token),
                ("ERP_LICENSE_SERVER_ADMIN_KEY", self.license_server_admin_key),
                ("ERP_LICENSE_OFFLINE_SIGNING_KEY", self.license_offline_signing_key),
            ):
                normalized = value.strip().lower()
                if (
                    normalized in placeholders
                    or "change_me" in normalized
                    or (field_name == "ERP_BOOTSTRAP_TOKEN" and len(value.strip()) < 32)
                ):
                    raise ValueError(
                        f"{field_name} must be set to a non-default secret in production"
                    )
            database_url = self.database_url.strip()
            if not database_url.startswith("postgresql"):
                raise ValueError("ERP_DATABASE_URL must use PostgreSQL in production")
            if "change_me" in database_url.lower() or "erp:erp@" in database_url.lower():
                raise ValueError(
                    "ERP_DATABASE_URL must not use development credentials in production"
                )
            parsed_api_url = urlparse(self.api_base_url.strip())
            if parsed_api_url.scheme != "https" or not parsed_api_url.netloc:
                raise ValueError("ERP_API_BASE_URL must be a public HTTPS URL in production")
            if not self.force_https:
                raise ValueError("ERP_FORCE_HTTPS must be enabled in production")
            if not self.trusted_hosts or "*" in self.trusted_hosts:
                raise ValueError("ERP_TRUSTED_HOSTS must list explicit production hosts")
            if not self.trusted_proxy_ips:
                raise ValueError("ERP_TRUSTED_PROXY_IPS must list the HTTPS reverse proxy")
            if not self.worker_loop:
                raise ValueError("ERP_WORKER_LOOP must be enabled in production")
            if self.push_enabled and (
                not self.push_vapid_public_key.strip()
                or not self.push_vapid_private_key.strip()
                or not self.push_vapid_subject.strip()
            ):
                raise ValueError(
                    "ERP_PUSH_VAPID_PUBLIC_KEY, ERP_PUSH_VAPID_PRIVATE_KEY, and "
                    "ERP_PUSH_VAPID_SUBJECT are required when ERP_PUSH_ENABLED is true"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def effective_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production

    @property
    def effective_whatsapp_enabled(self) -> bool:
        if self.whatsapp_enabled is not None:
            return self.whatsapp_enabled
        return not self.is_production

    @property
    def effective_push_enabled(self) -> bool:
        return bool(
            self.push_enabled
            and self.push_vapid_public_key.strip()
            and self.push_vapid_private_key.strip()
            and self.push_vapid_subject.strip()
        )

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
