@echo off
:: Activate Python virtual environment and run AppTradingView.py
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

echo Running AppTradingView.py...
python AppTradingView.py

echo Script execution completed.
pause