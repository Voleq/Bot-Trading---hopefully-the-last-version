"""
tests/test_execution_simulation.py - Simulate Execution Logic

Test the weekday execution logic WITHOUT placing real trades.

Simulates:
1. Loading precomputed analysis
2. Checking NO-TRADE conditions
3. Making trade decisions
4. Position sizing
5. Invalidation checks

Usage:
    python -m tests.test_execution_simulation
    python -m tests.test_execution_simulation --symbol AAPL
"""

import sys
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.t212_client import T212Client
from core.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class ExecutionSimulation:
    """Simulate execution logic."""
    
    def __init__(self, symbol: str = None):
        self.t212 = T212Client(paper=config.PAPER_MODE)
        self.storage = Storage()
        self.test_symbol = symbol
    
    def run(self):
        """Run simulation."""
        print("=" * 60)
        print("EXECUTION LOGIC SIMULATION")
        print("=" * 60)
        
        # 1. Test NO-TRADE rules
        self.test_no_trade_rules()
        
        # 2. Test trade decisions
        self.test_trade_decisions()
        
        # 3. Test position sizing
        self.test_position_sizing()
        
        # 4. Test invalidation
        self.test_invalidation()
    
    def test_no_trade_rules(self):
        """Test NO-TRADE condition checks."""
        print("\n" + "-" * 40)
        print("NO-TRADE RULES TEST")
        print("-" * 40)
        
        symbols = [self.test_symbol] if self.test_symbol else ["AAPL", "TSLA", "NVDA", "GME", "AMC"]
        
        from core import market_data
        
        for symbol in symbols:
            print(f"\n{symbol}:")
            
            try:
                info = market_data.get_info(symbol) or {}
                hist = market_data.get_history(symbol, period="5d")
                
                # Volume check
                avg_vol = info.get("averageVolume", 0) or 0
                vol_ok = avg_vol >= config.NO_TRADE_RULES["min_avg_volume"]
                print(f"  Volume: {avg_vol:,.0f} {'✓' if vol_ok else '✗ (min: ' + str(config.NO_TRADE_RULES['min_avg_volume']) + ')'}")
                
                # Market cap check
                mkt_cap = info.get("marketCap", 0) or 0
                cap_ok = mkt_cap >= config.NO_TRADE_RULES["min_market_cap"]
                print(f"  Market Cap: ${mkt_cap/1e9:.1f}B {'✓' if cap_ok else '✗'}")
                
                # Gap check
                if hist is not None and len(hist) >= 2:
                    prev_close = hist['Close'].iloc[-2]
                    current = hist['Close'].iloc[-1]
                    gap_pct = ((current - prev_close) / prev_close) * 100
                    gap_ok = abs(gap_pct) <= config.NO_TRADE_RULES["max_premarket_gap_pct"]
                    print(f"  Gap: {gap_pct:+.1f}% {'✓' if gap_ok else '✗'}")
                
                # Tradeable check
                tradeable = self.t212.is_tradeable(symbol)
                print(f"  On T212: {'✓' if tradeable else '✗'}")
                
                # Overall
                all_ok = vol_ok and cap_ok and tradeable
                print(f"  → {'TRADEABLE' if all_ok else 'NO-TRADE'}")
                
            except Exception as e:
                print(f"  Error: {e}")
    
    def test_trade_decisions(self):
        """Test trade decision logic with mock analysis."""
        print("\n" + "-" * 40)
        print("TRADE DECISION TEST")
        print("-" * 40)
        
        # Mock scenarios
        scenarios = [
            {"score": 5, "behavior": "continuation", "expected": "TRADE"},
            {"score": 5, "behavior": "fade", "expected": "TRADE"},
            {"score": 4, "behavior": "continuation", "expected": "TRADE"},
            {"score": 4, "behavior": "mixed", "expected": "TRADE"},
            {"score": 3, "behavior": "continuation", "expected": "TRADE"},
            {"score": 3, "behavior": "mixed", "expected": "NO-TRADE"},
            {"score": 2, "behavior": "fade", "expected": "NO-TRADE"},
            {"score": 1, "behavior": "unknown", "expected": "OBSERVE"},
        ]
        
        print("\nDecision Matrix:")
        print("-" * 50)
        print(f"{'Score':<8} {'Behavior':<15} {'Decision':<12} {'Size Mult'}")
        print("-" * 50)
        
        for s in scenarios:
            score = s["score"]
            behavior = s["behavior"]
            expected = s["expected"]
            
            # Get position size multiplier
            mult = config.POSITION_SIZE_BY_SCORE.get(score, 0.5)
            
            if mult == 0:
                decision = "OBSERVE"
            elif score >= 4:
                decision = "TRADE"
            elif score == 3 and behavior in ["continuation", "fade"]:
                decision = "TRADE"
            else:
                decision = "NO-TRADE"
            
            match = "✓" if decision == expected else "✗"
            
            print(f"{score:<8} {behavior:<15} {decision:<12} {mult:.0%} {match}")
    
    def test_position_sizing(self):
        """Test position sizing calculations."""
        print("\n" + "-" * 40)
        print("POSITION SIZING TEST")
        print("-" * 40)
        
        account = self.t212.get_account()
        if not account:
            print("Could not get account info")
            return
        
        cash = account.free_cash
        currency = account.currency
        
        print(f"\nAccount: {currency} {cash:,.2f}")
        print(f"Max Position %: {config.MAX_POSITION_PCT*100:.0f}%")
        print(f"Max Positions: {config.MAX_POSITIONS}")
        
        base_size = cash * config.MAX_POSITION_PCT
        
        print(f"\nPosition sizes by score:")
        print("-" * 40)
        
        for score in [5, 4, 3, 2, 1]:
            mult = config.POSITION_SIZE_BY_SCORE.get(score, 0)
            size = base_size * mult
            
            if mult == 0:
                print(f"  Score {score}: OBSERVE ONLY")
            else:
                print(f"  Score {score}: {currency} {size:,.2f} ({mult*100:.0f}% of max)")
        
        # Example trade
        print(f"\nExample: Buy AAPL with score 4")
        
        from core import market_data
        price = market_data.get_current_price("AAPL") or 180
        
        size = base_size * config.POSITION_SIZE_BY_SCORE[4]
        shares = size / price
        
        print(f"  Price: ${price:.2f}")
        print(f"  Value: {currency} {size:,.2f}")
        print(f"  Shares: {shares:.4f}")
    
    def test_invalidation(self):
        """Test invalidation rule calculations."""
        print("\n" + "-" * 40)
        print("INVALIDATION RULES TEST")
        print("-" * 40)
        
        rules = config.INVALIDATION_RULES
        
        print(f"\nRules:")
        print(f"  Max loss: {rules['max_loss_pct']}%")
        print(f"  Trailing stop: {rules['trailing_stop_pct']}%")
        print(f"  Max hold: {rules['max_hold_days']} days")
        
        # Test scenarios
        scenarios = [
            {"entry": 100, "current": 100, "high": 100, "days": 0, "desc": "Entry"},
            {"entry": 100, "current": 105, "high": 105, "days": 1, "desc": "+5%"},
            {"entry": 100, "current": 95, "high": 105, "days": 2, "desc": "Dropped from high"},
            {"entry": 100, "current": 91, "high": 100, "days": 3, "desc": "-9% (thesis break?)"},
            {"entry": 100, "current": 110, "high": 120, "days": 5, "desc": "Trailing stop?"},
            {"entry": 100, "current": 105, "high": 105, "days": 11, "desc": "Max hold?"},
        ]
        
        print("\nScenarios:")
        print("-" * 70)
        print(f"{'Description':<25} {'Entry':<8} {'High':<8} {'Current':<8} {'Days':<6} {'Action'}")
        print("-" * 70)
        
        for s in scenarios:
            entry = s["entry"]
            current = s["current"]
            high = s["high"]
            days = s["days"]
            desc = s["desc"]
            
            # Check rules
            pnl_pct = ((current - entry) / entry) * 100
            drop_from_high = ((high - current) / high) * 100 if high > entry else 0
            
            action = "HOLD"
            
            if pnl_pct <= rules["max_loss_pct"]:
                action = "CLOSE (max loss)"
            elif high > entry and drop_from_high >= rules["trailing_stop_pct"]:
                action = "CLOSE (trailing)"
            elif days >= rules["max_hold_days"]:
                action = "CLOSE (max hold)"
            
            print(f"{desc:<25} ${entry:<7} ${high:<7} ${current:<7} {days:<6} {action}")


def main():
    parser = argparse.ArgumentParser(description="Simulate Execution Logic")
    parser.add_argument("--symbol", "-s", help="Test specific symbol")
    
    args = parser.parse_args()
    
    sim = ExecutionSimulation(symbol=args.symbol)
    sim.run()


if __name__ == "__main__":
    main()
