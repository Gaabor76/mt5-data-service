@echo off
echo ============================================
echo   MT5 Data Service - Setup
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.11+ from python.org
    echo         Make sure to check "Add to PATH" during installation.
    pause
    exit /b 1
)

echo [OK] Python found.

REM Create virtual environment
if not exist "venv" (
    echo [..] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment exists.
)

REM Activate and install dependencies
echo [..] Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo [OK] Dependencies installed.

REM Create .env if it doesn't exist
if not exist ".env" (
    echo.
    echo [!!] .env file not found. Creating from template...
    copy .env.example .env
    echo [!!] IMPORTANT: Edit .env with your settings before starting!
    echo     - Set DATABASE_URL to your NAS PostgreSQL connection
    echo     - Generate ENCRYPTION_KEY (see .env.example for instructions)
    echo     - Set CORS_ORIGINS to your TradeLog URL
    echo     - Set MT5_TERMINAL_PATH to your MT5 installation
    echo.
    notepad .env
)

echo.
echo ============================================
echo   Setup complete!
echo   Run 'start.bat' to start the service.
echo ============================================
pause
