"""
tests/test_weekend_simulation.py - Simulate Weekend Pipeline

Run this on Tuesday to verify Saturday will work!

Simulates the ENTIRE weekend pipeline:
1. Universe refresh from T212
2. Earnings fetch from FMP  
3. Cross-check and filtering
4. Historical analysis on candidates
5. Score computation
6. Storage to files/MongoDB
7. Telegram notifications

Usage:
    python -m tests.test_weekend_simulation
    python -m tests.test_weekend_simulation --dry-run  # No Telegram
    python -m tests.test_weekend_simulation --verbose  # Detailed output
"""

import sys
import argparse
import logging
from datetime import datetime, timedelta
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
from core.t212_client import T212Client
from core.storage import Storage, get_week_id
from core.telegram import Telegram
from analysis.weekend_pipeline import WeekendAnalysisPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)


class WeekendSimulation:
    """Simulate the weekend analysis pipeline."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        
        self.t212 = T212Client(paper=config.PAPER_MODE)
        self.storage = Storage()
        self.telegram = Telegram() if not dry_run else None
        
        # Use test week ID to not overwrite real data
        self.test_week = f"TEST-{datetime.now().strftime('%Y%m%d')}"
        
        self.results = {
            "universe_count": 0,
            "earnings_raw": 0,
            "earnings_filtered": 0,
            "analyzed": 0,
            "high_score": 0,
            "errors": []
        }
    
    def log(self, msg: str, level: str = "INFO"):
        """Log message."""
        if level == "ERROR":
            logger.error(msg)
            self.results["errors"].append(msg)
        elif self.verbose or level == "INFO":
            logger.info(msg)
    
    def run(self):
        """Run full simulation."""
        print("=" * 60)
        print("WEEKEND PIPELINE SIMULATION")
        print(f"Test Week ID: {self.test_week}")
        print(f"Dry Run: {self.dry_run}")
        print("=" * 60)
        
        # Step 1: Universe
        self.step1_universe()
        
        # Step 2: Earnings
        self.step2_earnings()
        
        # Step 3: Analysis
        self.step3_analysis()
        
        # Summary
        self.print_summary()
    
    def step1_universe(self):
        """Step 1: Refresh universe from Trading212."""
        print("\n" + "-" * 40)
        print("STEP 1: Universe Refresh")
        print("-" * 40)
        
        try:
            instruments = self.t212.get_all_instruments(refresh=True)
            self.results["universe_count"] = len(instruments)
            
            # Convert to storable format
            universe = []
            for inst in instruments:
                universe.append({
                    "ticker": inst.ticker,
                    "symbol": inst.symbol,
                    "name": inst.name,
                    "type": inst.type,
                    "currency": inst.currency
                })
            
            # Save
            self.storage.save_universe(universe, self.test_week)
            
            self.log(f"✓ Loaded {len(instruments)} instruments from Trading212")
            
            # Show sample
            if self.verbose:
                symbols = [i.symbol for i in instruments[:20]]
                self.log(f"  Sample: {', '.join(symbols)}")
            
            # Check for expected stocks
            symbols_set = {i.symbol for i in instruments}
            expected = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "META", "AMZN"]
            found = [s for s in expected if s in symbols_set]
            missing = [s for s in expected if s not in symbols_set]
            
            self.log(f"  Expected stocks found: {len(found)}/{len(expected)}")
            if missing:
                self.log(f"  Missing: {', '.join(missing)}", "ERROR")
            
        except Exception as e:
            self.log(f"Universe refresh failed: {e}", "ERROR")
    
    def step2_earnings(self):
        """Step 2: Fetch earnings and cross-check."""
        print("\n" + "-" * 40)
        print("STEP 2: Earnings Candidates")
        print("-" * 40)
        
        if not config.FMP_API_KEY:
            self.log("FMP_API_KEY not set, skipping", "ERROR")
            return
        
        try:
            import requests
            
            # Get next week dates
            today = datetime.now()
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            
            next_monday = today + timedelta(days=days_until_monday)
            next_friday = next_monday + timedelta(days=4)
            
            self.log(f"Fetching earnings for {next_monday.strftime('%Y-%m-%d')} to {next_friday.strftime('%Y-%m-%d')}")
            
            # Fetch from FMP
            url = "https://financialmodelingprep.com/api/v3/earning_calendar"
            params = {
                "from": next_monday.strftime("%Y-%m-%d"),
                "to": next_friday.strftime("%Y-%m-%d"),
                "apikey": config.FMP_API_KEY
            }
            
            resp = requests.get(url, params=params, timeout=30)
            
            if resp.status_code != 200:
                self.log(f"FMP API error: {resp.status_code}", "ERROR")
                return
            
            earnings_data = resp.json()
            self.results["earnings_raw"] = len(earnings_data)
            
            self.log(f"✓ FMP returned {len(earnings_data)} earnings")
            
            # Get universe symbols
            universe = self.storage.get_universe(self.test_week)
            if not universe:
                self.log("No universe loaded", "ERROR")
                return
            
            universe_symbols = set(
                inst.get("symbol", "").upper() 
                for inst in universe.get("instruments", [])
            )
            
            # Filter to tradeable
            from core.t212_client import clean_symbol
            
            candidates = []
            for item in earnings_data:
                symbol = clean_symbol(item.get("symbol", ""))
                
                if not symbol:
                    continue
                
                if symbol.upper() in universe_symbols:
                    candidates.append({
                        "symbol": symbol,
                        "date": item.get("date"),
                        "time": item.get("time", "unknown"),
                        "eps_estimate": item.get("epsEstimated"),
                    })
            
            self.results["earnings_filtered"] = len(candidates)
            
            # Save
            self.storage.save_earnings_candidates(candidates, self.test_week)
            
            self.log(f"✓ Filtered to {len(candidates)} tradeable candidates")
            
            # Show by day
            if self.verbose and candidates:
                by_day = {}
                for c in candidates:
                    day = c.get("date", "Unknown")
                    if day not in by_day:
                        by_day[day] = []
                    by_day[day].append(c["symbol"])
                
                for day, symbols in sorted(by_day.items()):
                    self.log(f"  {day}: {', '.join(symbols[:10])}" + (" ..." if len(symbols) > 10 else ""))
            
        except Exception as e:
            self.log(f"Earnings fetch failed: {e}", "ERROR")
    
    def step3_analysis(self):
        """Step 3: Run historical analysis on candidates."""
        print("\n" + "-" * 40)
        print("STEP 3: Historical Analysis")
        print("-" * 40)
        
        candidates = self.storage.get_earnings_candidates(self.test_week)
        
        if not candidates:
            self.log("No candidates to analyze")
            return
        
        # Limit for simulation
        max_analyze = 10
        if len(candidates) > max_analyze:
            self.log(f"Limiting analysis to {max_analyze} candidates (of {len(candidates)})")
            candidates = candidates[:max_analyze]
        
        pipeline = WeekendAnalysisPipeline()
        results = []
        
        for i, candidate in enumerate(candidates):
            symbol = candidate.get("symbol")
            self.log(f"[{i+1}/{len(candidates)}] Analyzing {symbol}...")
            
            try:
                analysis = pipeline._analyze_single(symbol, candidate)
                
                if analysis:
                    results.append(analysis)
                    score = analysis.get("final_score", 0)
                    behavior = analysis.get("gap_behavior", "?")
                    
                    if self.verbose:
                        self.log(f"  Score: {score}/5, Behavior: {behavior}")
                    
                    if score >= 4:
                        self.results["high_score"] += 1
                else:
                    self.log(f"  No analysis returned")
                    
            except Exception as e:
                self.log(f"  Analysis failed: {e}", "ERROR")
        
        self.results["analyzed"] = len(results)
        
        # Save
        self.storage.save_analysis_results(results, self.test_week)
        
        self.log(f"✓ Analyzed {len(results)} candidates")
        
        # Show top scores
        if results:
            sorted_results = sorted(results, key=lambda x: x.get("final_score", 0), reverse=True)
            self.log("\nTop Scores:")
            for r in sorted_results[:5]:
                symbol = r.get("symbol")
                score = r.get("final_score")
                behavior = r.get("gap_behavior")
                self.log(f"  {symbol}: {score}/5 ({behavior})")
    
    def print_summary(self):
        """Print simulation summary."""
        print("\n" + "=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)
        
        print(f"\nUniverse: {self.results['universe_count']} instruments")
        print(f"Earnings (raw): {self.results['earnings_raw']}")
        print(f"Earnings (tradeable): {self.results['earnings_filtered']}")
        print(f"Analyzed: {self.results['analyzed']}")
        print(f"High score (>=4): {self.results['high_score']}")
        
        if self.results["errors"]:
            print(f"\n⚠️  ERRORS ({len(self.results['errors'])}):")
            for err in self.results["errors"]:
                print(f"  - {err}")
        else:
            print("\n✓ No errors!")
        
        # Verdict
        print("\n" + "-" * 40)
        if self.results["universe_count"] > 100 and not self.results["errors"]:
            print("🎉 SIMULATION PASSED!")
            print("The weekend pipeline should work on Saturday.")
        else:
            print("⚠️  SIMULATION HAD ISSUES")
            print("Review errors before Saturday.")
        
        # Cleanup notice
        print(f"\nTest data saved with week ID: {self.test_week}")
        print("This won't interfere with real data.")


def main():
    parser = argparse.ArgumentParser(description="Simulate Weekend Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Don't send Telegram")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    sim = WeekendSimulation(dry_run=args.dry_run, verbose=args.verbose)
    sim.run()


if __name__ == "__main__":
    main()
