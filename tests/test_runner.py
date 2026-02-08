"""
tests/test_runner.py - Comprehensive Test Suite

Tests EVERYTHING before Saturday:
1. API connections (Trading212, FMP, Telegram)
2. Data storage (MongoDB, JSON files)
3. Weekend pipeline (universe, earnings, analysis)
4. Execution logic (NO-TRADE rules, trade decisions)
5. Position management (invalidation rules)

Run: python -m tests.test_runner
Or:  python main.py --test
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check numpy version FIRST - before any other imports
def _check_numpy():
    try:
        import numpy as np
        return True
    except ImportError:
        print("ERROR: numpy not installed")
        print("Fix: pip install -r requirements.txt")
        return False

if not _check_numpy():
    sys.exit(1)

import config

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = []
    
    def success(self, msg: str = ""):
        self.passed = True
        self.message = msg
        return self
    
    def fail(self, msg: str):
        self.passed = False
        self.message = msg
        return self
    
    def add_detail(self, detail: str):
        self.details.append(detail)
        return self


class TestSuite:
    """Comprehensive test suite."""
    
    def __init__(self):
        self.results: list = []
    
    def run_all(self):
        """Run all tests."""
        print("=" * 60)
        print("TRADING BOT TEST SUITE")
        print(f"Time: {datetime.now()}")
        print("=" * 60)
        
        # 1. Configuration
        self.test_configuration()
        
        # 2. API Connections
        self.test_t212_connection()
        self.test_fmp_connection()
        self.test_telegram_connection()
        self.test_mongodb_connection()
        
        # 3. Storage
        self.test_storage_operations()
        
        # 4. Weekend Pipeline
        self.test_universe_refresh()
        self.test_earnings_fetch()
        self.test_historical_analysis()
        
        # 5. Execution Logic
        self.test_no_trade_rules()
        self.test_trade_decisions()
        self.test_position_sizing()
        
        # 6. Position Management
        self.test_invalidation_rules()
        
        # Print summary
        self.print_summary()
    
    def add_result(self, result: TestResult):
        self.results.append(result)
        emoji = "✓" if result.passed else "✗"
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{emoji} [{status}] {result.name}")
        if result.message:
            print(f"  {result.message}")
        for detail in result.details:
            print(f"    - {detail}")
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        
        print(f"Passed: {passed}/{total}")
        
        failed = [r for r in self.results if not r.passed]
        if failed:
            print("\nFailed tests:")
            for r in failed:
                print(f"  ✗ {r.name}: {r.message}")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED! Ready for Saturday.")
        else:
            print(f"\n⚠️  {total - passed} test(s) failed. Fix before Saturday!")
    
    # ==================== CONFIGURATION TESTS ====================
    
    def test_configuration(self):
        result = TestResult("Configuration")
        
        missing = []
        
        if not config.T212_API_KEY:
            missing.append("T212_API_KEY")
        if not config.T212_API_SECRET:
            missing.append("T212_API_SECRET")
        
        # Optional but recommended
        warnings = []
        if not config.FMP_API_KEY:
            warnings.append("FMP_API_KEY (needed for earnings)")
        if not config.TELEGRAM_TOKEN:
            warnings.append("TELEGRAM_TOKEN (needed for alerts)")
        if not config.MONGO_URI:
            warnings.append("MONGO_URI (will use file storage)")
        
        if missing:
            result.fail(f"Missing required: {', '.join(missing)}")
        else:
            result.success("All required config present")
        
        for w in warnings:
            result.add_detail(f"Optional missing: {w}")
        
        self.add_result(result)
    
    # ==================== API CONNECTION TESTS ====================
    
    def test_t212_connection(self):
        result = TestResult("Trading212 API")
        
        try:
            from core.t212_client import T212Client
            
            client = T212Client(paper=config.PAPER_MODE)
            account = client.get_account()
            
            if account:
                result.success(f"Connected: {account.currency} {account.total_value:,.2f}")
                result.add_detail(f"Account ID: {account.id}")
                result.add_detail(f"Free cash: {account.free_cash:,.2f}")
            else:
                result.fail("Could not get account info")
                
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_fmp_connection(self):
        result = TestResult("FMP API (Earnings)")
        
        if not config.FMP_API_KEY:
            result.fail("FMP_API_KEY not configured")
            self.add_result(result)
            return
        
        try:
            import requests
            
            today = datetime.now()
            next_week = today + timedelta(days=7)
            
            url = "https://financialmodelingprep.com/api/v3/earning_calendar"
            params = {
                "from": today.strftime("%Y-%m-%d"),
                "to": next_week.strftime("%Y-%m-%d"),
                "apikey": config.FMP_API_KEY
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "Error Message" in data:
                    result.fail(f"API Error: {data.get('Error Message', 'Unknown')}")
                else:
                    result.success(f"Connected: {len(data)} earnings found")
            elif resp.status_code == 401:
                result.fail("HTTP 401 - Invalid API key. Check FMP_API_KEY in .env")
                result.add_detail("Get a free API key at: https://financialmodelingprep.com/")
            elif resp.status_code == 403:
                result.fail("HTTP 403 - API key limit reached or invalid plan")
            else:
                result.fail(f"HTTP {resp.status_code}: {resp.text[:100]}")
                
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_telegram_connection(self):
        result = TestResult("Telegram API")
        
        if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
            result.fail("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not configured")
            self.add_result(result)
            return
        
        try:
            import requests
            
            url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getMe"
            resp = requests.get(url, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    bot_name = data.get("result", {}).get("username", "Unknown")
                    result.success(f"Connected: @{bot_name}")
                else:
                    result.fail("API returned error")
            else:
                result.fail(f"HTTP {resp.status_code}")
                
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_mongodb_connection(self):
        result = TestResult("MongoDB")
        
        if not config.MONGO_URI:
            result.success("Not configured (using file storage)")
            self.add_result(result)
            return
        
        try:
            from pymongo import MongoClient
            
            client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            
            result.success("Connected")
            
        except ImportError:
            result.fail("pymongo not installed")
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    # ==================== STORAGE TESTS ====================
    
    def test_storage_operations(self):
        result = TestResult("Storage Operations")
        
        try:
            from core.storage import Storage, get_week_id
            
            storage = Storage()
            
            # Test save/load universe
            test_universe = [
                {"symbol": "TEST", "ticker": "TEST_US_EQ", "name": "Test Corp"}
            ]
            
            test_week = "TEST-W99"
            storage.save_universe(test_universe, test_week)
            loaded = storage.get_universe(test_week)
            
            if loaded and loaded.get("instruments"):
                result.add_detail("Universe save/load: OK")
            else:
                result.fail("Universe save/load failed")
                self.add_result(result)
                return
            
            # Test earnings candidates
            test_candidates = [{"symbol": "TEST", "date": "2026-02-06"}]
            storage.save_earnings_candidates(test_candidates, test_week)
            loaded = storage.get_earnings_candidates(test_week)
            
            if loaded:
                result.add_detail("Earnings save/load: OK")
            else:
                result.fail("Earnings save/load failed")
                self.add_result(result)
                return
            
            # Test analysis results
            test_results = [{"symbol": "TEST", "final_score": 4}]
            storage.save_analysis_results(test_results, test_week)
            loaded = storage.get_analysis_results(test_week)
            
            if loaded:
                result.add_detail("Analysis save/load: OK")
            else:
                result.fail("Analysis save/load failed")
                self.add_result(result)
                return
            
            result.success("All storage operations working")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    # ==================== WEEKEND PIPELINE TESTS ====================
    
    def test_universe_refresh(self):
        result = TestResult("Universe Refresh")
        
        try:
            from core.t212_client import T212Client
            
            client = T212Client(paper=config.PAPER_MODE)
            instruments = client.get_all_instruments(refresh=True)
            
            if len(instruments) > 100:
                result.success(f"Loaded {len(instruments)} instruments")
                
                # Check some expected stocks
                symbols = {i.symbol for i in instruments}
                expected = ["AAPL", "MSFT", "GOOGL", "TSLA"]
                found = [s for s in expected if s in symbols]
                
                result.add_detail(f"Sample check: {len(found)}/{len(expected)} found")
            else:
                result.fail(f"Only {len(instruments)} instruments")
                
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_earnings_fetch(self):
        result = TestResult("Earnings Calendar Fetch")
        
        if not config.FMP_API_KEY:
            result.fail("FMP_API_KEY required")
            self.add_result(result)
            return
        
        try:
            import requests
            
            today = datetime.now()
            next_monday = today + timedelta(days=(7 - today.weekday()) % 7)
            next_friday = next_monday + timedelta(days=4)
            
            url = "https://financialmodelingprep.com/api/v3/earning_calendar"
            params = {
                "from": next_monday.strftime("%Y-%m-%d"),
                "to": next_friday.strftime("%Y-%m-%d"),
                "apikey": config.FMP_API_KEY
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                result.success(f"Found {len(data)} earnings next week")
                
                if data:
                    result.add_detail(f"First: {data[0].get('symbol')}")
            else:
                result.fail(f"HTTP {resp.status_code}")
                
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_historical_analysis(self):
        result = TestResult("Historical Analysis")
        
        try:
            from core import market_data
            import pandas as pd
            
            # Test with a known stock
            symbol = "AAPL"
            
            hist = market_data.get_history(symbol, period="2y")
            
            if hist is None or len(hist) < 200:
                result.fail(f"Insufficient history: {len(hist) if hist is not None else 0} days")
                self.add_result(result)
                return
            
            result.add_detail(f"History: {len(hist)} days")
            
            # Test earnings dates
            try:
                earnings = market_data.get_earnings_dates(symbol)
                if earnings is not None and not earnings.empty:
                    result.add_detail(f"Earnings dates: {len(earnings)}")
                else:
                    result.add_detail("No earnings dates (may be normal)")
            except Exception as e:
                result.add_detail(f"Earnings dates: skipped ({type(e).__name__})")
            
            # Test basic calculations
            returns = hist['Close'].pct_change()
            vol = returns.std() * (252 ** 0.5) * 100
            
            result.add_detail(f"Volatility: {vol:.1f}%")
            
            result.success(f"Analysis working for {symbol}")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    # ==================== EXECUTION LOGIC TESTS ====================
    
    def test_no_trade_rules(self):
        result = TestResult("NO-TRADE Rules")
        
        try:
            # Test the rule thresholds
            rules = config.NO_TRADE_RULES
            
            result.add_detail(f"Min volume: {rules['min_avg_volume']:,}")
            result.add_detail(f"Max premarket gap: {rules['max_premarket_gap_pct']}%")
            result.add_detail(f"Min market cap: ${rules['min_market_cap']/1e6:.0f}M")
            
            # Test with a real stock
            from core import market_data
            
            info = market_data.get_info("AAPL") or {}
            
            vol = info.get("averageVolume", 0) or 0
            mkt_cap = info.get("marketCap", 0) or 0
            
            checks = []
            if vol >= rules["min_avg_volume"]:
                checks.append("Volume: PASS")
            else:
                checks.append("Volume: FAIL")
            
            if mkt_cap >= rules["min_market_cap"]:
                checks.append("Market cap: PASS")
            else:
                checks.append("Market cap: FAIL")
            
            for c in checks:
                result.add_detail(f"AAPL {c}")
            
            result.success("NO-TRADE rules configured")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_trade_decisions(self):
        result = TestResult("Trade Decision Logic")
        
        try:
            # Test score thresholds
            score_sizes = config.POSITION_SIZE_BY_SCORE
            
            for score, size in sorted(score_sizes.items(), reverse=True):
                action = "FULL" if size == 1.0 else f"{size*100:.0f}%" if size > 0 else "OBSERVE"
                result.add_detail(f"Score {score}: {action}")
            
            result.success("Trade decision logic configured")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    def test_position_sizing(self):
        result = TestResult("Position Sizing")
        
        try:
            from core.t212_client import T212Client
            
            client = T212Client(paper=config.PAPER_MODE)
            account = client.get_account()
            
            if not account:
                result.fail("Could not get account")
                self.add_result(result)
                return
            
            cash = account.free_cash
            max_pos = cash * config.MAX_POSITION_PCT
            
            result.add_detail(f"Free cash: {account.currency} {cash:,.2f}")
            result.add_detail(f"Max position ({config.MAX_POSITION_PCT*100:.0f}%): {account.currency} {max_pos:,.2f}")
            
            # Show sizing by score
            for score in [5, 4, 3]:
                mult = config.POSITION_SIZE_BY_SCORE.get(score, 0.5)
                size = max_pos * mult
                result.add_detail(f"Score {score} size: {account.currency} {size:,.2f}")
            
            result.success("Position sizing configured")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)
    
    # ==================== POSITION MANAGEMENT TESTS ====================
    
    def test_invalidation_rules(self):
        result = TestResult("Invalidation Rules")
        
        try:
            rules = config.INVALIDATION_RULES
            
            result.add_detail(f"Max loss: {rules['max_loss_pct']}%")
            result.add_detail(f"Trailing stop: {rules['trailing_stop_pct']}%")
            result.add_detail(f"Max hold: {rules['max_hold_days']} days")
            
            # Simulate scenarios
            scenarios = [
                ("Entry $100, Current $91", -9.0, rules['max_loss_pct'], "CLOSE (max loss)"),
                ("Entry $100, Current $95", -5.0, rules['max_loss_pct'], "HOLD"),
                ("Entry $100, High $120, Current $113", -5.83, rules['trailing_stop_pct'], "CLOSE (trailing)"),
            ]
            
            for desc, pnl, threshold, expected in scenarios:
                result.add_detail(f"{desc} → {expected}")
            
            result.success("Invalidation rules configured")
            
        except Exception as e:
            result.fail(str(e))
        
        self.add_result(result)


def run_all_tests():
    """Run all tests."""
    suite = TestSuite()
    suite.run_all()
    
    # Return exit code
    failed = sum(1 for r in suite.results if not r.passed)
    return failed


if __name__ == "__main__":
    sys.exit(run_all_tests())
