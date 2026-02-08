#!/usr/bin/env python3
"""
check_env.py - Verify all dependencies are correct

Run this FIRST before running the bot!

Usage:
    python check_env.py
"""

import sys

def main():
    print("=" * 60)
    print("Trading Bot Environment Check")
    print("=" * 60)
    print()
    
    errors = []
    warnings = []
    
    # Check Python version
    py_version = sys.version_info
    print(f"Python: {py_version.major}.{py_version.minor}.{py_version.micro}")
    if py_version.major < 3 or (py_version.major == 3 and py_version.minor < 9):
        errors.append("Python 3.9+ required")
    
    # Check numpy
    try:
        import numpy as np
        print(f"✓ numpy: {np.__version__}")
    except ImportError:
        print("✗ numpy: NOT INSTALLED")
        errors.append("numpy not installed")
    
    # Check pandas
    try:
        import pandas as pd
        print(f"✓ pandas: {pd.__version__}")
    except ImportError:
        print("✗ pandas: NOT INSTALLED")
        errors.append("pandas not installed")
    except Exception as e:
        print(f"✗ pandas: ERROR - {e}")
        errors.append(f"pandas error: {e}")
    
    # Check requests
    try:
        import requests
        print(f"✓ requests: {requests.__version__}")
    except ImportError:
        print("✗ requests: NOT INSTALLED")
        errors.append("requests not installed")
    
    # Check lxml
    try:
        import lxml
        print(f"✓ lxml: {lxml.__version__}")
    except ImportError:
        print("⚠ lxml: NOT INSTALLED (optional)")
        warnings.append("lxml not installed (some features disabled)")
    
    # Check pytz
    try:
        import pytz
        print(f"✓ pytz: installed")
    except ImportError:
        print("✗ pytz: NOT INSTALLED")
        errors.append("pytz not installed")
    
    # Check pymongo (optional)
    try:
        import pymongo
        print(f"✓ pymongo: {pymongo.__version__}")
    except ImportError:
        print("⚠ pymongo: NOT INSTALLED (optional)")
        warnings.append("pymongo not installed (using file storage)")
    
    # Check python-dotenv
    try:
        import dotenv
        print(f"✓ python-dotenv: installed")
    except ImportError:
        print("✗ python-dotenv: NOT INSTALLED")
        errors.append("python-dotenv not installed")
    
    # Test Yahoo Finance API (chart endpoint - no crumb needed)
    print()
    print("Testing Yahoo Finance API...")
    try:
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        resp = session.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            params={"range": "1d", "interval": "5m"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            price = data.get("chart", {}).get("result", [{}])[0].get("meta", {}).get("regularMarketPrice")
            if price:
                print(f"✓ Yahoo Finance API: AAPL ${price:.2f}")
            else:
                print("⚠ Yahoo Finance API: Connected but no price data")
        else:
            print(f"⚠ Yahoo Finance API: HTTP {resp.status_code}")
            warnings.append("Yahoo Finance API returned non-200 status")
    except Exception as e:
        print(f"⚠ Yahoo Finance API: {str(e)[:60]}")
        warnings.append("Yahoo Finance API not reachable (check internet)")
    
    print()
    
    # Summary
    if errors:
        print("=" * 60)
        print("❌ ERRORS FOUND - Bot will NOT work!")
        print("=" * 60)
        for e in errors:
            print(f"  • {e}")
        print()
        print("FIX: Run this command:")
        print("  pip install -r requirements.txt")
        print("=" * 60)
        return 1
    
    if warnings:
        print("⚠ Warnings:")
        for w in warnings:
            print(f"  • {w}")
        print()
    
    print("=" * 60)
    print("✅ All dependencies OK!")
    print("=" * 60)
    print()
    print("Next: Run the bot with:")
    print("  python main.py --test")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
