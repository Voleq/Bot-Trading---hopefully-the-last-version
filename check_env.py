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
    
    # Check numpy (CRITICAL - must be <2.0)
    try:
        import numpy as np
        np_version = np.__version__
        np_major = int(np_version.split('.')[0])
        
        if np_major >= 2:
            print(f"✗ numpy: {np_version} (MUST BE <2.0)")
            errors.append(f"numpy {np_version} not compatible, need <2.0")
        else:
            print(f"✓ numpy: {np_version}")
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
    
    # Check yfinance
    try:
        import yfinance as yf
        print(f"✓ yfinance: {yf.__version__}")
    except ImportError:
        print("✗ yfinance: NOT INSTALLED")
        errors.append("yfinance not installed")
    except Exception as e:
        print(f"✗ yfinance: ERROR - {e}")
        errors.append(f"yfinance error: {e}")
    
    # Check lxml
    try:
        import lxml
        print(f"✓ lxml: {lxml.__version__}")
    except ImportError:
        print("⚠ lxml: NOT INSTALLED (optional)")
        warnings.append("lxml not installed (some features disabled)")
    
    # Check requests
    try:
        import requests
        print(f"✓ requests: {requests.__version__}")
    except ImportError:
        print("✗ requests: NOT INSTALLED")
        errors.append("requests not installed")
    
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
        print("  bash fix_dependencies.sh")
        print()
        print("Or manually:")
        print("  pip uninstall numpy pandas yfinance -y")
        print("  pip install numpy==1.26.4 pandas==2.1.4 yfinance==0.2.40 lxml==5.1.0")
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
