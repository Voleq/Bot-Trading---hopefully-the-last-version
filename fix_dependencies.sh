#!/bin/bash
# fix_dependencies.sh - Fix numpy/pandas compatibility
# 
# ERROR: "module 'numpy' has no attribute '__version__'"
# CAUSE: numpy 2.0 is not compatible with older pandas/yfinance
# FIX: Install numpy 1.26.4

echo "============================================"
echo "Fixing Trading Bot Dependencies"
echo "============================================"
echo ""

# Check if in venv
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Not in virtual environment!"
    echo ""
    echo "Run these commands first:"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Step 1: Uninstalling ALL problematic packages..."
pip uninstall numpy pandas yfinance lxml -y 2>/dev/null

echo ""
echo "Step 2: Clearing pip cache..."
pip cache purge 2>/dev/null || true

echo ""
echo "Step 3: Installing EXACT working versions..."
pip install --no-cache-dir \
    numpy==1.26.4 \
    pandas==2.1.4 \
    yfinance==0.2.40 \
    lxml==5.1.0 \
    python-dotenv==1.0.1 \
    requests==2.31.0 \
    pytz==2024.1 \
    pymongo==4.6.1

echo ""
echo "Step 4: Verifying installation..."
echo ""
python3 << 'EOF'
import sys
try:
    import numpy as np
    import pandas as pd
    import yfinance as yf
    
    print(f"✓ numpy:   {np.__version__}")
    print(f"✓ pandas:  {pd.__version__}")
    print(f"✓ yfinance: {yf.__version__}")
    
    # Quick test
    ticker = yf.Ticker("AAPL")
    hist = ticker.history(period="5d")
    print(f"✓ yfinance working (got {len(hist)} days of AAPL data)")
    
    print("")
    print("✅ ALL DEPENDENCIES WORKING!")
    sys.exit(0)
except Exception as e:
    print(f"❌ FAILED: {e}")
    print("")
    print("Try removing venv and starting fresh:")
    print("  deactivate")
    print("  rm -rf venv")
    print("  python -m venv venv")
    print("  source venv/bin/activate")
    print("  pip install -r requirements.txt")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================"
    echo "Now run: python main.py --test"
    echo "============================================"
fi
