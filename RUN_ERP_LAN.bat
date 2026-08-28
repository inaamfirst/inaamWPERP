@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul
if errorlevel 1 (
    echo Failed to enter repository root: %ROOT_DIR%
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\run_pc_lan.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo LAN startup failed with exit code %EXIT_CODE%.
    echo Review the error above, then press any key to close this window.
    pause >nul
)

popd >nul
exit /b %EXIT_CODE%
