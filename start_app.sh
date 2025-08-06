#!/bin/bash

# Activate Python virtual environment and run AppTradingView.py
echo "Activating Python environment..."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv .venv
    echo "Installing dependencies..."
    .venv/bin/pip install -r requirements.txt
else
    echo "Virtual environment found."
fi

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Running AppTradingView.py..."
python AppTradingView.py

echo "Script execution completed."
read -p "Press Enter to continue..."