@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul
if errorlevel 1 (
    echo Failed to enter repository root: %ROOT_DIR%
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "ERP_PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"
) else (
    if not defined ERP_PYTHON (
        set "ERP_PYTHON=python"
    )
)

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=local"
set "EXIT_CODE=0"

if /I "%ACTION%"=="local" goto :run_local
if /I "%ACTION%"=="lan" goto :run_lan
if /I "%ACTION%"=="api" goto :run_api
if /I "%ACTION%"=="desktop" goto :run_desktop
if /I "%ACTION%"=="stop" goto :run_stop
if /I "%ACTION%"=="tests" goto :run_tests
if /I "%ACTION%"=="check" goto :run_check
if /I "%ACTION%"=="migrate" goto :run_migrate
if /I "%ACTION%"=="help" goto :show_help
goto :show_help

:run_local
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_pc_local.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_lan
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_pc_lan.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_api
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_api.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_desktop
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_desktop.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_stop
call ".\STOP_ERP.bat"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_tests
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_check
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\check.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:run_migrate
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\migrate.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:show_help
echo Usage: %~nx0 [local^|lan^|api^|desktop^|stop^|tests^|check^|migrate]
echo.
echo Default: local
echo   local    Start API, worker, and desktop.
echo   lan      Start API on 0.0.0.0, worker, and desktop for same-Wi-Fi access.
echo   api      Start the FastAPI server only.
echo   desktop  Start the desktop client only.
echo   stop     Stop the local ERP API, worker, and desktop processes.
echo   tests    Run pytest.
echo   check    Run ruff, pytest, startup checks, and migration smoke test.
echo   migrate  Apply Alembic migrations.
set "EXIT_CODE=1"

:done
if not "%EXIT_CODE%"=="0" (
    if "%~1"=="" (
        echo.
        echo Startup failed with exit code %EXIT_CODE%.
        echo Review the error above, then press any key to close this window.
        pause >nul
    )
)
popd >nul
exit /b %EXIT_CODE%
