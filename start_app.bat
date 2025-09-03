@echo off
:: Activate Python virtual environment and run AppTradingView.py with auto-restart
echo Activating Python environment...

:: Check if virtual environment exists
if not exist .venv (
    echo Virtual environment not found. Creating one...
    python -m venv .venv
    echo Installing dependencies...
    .venv\Scripts\pip install -r requirements.txt
) else (
    echo Virtual environment found.
)

echo Activating virtual environment...
call .venv\Scripts\activate

:restart_loop
echo Starting AppTradingView.py...
python AppTradingView.py

echo.
echo Server stopped. Press any key to restart, or Ctrl+C to exit...
pause >nul
goto restart_loop

echo Script execution completed.