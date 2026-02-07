#!/bin/bash
# fix_dependencies.sh - Fix yfinance with browser session
# Run: bash fix_dependencies.sh

echo "========================================"
echo "TRADING BOT - DEPENDENCY FIX"
echo "========================================"

cd "$(dirname "$0")"

# Activate or create venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
fi

echo ""
echo "Step 1: Uninstalling old packages..."
pip uninstall numpy pandas yfinance requests-cache -y 2>/dev/null

echo ""
echo "Step 2: Installing correct versions..."
pip install "numpy<2.0.0"
pip install "pandas>=2.0.0"
pip install "yfinance>=0.2.54"
pip install "requests-cache>=1.2.0"
pip install python-dotenv requests pytz lxml pymongo

echo ""
echo "Step 3: Testing..."
python3 << 'EOF'
import yfinance as yf
import requests_cache
from datetime import timedelta

print(f"yfinance: {yf.__version__}")

# Create session with browser headers
session = requests_cache.CachedSession('yf_cache', expire_after=timedelta(minutes=1))
session.headers['User-Agent'] = 'Mozilla/5.0 Chrome/120.0.0.0'

# Test
ticker = yf.Ticker('AAPL', session=session)
try:
    price = ticker.fast_info.get('lastPrice')
    if price:
        print(f"AAPL: ${price:.2f} ✓")
    else:
        hist = ticker.history(period='5d')
        print(f"AAPL: {len(hist)} rows ✓")
except Exception as e:
    print(f"Error: {e}")

import os
os.remove('yf_cache.sqlite') if os.path.exists('yf_cache.sqlite') else None
EOF

echo ""
echo "========================================"
echo "Done! Run: python check_setup.py"
echo "========================================"
