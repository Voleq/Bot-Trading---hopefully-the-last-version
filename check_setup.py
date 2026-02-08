#!/usr/bin/env python3
"""
check_setup.py - Verify all dependencies are correctly installed

Run this BEFORE running the bot:
    python check_setup.py

This will check:
1. Python version
2. All required packages and versions
3. API connectivity
4. Basic functionality
"""

import sys

def check_python_version():
    """Check Python version."""
    print("1. Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"   ✗ Python 3.9+ required, got {version.major}.{version.minor}")
        return False
    print(f"   ✓ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_numpy():
    """Check numpy is installed."""
    print("\n2. Checking numpy...")
    try:
        import numpy as np
        version = np.__version__
        print(f"   ✓ numpy {version}")
        return True
    except ImportError:
        print("   ✗ numpy not installed")
        print("   Run: pip install numpy")
        return False
    except Exception as e:
        print(f"   ✗ numpy error: {e}")
        return False


def check_pandas():
    """Check pandas."""
    print("\n3. Checking pandas...")
    try:
        import pandas as pd
        print(f"   ✓ pandas {pd.__version__}")
        return True
    except ImportError:
        print("   ✗ pandas not installed")
        print("   Run: pip install pandas==2.1.4")
        return False
    except Exception as e:
        print(f"   ✗ pandas error: {e}")
        return False


def check_market_data():
    """Check Yahoo Finance API (direct REST, no crumb needed for prices)."""
    print("\n4. Checking Yahoo Finance API...")
    try:
        import requests as req
        
        session = req.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        
        symbols = ['AAPL', 'MSFT', 'SPY']
        success = False
        
        for symbol in symbols:
            try:
                resp = session.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"range": "1d", "interval": "5m"},
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    price = data.get("chart", {}).get("result", [{}])[0].get("meta", {}).get("regularMarketPrice")
                    if price:
                        print(f"   ✓ {symbol}: ${price:.2f}")
                        success = True
                        break
                    else:
                        print(f"   - {symbol}: No price in response")
                else:
                    print(f"   - {symbol}: HTTP {resp.status_code}")
            except Exception as e:
                print(f"   - {symbol}: {str(e)[:40]}")
        
        if success:
            print(f"   ✓ Yahoo Finance API working (chart endpoint, no auth needed)")
            return True
        else:
            print(f"   ⚠ Yahoo Finance not responding")
            return True  # Don't fail setup for temporary issues
        
    except ImportError as e:
        print(f"   ✗ Import error: {e}")
        print("   Run: pip install requests pandas numpy")
        return False
    except Exception as e:
        print(f"   ⚠ Yahoo Finance warning: {e}")
        return True


def check_other_packages():
    """Check other required packages."""
    print("\n5. Checking other packages...")
    
    packages = [
        ("python-dotenv", "dotenv"),
        ("requests", "requests"),
        ("pytz", "pytz"),
        ("lxml", "lxml"),
    ]
    
    all_ok = True
    for name, import_name in packages:
        try:
            __import__(import_name)
            print(f"   ✓ {name}")
        except ImportError:
            print(f"   ✗ {name} not installed")
            all_ok = False
    
    # Optional
    try:
        import pymongo
        print(f"   ✓ pymongo (optional)")
    except ImportError:
        print(f"   - pymongo not installed (optional, will use JSON)")
    
    return all_ok


def check_config():
    """Check configuration."""
    print("\n6. Checking configuration...")
    
    try:
        sys.path.insert(0, '.')
        import config
        
        issues = []
        
        if not config.T212_API_KEY:
            issues.append("T212_API_KEY not set")
        else:
            print(f"   ✓ T212_API_KEY configured")
        
        if not config.TELEGRAM_TOKEN:
            issues.append("TELEGRAM_TOKEN not set")
        else:
            print(f"   ✓ TELEGRAM_TOKEN configured")
        
        if not config.TELEGRAM_CHAT_ID:
            issues.append("TELEGRAM_CHAT_ID not set")
        else:
            print(f"   ✓ TELEGRAM_CHAT_ID configured")
        
        if not config.FMP_API_KEY:
            print(f"   - FMP_API_KEY not set (earnings will be disabled)")
        else:
            print(f"   ✓ FMP_API_KEY configured")
        
        if issues:
            print(f"\n   Issues found:")
            for issue in issues:
                print(f"   ✗ {issue}")
            return False
        
        return True
        
    except Exception as e:
        print(f"   ✗ Config error: {e}")
        print(f"   Make sure .env file exists with required keys")
        return False


def check_t212_connection():
    """Check Trading212 API connection."""
    print("\n7. Checking Trading212 API...")
    
    try:
        from core.t212_client import T212Client
        import config
        
        client = T212Client(paper=config.PAPER_MODE)
        account = client.get_account()
        
        if account:
            print(f"   ✓ Connected: {account.currency} {account.total_value:,.2f}")
            return True
        else:
            print(f"   ✗ Could not get account info")
            return False
            
    except Exception as e:
        print(f"   ✗ Connection error: {e}")
        return False


def main():
    print("=" * 50)
    print("TRADING BOT - SETUP CHECK")
    print("=" * 50)
    
    results = []
    
    results.append(("Python", check_python_version()))
    results.append(("numpy", check_numpy()))
    results.append(("pandas", check_pandas()))
    results.append(("Yahoo Finance", check_market_data()))
    results.append(("packages", check_other_packages()))
    results.append(("config", check_config()))
    results.append(("T212 API", check_t212_connection()))
    
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    
    all_ok = True
    for name, ok in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")
        if not ok:
            all_ok = False
    
    print()
    if all_ok:
        print("✓ All checks passed! Run: python main.py")
    else:
        print("✗ Some checks failed. Fix the issues above.")
        print("\nQuick fix:")
        print("  pip install requests pandas numpy pytz python-dotenv")
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
