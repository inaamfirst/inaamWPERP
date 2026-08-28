from __future__ import annotations

from types import SimpleNamespace

from erp.packages.core import production_services


def test_windows_acl_inspection_failure_fails_closed(
    monkeypatch,
    tmp_path,
) -> None:
    config_file = tmp_path / "production.env"
    config_file.write_text("ERP_SECRET_KEY=not-a-real-secret\n", encoding="utf-8")
    monkeypatch.setenv("ERP_CONFIG_FILE", str(config_file))
    monkeypatch.setattr(production_services.os, "name", "nt")
    monkeypatch.setattr(
        production_services.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="denied"),
    )

    check = production_services._env_file_check()

    assert check.name == "environment_file_permissions"
    assert check.required is True
    assert check.ok is False
    assert "icacls exited 1" in check.detail
