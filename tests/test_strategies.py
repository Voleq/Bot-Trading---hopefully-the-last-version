"""
tests/test_strategies.py - Test All Non-Earnings Strategies

Run this to verify all strategies work before Saturday.

Usage:
    python -m tests.test_strategies
    python -m tests.test_strategies --strategy sector_momentum
    python -m tests.test_strategies --full
"""

import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Check numpy version FIRST
try:
    import numpy as np
    if int(np.__version__.split('.')[0]) >= 2:
        print("ERROR: numpy 2.0+ is not supported!")
        print("Run: pip uninstall numpy -y && pip install numpy==1.26.4")
        sys.exit(1)
except ImportError:
    print("ERROR: numpy not installed. Run: pip install numpy==1.26.4")
    sys.exit(1)

import config
from strategies import (
    SectorMomentumStrategy,
    MeanReversionStrategy,
    BreakoutStrategy,
    StrategyManager
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def test_sector_momentum():
    """Test Sector Momentum strategy."""
    print("\n" + "=" * 60)
    print("SECTOR MOMENTUM STRATEGY")
    print("=" * 60)
    
    strategy = SectorMomentumStrategy()
    
    print(f"\nConfig:")
    print(f"  Check time: {strategy.config.check_time}")
    print(f"  Max positions: {strategy.config.max_positions}")
    print(f"  Position size: {strategy.config.position_size_pct*100:.0f}%")
    
    print(f"\nUniverse: {len(strategy.get_universe())} sector ETFs")
    print(f"  {', '.join(strategy.get_universe())}")
    
    print("\nRunning weekend analysis...")
    results = strategy.analyze()
    
    print(f"\nResults ({len(results)} sectors):")
    print("-" * 60)
    print(f"{'Rank':<6} {'Symbol':<8} {'Sector':<20} {'Score':<6} {'1M Ret':<10} {'Signal'}")
    print("-" * 60)
    
    for r in results:
        print(f"{r['momentum_rank']:<6} {r['symbol']:<8} {r['sector_name'][:20]:<20} "
              f"{r['score']:<6} {r['return_1m']:>+6.1f}%    {r['signal']}")
    
    print("\nRunning daily scan...")
    signals = strategy.scan()
    
    print(f"\nSignals ({len(signals)}):")
    for s in signals:
        print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}/5 - {s.reason}")
    
    return len(results) > 0


def test_mean_reversion():
    """Test Mean Reversion strategy."""
    print("\n" + "=" * 60)
    print("MEAN REVERSION STRATEGY")
    print("=" * 60)
    
    strategy = MeanReversionStrategy()
    
    print(f"\nConfig:")
    print(f"  Check time: {strategy.config.check_time}")
    print(f"  Max positions: {strategy.config.max_positions}")
    print(f"  RSI entry: < {strategy.rsi_entry}")
    print(f"  RSI exit: > {strategy.rsi_exit}")
    
    print(f"\nUniverse: {len(strategy.get_universe())} quality stocks")
    
    print("\nRunning weekend analysis (quality screening)...")
    results = strategy.analyze()
    
    print(f"\nQuality stocks screened: {len(results)}")
    
    print("\nRunning daily scan (looking for RSI < 10)...")
    signals = strategy.scan()
    
    print(f"\nSignals ({len(signals)}):")
    if signals:
        for s in signals:
            print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}/5")
            print(f"    {s.reason}")
            print(f"    Entry: ${s.entry_price:.2f}, Stop: ${s.stop_loss:.2f}")
    else:
        print("  No oversold stocks found (this is normal)")
        
        # Show stocks closest to oversold
        print("\n  Stocks with lowest RSI:")
        rsi_data = []
        for symbol in strategy.get_universe()[:30]:
            data = strategy._check_oversold(symbol)
            if data and data.get("rsi"):
                rsi_data.append((symbol, data["rsi"]))
        
        rsi_data.sort(key=lambda x: x[1])
        for symbol, rsi in rsi_data[:10]:
            status = "OVERSOLD" if rsi < 10 else ""
            print(f"    {symbol}: RSI = {rsi:.1f} {status}")
    
    return len(results) > 0


def test_breakout():
    """Test Breakout strategy."""
    print("\n" + "=" * 60)
    print("BREAKOUT STRATEGY")
    print("=" * 60)
    
    strategy = BreakoutStrategy()
    
    print(f"\nConfig:")
    print(f"  Check time: {strategy.config.check_time}")
    print(f"  Max positions: {strategy.config.max_positions}")
    print(f"  Max % from high: {strategy.max_pct_from_high}%")
    print(f"  Min volume ratio: {strategy.min_volume_ratio}x")
    
    print(f"\nUniverse: {len(strategy.get_universe())} stocks")
    
    print("\nRunning weekend analysis...")
    results = strategy.analyze()
    
    # Show watchlist
    watchlist = [r for r in results if r.get("pct_from_high", 100) <= 5]
    
    print(f"\nWatchlist ({len(watchlist)} stocks within 5% of 52W high):")
    print("-" * 70)
    print(f"{'Symbol':<10} {'% From High':<12} {'RSI':<8} {'Vol Ratio':<12} {'Uptrend'}")
    print("-" * 70)
    
    for r in watchlist[:15]:
        uptrend = "✓" if r.get("in_uptrend") else "✗"
        print(f"{r['symbol']:<10} {r['pct_from_high']:<12.1f} {r.get('rsi', 0):<8.0f} "
              f"{r.get('volume_ratio', 0):<12.1f} {uptrend}")
    
    print("\nRunning daily scan...")
    signals = strategy.scan()
    
    print(f"\nSignals ({len(signals)}):")
    for s in signals:
        print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}/5")
        print(f"    {s.reason}")
    
    return len(results) > 0


def test_strategy_manager():
    """Test Strategy Manager."""
    print("\n" + "=" * 60)
    print("STRATEGY MANAGER")
    print("=" * 60)
    
    manager = StrategyManager()
    
    print(f"\nManaging {len(manager.strategies)} strategies:")
    for name, strategy in manager.strategies.items():
        print(f"  - {name}: {'Enabled' if strategy.enabled else 'Disabled'}")
    
    print("\nStatus:")
    status = manager.get_status()
    
    for name, data in status["strategies"].items():
        print(f"\n  {name}:")
        print(f"    Check time: {data['check_time']}")
        print(f"    Max positions: {data['max_positions']}")
        print(f"    Current positions: {data['current_positions']}")
    
    return True


def run_full_test():
    """Run all strategy tests."""
    print("=" * 60)
    print("FULL STRATEGY TEST SUITE")
    print(f"Time: {datetime.now()}")
    print("=" * 60)
    
    results = {}
    
    # Test each strategy
    results["sector_momentum"] = test_sector_momentum()
    results["mean_reversion"] = test_mean_reversion()
    results["breakout"] = test_breakout()
    results["manager"] = test_strategy_manager()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 ALL STRATEGY TESTS PASSED!")
    else:
        print("\n⚠️  SOME TESTS FAILED")
    
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Test Trading Strategies")
    parser.add_argument("--strategy", "-s", 
                       choices=["sector_momentum", "mean_reversion", "breakout", "manager"],
                       help="Test specific strategy")
    parser.add_argument("--full", "-f", action="store_true",
                       help="Run full test suite")
    
    args = parser.parse_args()
    
    if args.full or not args.strategy:
        run_full_test()
    elif args.strategy == "sector_momentum":
        test_sector_momentum()
    elif args.strategy == "mean_reversion":
        test_mean_reversion()
    elif args.strategy == "breakout":
        test_breakout()
    elif args.strategy == "manager":
        test_strategy_manager()


if __name__ == "__main__":
    main()
