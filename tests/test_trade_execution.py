"""
tests/test_trade_execution.py - Test Actual Trade Placement

IMPORTANT: This will place REAL orders in your account!
Only run this with PAPER trading mode enabled.

Tests:
1. Buy a small position
2. Check position exists
3. Sell the position
4. Verify closed

Usage:
    python -m tests.test_trade_execution
    python -m tests.test_trade_execution --symbol AAPL --amount 10
"""

import sys
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.t212_client import T212Client
from core import market_data

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def test_trade_execution(symbol: str = "AAPL", amount: float = 10.0, paper: bool = True):
    """
    Test complete trade cycle: buy -> verify -> sell -> verify
    
    Args:
        symbol: Stock to trade
        amount: Dollar amount to buy
        paper: Must be True for safety
    """
    print("=" * 60)
    print("TRADE EXECUTION TEST")
    print("=" * 60)
    
    if not paper:
        print("\n⚠️  DANGER: LIVE MODE DETECTED!")
        print("This will place REAL trades with REAL money!")
        confirm = input("Type 'YES I UNDERSTAND' to continue: ")
        if confirm != "YES I UNDERSTAND":
            print("Aborted.")
            return False
    else:
        print("\n✓ Paper mode - safe to test")
    
    # Initialize client
    print("\n1. Connecting to Trading212...")
    try:
        client = T212Client(paper=paper)
        
        if not client.test_connection():
            print("   ✗ Connection failed!")
            return False
        
        account = client.get_account()
        print(f"   ✓ Connected: {account.currency} {account.free_cash:,.2f} available")
        
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False
    
    # Check if symbol is tradeable
    print(f"\n2. Checking if {symbol} is tradeable...")
    
    if not client.is_tradeable(symbol):
        print(f"   ✗ {symbol} is NOT tradeable on Trading212")
        print("   Try a different symbol like AAPL, MSFT, or TSLA")
        return False
    
    ticker = client.get_ticker(symbol)
    print(f"   ✓ Tradeable as: {ticker}")
    
    # Get current price
    print(f"\n3. Getting current price...")
    
    price = market_data.get_current_price(symbol)
    if not price:
        print("   ✗ Could not get price")
        return False
    
    print(f"   ✓ Current price: ${price:.2f}")
    
    # Calculate quantity
    quantity = round(amount / price, 2)  # Round to 2 decimal places for T212
    print(f"   Order: {quantity:.2f} shares (${amount:.2f})")
    
    # Check existing position
    print(f"\n4. Checking for existing position...")
    
    existing = client.get_position(symbol)
    if existing:
        print(f"   ⚠️  Already have position: {existing.quantity:.4f} shares")
        print(f"      P&L: ${existing.pnl:+.2f} ({existing.pnl_pct:+.1f}%)")
    else:
        print("   ✓ No existing position")
    
    # Place BUY order
    print(f"\n5. Placing BUY order...")
    print(f"   Symbol: {symbol}")
    print(f"   Quantity: {quantity:.6f}")
    print(f"   Est. Value: ${amount:.2f}")
    
    confirm = input("\n   Place order? (y/n): ")
    if confirm.lower() != 'y':
        print("   Aborted.")
        return False
    
    try:
        result = client.buy(symbol, quantity)
        
        if result:
            print(f"   ✓ Order placed successfully!")
            print(f"   Response: {result}")
        else:
            print("   ✗ Order failed - no response")
            return False
            
    except Exception as e:
        print(f"   ✗ Order failed: {e}")
        return False
    
    # Wait for order to fill
    print("\n6. Waiting for order to fill...")
    time.sleep(3)
    
    # Verify position
    print("\n7. Verifying position...")
    
    position = client.get_position(symbol)
    
    if position:
        print(f"   ✓ Position confirmed!")
        print(f"      Quantity: {position.quantity:.6f}")
        print(f"      Avg Price: ${position.avg_price:.2f}")
        print(f"      Current: ${position.current_price:.2f}")
        print(f"      P&L: ${position.pnl:+.2f} ({position.pnl_pct:+.1f}%)")
    else:
        print("   ⚠️  Position not found (may still be processing)")
        # Continue anyway to try sell
    
    # Place SELL order
    print(f"\n8. Placing SELL order to close position...")
    
    confirm = input("   Close position? (y/n): ")
    if confirm.lower() != 'y':
        print("   Position left open. You can close manually.")
        return True
    
    try:
        result = client.close_position(symbol)
        
        if result:
            print(f"   ✓ Sell order placed!")
            print(f"   Response: {result}")
        else:
            print("   ✗ Sell failed - may already be closed")
            
    except Exception as e:
        print(f"   ✗ Sell failed: {e}")
    
    # Wait and verify closed
    print("\n9. Verifying position closed...")
    time.sleep(3)
    
    final_position = client.get_position(symbol)
    
    if final_position is None or final_position.quantity == 0:
        print("   ✓ Position closed successfully!")
    else:
        print(f"   ⚠️  Position still open: {final_position.quantity:.6f} shares")
    
    # Final account status
    print("\n10. Final account status...")
    
    final_account = client.get_account()
    print(f"    Cash: {final_account.currency} {final_account.free_cash:,.2f}")
    print(f"    Total: {final_account.currency} {final_account.total_value:,.2f}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    return True


def test_order_types(paper: bool = True):
    """Test different order scenarios."""
    print("=" * 60)
    print("ORDER TYPE TESTS")
    print("=" * 60)
    
    client = T212Client(paper=paper)
    
    if not client.test_connection():
        print("Connection failed!")
        return
    
    # Test 1: Get all positions
    print("\n1. Current Positions:")
    positions = client.get_positions()
    if positions:
        for p in positions:
            print(f"   {p.symbol}: {p.quantity:.4f} @ ${p.current_price:.2f}")
    else:
        print("   No open positions")
    
    # Test 2: Check tradeable symbols
    print("\n2. Checking tradeable symbols:")
    test_symbols = ["AAPL", "MSFT", "TSLA", "GOOGL", "NVDA", "SPY", "QQQ"]
    
    for symbol in test_symbols:
        tradeable = client.is_tradeable(symbol)
        ticker = client.get_ticker(symbol) if tradeable else "N/A"
        status = "✓" if tradeable else "✗"
        print(f"   {status} {symbol}: {ticker}")
    
    # Test 3: Account summary
    print("\n3. Account Summary:")
    account = client.get_account()
    print(f"   ID: {account.id}")
    print(f"   Currency: {account.currency}")
    print(f"   Free Cash: {account.free_cash:,.2f}")
    print(f"   Invested: {account.invested:,.2f}")
    print(f"   Total Value: {account.total_value:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Test Trade Execution")
    parser.add_argument("--symbol", "-s", default="AAPL", help="Symbol to trade")
    parser.add_argument("--amount", "-a", type=float, default=10.0, help="Dollar amount")
    parser.add_argument("--live", action="store_true", help="Use LIVE mode (DANGEROUS!)")
    parser.add_argument("--status", action="store_true", help="Just show status")
    
    args = parser.parse_args()
    
    paper = not args.live
    
    if args.status:
        test_order_types(paper=paper)
    else:
        test_trade_execution(symbol=args.symbol, amount=args.amount, paper=paper)


if __name__ == "__main__":
    main()
