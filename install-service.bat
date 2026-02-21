@echo off
echo ============================================
echo   Install MT5 Data Service as Windows Service
echo ============================================
echo.
echo This script installs the service to auto-start with Windows.
echo Requires NSSM (Non-Sucking Service Manager).
echo Download from: https://nssm.cc/download
echo.

REM Check if NSSM is available
nssm version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] NSSM not found in PATH.
    echo         Download from https://nssm.cc/download
    echo         Extract and add to PATH, or place nssm.exe in this folder.
    pause
    exit /b 1
)

set SERVICE_NAME=MT5DataService
set SERVICE_DIR=%~dp0

echo Installing service: %SERVICE_NAME%
echo Working directory: %SERVICE_DIR%
echo.

nssm install %SERVICE_NAME% "%SERVICE_DIR%venv\Scripts\python.exe" "%SERVICE_DIR%run.py"
nssm set %SERVICE_NAME% AppDirectory "%SERVICE_DIR%"
nssm set %SERVICE_NAME% DisplayName "MT5 Data Service"
nssm set %SERVICE_NAME% Description "REST API for downloading historical market data from MetaTrader 5"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%SERVICE_DIR%logs\service.log"
nssm set %SERVICE_NAME% AppStderr "%SERVICE_DIR%logs\service-error.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 10485760

REM Create logs directory
if not exist "%SERVICE_DIR%logs" mkdir "%SERVICE_DIR%logs"

echo.
echo [OK] Service installed.
echo.
echo To start:  nssm start %SERVICE_NAME%
echo To stop:   nssm stop %SERVICE_NAME%
echo To remove: nssm remove %SERVICE_NAME% confirm
echo.
echo Starting service now...
nssm start %SERVICE_NAME%
echo.
pause
