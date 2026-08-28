@echo off
setlocal EnableExtensions

echo Stopping the ERP Application...
:: This calls your existing stop script to terminate processes
call STOP_ERP.bat

echo Waiting for processes to close completely...
:: A 3-second delay ensures the system has enough time to release ports and resources
timeout /t 3 /nobreak >nul

echo Starting the ERP Application...
:: This calls your main run script to launch the local API, worker, and desktop client
call RUN_ERP.bat local

echo Restart sequence initiated.
exit /b 0