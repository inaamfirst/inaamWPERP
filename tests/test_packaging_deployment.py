from __future__ import annotations

from pathlib import Path


def test_packaging_assets_are_present_and_tracked_by_policy() -> None:
    required_files = [
        Path("deploy/pyinstaller/erp-api.spec"),
        Path("erp/apps/api/static/web.css"),
        Path("deploy/pyinstaller/erp-worker.spec"),
        Path("deploy/pyinstaller/erp-desktop.spec"),
        Path("deploy/inno/installer.iss"),
        Path("deploy/inno/README.md"),
        Path("deploy/pythonanywhere/README.md"),
        Path("deploy/pythonanywhere/asgi_command.txt"),
        Path("deploy/pythonanywhere/env.production.example"),
        Path("deploy/pythonanywhere/migrate.sh"),
        Path("deploy/pythonanywhere/run_asgi.sh"),
        Path("deploy/pythonanywhere/run_worker.sh"),
        Path("deploy/windows/env.production.example"),
        Path("deploy/windows/start_api.ps1"),
        Path("deploy/windows/start_worker.ps1"),
        Path("deploy/windows/start_desktop.ps1"),
        Path("deploy/windows/migrate_database.ps1"),
        Path("deploy/windows/preflight_production.ps1"),
        Path("deploy/windows/install_managed_tasks.ps1"),
        Path("deploy/windows/uninstall_managed_tasks.ps1"),
        Path("scripts/preflight_production.ps1"),
        Path("RUN_ON_PC_OFFLINE/1_FIRST_TIME_SETUP.bat"),
        Path("RUN_ON_PC_OFFLINE/2_RUN_ERP_OFFLINE.bat"),
        Path("RUN_ON_PC_OFFLINE/3_RUN_API_ONLY.bat"),
        Path("RUN_ON_PC_OFFLINE/4_RUN_DESKTOP_ONLY.bat"),
        Path("RUN_ON_PC_OFFLINE/offline.env.example"),
        Path("RUN_ON_PC_OFFLINE/setup_offline.ps1"),
        Path("RUN_ON_PC_OFFLINE/run_erp_offline.ps1"),
        Path("UPLOAD_TO_PYTHONANYWHERE/CREATE_PYTHONANYWHERE_UPLOAD_ZIP.bat"),
        Path("UPLOAD_TO_PYTHONANYWHERE/README.md"),
        Path("UPLOAD_TO_PYTHONANYWHERE/pythonanywhere.env.example"),
        Path("UPLOAD_TO_PYTHONANYWHERE/run_asgi.sh"),
        Path("UPLOAD_TO_PYTHONANYWHERE/migrate.sh"),
        Path("UPLOAD_TO_PYTHONANYWHERE/run_worker.sh"),
        Path("UPLOAD_TO_PYTHONANYWHERE/create_pythonanywhere_upload_zip.ps1"),
        Path("scripts/build_package.ps1"),
        Path("scripts/build_installer.ps1"),
        Path("scripts/stop_erp.ps1"),
        Path("scripts/run_pc_local.ps1"),
        Path("scripts/smoke_package.ps1"),
        Path("scripts/backup_postgres.ps1"),
        Path("scripts/restore_postgres.ps1"),
        Path("docs/production_deployment.md"),
        Path("docs/pc_and_cloud_deployment.md"),
        Path("docs/production_monitoring_runbook.md"),
        Path("docs/postgresql_backup_restore.md"),
        Path("docs/v3_expansion_plan.md"),
    ]

    missing = [str(path) for path in required_files if not path.exists()]
    assert missing == []

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "*.spec" in gitignore
    assert "!deploy/pyinstaller/*.spec" in gitignore
    assert "release_builds/" in gitignore

    installer = Path("deploy/inno/installer.iss").read_text(encoding="utf-8")
    assert "release_builds\\dist\\erp-api" in installer
    assert "release_builds\\dist\\*.ps1" in installer
    assert "production.env.example" in installer
    assert "migrate_database.ps1" in installer
    assert "[UninstallRun]" in installer
    assert "\n[Run]" not in installer
    assert "SignTool" in installer

    api_spec = Path("deploy/pyinstaller/erp-api.spec").read_text(encoding="utf-8")
    assert '"erp/apps/api/static"' in api_spec

    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"erp.apps.api" = ["static/*.css"]' in pyproject

    asgi_command = Path("deploy/pythonanywhere/asgi_command.txt").read_text(encoding="utf-8")
    assert "run_asgi.sh" in asgi_command

    offline_readme = Path("RUN_ON_PC_OFFLINE/README.md").read_text(encoding="utf-8")
    assert "2_RUN_ERP_OFFLINE.bat" in offline_readme

    upload_readme = Path("UPLOAD_TO_PYTHONANYWHERE/README.md").read_text(encoding="utf-8")
    assert "CREATE_PYTHONANYWHERE_UPLOAD_ZIP.bat" in upload_readme


def test_production_templates_do_not_ship_real_secrets() -> None:
    template = Path("deploy/windows/env.production.example").read_text(encoding="utf-8")
    assert "ERP_ENV=production" in template
    assert "ERP_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET" in template
    assert "ERP_API_BASE_URL=https://erp.example.com" in template
    assert "ERP_LICENSE_OFFLINE_SIGNING_KEY=CHANGE_ME_TO_OFFLINE_LICENSE_SIGNING_KEY" in template
    assert "ERP_LICENSE_SERVER_ADMIN_KEY=CHANGE_ME_TO_LICENSE_ADMIN_KEY" in template
    assert "ERP_TRUSTED_HOSTS=[\"erp.example.com\"]" in template
    assert "ERP_FORCE_HTTPS=true" in template
    assert "ERP_WORKER_LOOP=true" in template
    assert "ERP_WORKER_HEARTBEAT_FILE=" in template
    assert "dev-only-change-me" not in template


    migration_launcher = Path("deploy/windows/migrate_database.ps1").read_text(encoding="utf-8")
    assert "ERP_MIGRATE_ONLY" in migration_launcher

    package_smoke = Path("scripts/smoke_package.ps1").read_text(encoding="utf-8")
    assert "migrate_database.ps1" in package_smoke
    assert "ERP_DESKTOP_SMOKE" in package_smoke
    assert "Start-Process -FilePath $apiExe" in package_smoke
    assert "worker_heartbeat.json" in package_smoke
    assert "SkipRuntimeSmoke" in package_smoke
    assert "[IO.Path]::IsPathRooted($DistPath)" in package_smoke

    package_builder = Path("scripts/build_package.ps1").read_text(encoding="utf-8")
    assert "backup_postgres.ps1" in package_builder
    assert "restore_postgres.ps1" in package_builder

    backup_script = Path("scripts/backup_postgres.ps1").read_text(encoding="utf-8")
    restore_script = Path("scripts/restore_postgres.ps1").read_text(encoding="utf-8")
    assert "PGPASSWORD" not in backup_script
    assert "PGPASSWORD" not in restore_script
    assert "-ConfirmRestore" in restore_script

    installer_script = Path("scripts/build_installer.ps1").read_text(encoding="utf-8")
    assert ".wwebjs_auth" in installer_script
    assert ".env" in installer_script
    assert "ISCC.exe" in installer_script

    pythonanywhere_template = Path("deploy/pythonanywhere/env.production.example").read_text(
        encoding="utf-8"
    )
    assert "YOURUSERNAME.pythonanywhere.com" in pythonanywhere_template
    assert "dev-only-change-me" not in pythonanywhere_template
    assert "ERP_DATABASE_URL=postgresql+psycopg://" in pythonanywhere_template

    run_asgi = Path("deploy/pythonanywhere/run_asgi.sh").read_text(encoding="utf-8")
    assert "--uds \"${DOMAIN_SOCKET}\"" in run_asgi
    assert "cd \"$PROJECT_DIR\"" in run_asgi

    offline_template = Path("RUN_ON_PC_OFFLINE/offline.env.example").read_text(encoding="utf-8")
    assert "ERP_DATABASE_URL=sqlite:///./runtime_data/local_offline_erp.db" in offline_template
    assert "ERP_API_BASE_URL=" in offline_template

    upload_template = Path("UPLOAD_TO_PYTHONANYWHERE/pythonanywhere.env.example").read_text(
        encoding="utf-8"
    )
    assert "YOURUSERNAME.pythonanywhere.com" in upload_template
    assert "dev-only-change-me" not in upload_template

    upload_zip_script = Path(
        "UPLOAD_TO_PYTHONANYWHERE/create_pythonanywhere_upload_zip.ps1"
    ).read_text(encoding="utf-8")
    assert "Forbidden file(s)" in upload_zip_script
    assert ".wwebjs_auth" in upload_zip_script
    assert "Compress-Archive" in upload_zip_script


def test_linux_staging_environment_values_are_shell_and_systemd_safe() -> None:
    installer = Path("deploy/linux/setup_staging.sh").read_text(encoding="utf-8")

    assert "REPO_REF=\"${REPO_REF:-7e8e5f9}\"" in installer
    assert "ERP_APP_NAME='Enterprise Commerce ERP'" in installer
    assert "ERP_TRUSTED_HOSTS='[\"$ERP_HOSTNAME\"]'" in installer
    assert "ERP_TRUSTED_PROXY_IPS='[\"127.0.0.1\",\"::1\"]'" in installer
    assert "ERP_CORS_ORIGINS='[]'" in installer
    assert Path("deploy/linux/recover_staging_login.sh").exists()


def test_ci_runs_local_quality_gate_and_packaging_smoke() -> None:
    workflow = Path(".github/workflows/checks.yml").read_text(encoding="utf-8")
    assert ".\\scripts\\check.ps1" in workflow
    assert "Packaging config smoke" in workflow
    assert "Package integration smoke" in workflow
    assert ".\\scripts\\build_package.ps1 -SkipChecks" in workflow
    assert "deploy\\inno\\installer.iss" in workflow
    assert "  frontend:" in workflow
    assert "npm ci" in workflow
    assert "npm run lint" in workflow
    assert "npm run build" in workflow


def test_powershell_scripts_support_explicit_python_interpreter() -> None:
    scripts = [
        Path("scripts/check.ps1"),
        Path("scripts/install_dev.ps1"),
        Path("scripts/test.ps1"),
        Path("scripts/run_api.ps1"),
        Path("scripts/run_desktop.ps1"),
        Path("scripts/run_license_server.ps1"),
        Path("scripts/run_pc_local.ps1"),
        Path("scripts/migrate.ps1"),
        Path("scripts/build_package.ps1"),
    ]

    for script in scripts:
        content = script.read_text(encoding="utf-8")
        assert "$env:ERP_PYTHON" in content
        assert "& $Python" in content


def test_root_batch_launchers_expose_stop_action() -> None:
    run_batch = Path("RUN_ERP.bat").read_text(encoding="utf-8")
    stop_batch = Path("STOP_ERP.bat").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    run_api = Path("scripts/run_api.ps1").read_text(encoding="utf-8")
    run_local = Path("scripts/run_pc_local.ps1").read_text(encoding="utf-8")
    stop_script = Path("scripts/stop_erp.ps1").read_text(encoding="utf-8")

    assert '"stop"' in run_batch
    assert "STOP_ERP.bat" in run_batch
    assert "Startup failed with exit code" in run_batch
    assert "stop_erp.ps1" in stop_batch
    assert "run_(pc_local|api|desktop)\\.ps1" in stop_script
    assert "Get-DescendantProcessIds" in stop_script
    assert 'Join-Path $PSScriptRoot "migrate.ps1"' in run_api
    assert 'Join-Path $PSScriptRoot "migrate.ps1"' in run_local
    assert 'Join-Path $PSScriptRoot "stop_erp.ps1"' in run_local
    assert 'ERP_START_WORKER -eq "1"' in run_local
    assert "ERP_WORKER_LOOP='true'" in run_local
    assert "ERP_WORKER_POLL_SECONDS='5'" in run_local
    assert "Wait-ForApiReady -Url $healthUrl" in run_local
    assert "`stop`" in readme
    assert "ERP_START_WORKER=0" in readme
    assert 'Ensure-PythonModule -ModuleName "multipart"' in run_api
    assert 'Ensure-PythonModule -ModuleName "multipart"' in run_local
    assert 'set "ERP_PYTHON=%ROOT_DIR%\\.venv\\Scripts\\python.exe"' in run_batch
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in run_api
    assert 'Join-Path $repoRoot ".venv\\Scripts\\python.exe"' in run_local
