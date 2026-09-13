@echo off
setlocal

cd /d "%~dp0"

set "MESSAGE=%~1"
if not defined MESSAGE set /p "MESSAGE=Enter a short deployment message: "
if not defined MESSAGE set "MESSAGE=Deploy latest local ERP changes"

echo Staging application source files only...
git add --all -- . ":(exclude)runtime_data" ":(exclude).pytest_cache" ":(exclude).ruff_cache" ":(exclude)Tree.txt" ":(exclude,glob)**/*.rar"

echo.
echo Files to deploy:
git diff --cached --name-status
echo.

choice /C YN /M "Continue with deployment"
if errorlevel 2 exit /b 0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0scripts\deploy-production.ps1" ^
  -ConfigPath "%~dp0scripts\deploy-production.local.psd1" ^
  -Message "%MESSAGE%"

if errorlevel 1 (
    echo.
    echo DEPLOYMENT FAILED.
    pause
    exit /b 1
)

echo.
echo DEPLOYMENT SUCCEEDED.
echo Open https://erp.choiceoye.com
pause
