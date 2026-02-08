#!/bin/bash
# fix_dependencies.sh - Install/fix all trading bot dependencies
# Run: bash fix_dependencies.sh

echo "========================================"
echo "TRADING BOT - DEPENDENCY SETUP"
echo "========================================"

cd "$(dirname "$0")"

# Activate or create venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
fi

echo ""
echo "Step 1: Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Step 2: Testing Yahoo Finance API..."
python3 << 'EOF'
import requests
import pandas as pd
import numpy as np

print(f"numpy:    {np.__version__}")
print(f"pandas:   {pd.__version__}")
print(f"requests: {requests.__version__}")
print()

# Test Yahoo Finance direct API
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Get crumb
try:
    session.get("https://fc.yahoo.com", timeout=10, allow_redirects=True)
except:
    pass

resp = session.get(
    "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
    params={"range": "5d", "interval": "1d"},
    timeout=10
)

if resp.status_code == 200:
    data = resp.json()
    result = data.get("chart", {}).get("result", [{}])[0]
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price:
        print(f"✓ AAPL: ${price:.2f}")
    timestamps = result.get("timestamp", [])
    print(f"✓ Got {len(timestamps)} data points")
else:
    print(f"✗ HTTP {resp.status_code}")
EOF

echo ""
echo "========================================"
echo "Done! Run: python check_setup.py"
echo "========================================"
