#!/usr/bin/env python3
"""
run_bot.py - Safe launcher for Trading Bot

This script checks dependencies BEFORE importing the main bot,
preventing numpy 2.0 compatibility errors.

Usage:
    python run_bot.py          # Run bot
    python run_bot.py --test   # Run tests
    python run_bot.py --live   # Live mode (real money!)
"""

import sys
import subprocess

def check_numpy():
    """Check numpy version before importing anything else."""
    try:
        # Use subprocess to avoid import issues
        result = subprocess.run(
            [sys.executable, "-c", "import numpy; print(numpy.__version__)"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return False, f"numpy import failed: {result.stderr}"
        
        version = result.stdout.strip()
        major = int(version.split('.')[0])
        
        if major >= 2:
            return False, f"numpy {version} detected (need <2.0)"
        
        return True, version
        
    except Exception as e:
        return False, str(e)

def check_pandas():
    """Check pandas can import (depends on numpy)."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import pandas; print(pandas.__version__)"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            stderr = result.stderr
            if "__version__" in stderr:
                return False, "pandas incompatible with numpy 2.0"
            return False, f"pandas error: {stderr[:100]}"
        
        return True, result.stdout.strip()
        
    except Exception as e:
        return False, str(e)

def main():
    print("=" * 60)
    print("Trading Bot Launcher")
    print("=" * 60)
    
    # Check numpy
    ok, msg = check_numpy()
    if not ok:
        print(f"✗ numpy: {msg}")
        print()
        print("FIX: Run this command:")
        print("  bash fix_dependencies.sh")
        print("=" * 60)
        return 1
    print(f"✓ numpy: {msg}")
    
    # Check pandas
    ok, msg = check_pandas()
    if not ok:
        print(f"✗ pandas: {msg}")
        print()
        print("FIX: Run this command:")
        print("  bash fix_dependencies.sh")
        print("=" * 60)
        return 1
    print(f"✓ pandas: {msg}")
    
    print("✓ Dependencies OK")
    print("=" * 60)
    print()
    
    # Now import and run the actual bot
    # Pass through command line args
    args = sys.argv[1:]
    
    # Import main module
    try:
        from main import main as bot_main
        return bot_main(args)
    except ImportError as e:
        print(f"Failed to import bot: {e}")
        return 1
    except Exception as e:
        print(f"Bot error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main() or 0)
