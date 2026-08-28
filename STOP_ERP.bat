@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%scripts\stop_erp.ps1"
exit /b %ERRORLEVEL%
