@echo off
echo Starting backup...

REM Get a reliable timestamp using PowerShell (avoids regional date format errors)
for /f %%I in ('powershell -NoProfile -Command "Get-Date -format yyyyMMdd_HHmm"') do set "datetime=%%I"

REM Define source and destination
set "SOURCE=C:\Users\User\Documents\ChoiceOye\Inaam's Ecommerce ERP"
set "DEST=D:\ChoiceOye_ERP_Backup_%datetime%"

REM Run Robocopy
REM /MIR = Mirror the directory tree
REM /XD = Exclude Directories
REM /XF = Exclude Files
robocopy "%SOURCE%" "%DEST%" /MIR /XD .venv __pycache__ node_modules .git /XF *.pyc *.log *.tmp

echo.
echo Backup completed successfully to: %DEST%
pause