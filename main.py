"""
main.py - Trading Bot Main Orchestrator

Schedule:
- Weekend (Sat/Sun): Run analysis pipeline (earnings + strategies)
- Weekday (Mon-Fri): Run execution engine

Priority:
1. Position management (invalidation checks)
2. Earnings execution
3. Non-earnings strategies (once daily per strategy)
"""

import sys
import logging
import time
import argparse
from datetime import datetime, time as dt_time
import pytz

import config
from core.t212_client import T212Client
from core.storage import Storage
from core.telegram import Telegram
from analysis.weekend_pipeline import WeekendAnalysisPipeline
from analysis.earnings_executor import EarningsExecutor
from strategies.manager import StrategyManager

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOGS_DIR / f"bot_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


class TradingBot:
    """Main trading bot orchestrator."""
    
    def __init__(self, paper: bool = True):
        self.paper = paper
        self.t212 = T212Client(paper=paper)
        self.storage = Storage()
        self.telegram = Telegram()
        
        # Earnings
        self.weekend_pipeline = WeekendAnalysisPipeline()
        self.earnings_executor = EarningsExecutor()
        
        # Non-earnings strategies
        self.strategy_manager = StrategyManager(t212_client=self.t212)
        
        self._running = False
    
    def is_weekend(self) -> bool:
        """Check if it's weekend (analysis time)."""
        return datetime.now().weekday() in config.ANALYSIS_DAYS
    
    def is_market_hours(self) -> bool:
        """Check if US market is open."""
        now = datetime.now(ET)
        if now.weekday() >= 5:
            return False
        return config.MARKET_OPEN <= now.time() <= config.MARKET_CLOSE
    
    def is_pre_market(self) -> bool:
        """Check if pre-market."""
        now = datetime.now(ET)
        if now.weekday() >= 5:
            return False
        return config.PRE_MARKET_START <= now.time() < config.MARKET_OPEN
    
    # ==================== WEEKEND LOGIC ====================
    
    def run_weekend_analysis(self):
        """Run weekend analysis pipeline for ALL strategies."""
        logger.info("=" * 60)
        logger.info("WEEKEND ANALYSIS MODE")
        logger.info("=" * 60)
        
        # 1. Earnings analysis
        logger.info("\n>>> EARNINGS ANALYSIS")
        self.weekend_pipeline.run_full_pipeline()
        
        # 2. Non-earnings strategies analysis
        logger.info("\n>>> STRATEGY ANALYSIS")
        self.strategy_manager.run_weekend_analysis()
    
    # ==================== WEEKDAY LOGIC ====================
    
    def run_execution_cycle(self):
        """Run one execution cycle during trading hours."""
        try:
            # Priority 1: Check strategy invalidations
            self.strategy_manager.check_all_invalidations()
            
            # Priority 2: Earnings execution
            self.earnings_executor.run_cycle()
            
            # Priority 3: Non-earnings strategy scans
            self.strategy_manager.run_cycle()
            
        except Exception as e:
            logger.error(f"Execution cycle error: {e}")
            self.telegram.error("Execution Cycle", str(e))
    
    def run_daily_non_earnings(self):
        """Run non-earnings strategies once per day."""
        self.strategy_manager.run_daily_scans()
    
    # ==================== MAIN LOOP ====================
    
    def run(self):
        """Main bot loop."""
        logger.info("=" * 60)
        logger.info("TRADING BOT STARTING")
        logger.info(f"Mode: {'PAPER' if self.paper else 'LIVE'}")
        logger.info(f"Time: {datetime.now()}")
        logger.info("=" * 60)
        
        # Test connection
        if not self.t212.test_connection():
            logger.error("Failed to connect to Trading212")
            return
        
        # Start news monitoring
        logger.info("Starting news monitoring...")
        self.strategy_manager.start_news_monitoring()
        
        self._running = True
        last_daily_run = None
        
        try:
            while self._running:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                
                if self.is_weekend():
                    # Weekend: run analysis once
                    if last_daily_run != today:
                        self.run_weekend_analysis()
                        last_daily_run = today
                    
                    # Sleep longer on weekends
                    time.sleep(3600)  # 1 hour
                    
                else:
                    # Weekday: execution mode
                    if self.is_market_hours() or self.is_pre_market():
                        self.run_execution_cycle()
                        time.sleep(config.MARKET_CHECK_INTERVAL)
                    else:
                        # Outside market hours
                        # Run daily summary at market close
                        now_et = datetime.now(ET)
                        if now_et.time() >= dt_time(16, 5) and last_daily_run != today:
                            self.send_daily_summary()
                            last_daily_run = today
                        
                        time.sleep(config.OFF_MARKET_CHECK_INTERVAL)
                        
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.telegram.error("Bot Main Loop", str(e))
        finally:
            # Stop news monitoring
            self.strategy_manager.stop_news_monitoring()
            self._running = False
    
    def send_daily_summary(self):
        """Send daily summary."""
        try:
            # Get today's trades
            trades = self.storage.get_trades()
            
            total_pnl = sum(t.get("pnl", 0) for t in trades if t.get("action") == "SELL")
            trade_count = len([t for t in trades if t.get("action") == "BUY"])
            
            positions = self.t212.get_positions()
            
            self.telegram.daily_summary(total_pnl, trade_count, len(positions))
            
        except Exception as e:
            logger.error(f"Daily summary error: {e}")
    
    def stop(self):
        """Stop the bot."""
        self._running = False


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="Trading212 Bot")
    parser.add_argument("--live", action="store_true", help="Run in LIVE mode")
    parser.add_argument("--status", action="store_true", help="Check connection status")
    parser.add_argument("--positions", action="store_true", help="Show positions")
    parser.add_argument("--weekend", action="store_true", help="Run weekend analysis now")
    parser.add_argument("--test", action="store_true", help="Run tests")
    
    args = parser.parse_args()
    
    paper = not args.live
    
    if args.status:
        t212 = T212Client(paper=paper)
        if t212.test_connection():
            print("✓ Connection OK")
            account = t212.get_account()
            print(f"  Cash: {account.currency} {account.free_cash:,.2f}")
            print(f"  Invested: {account.currency} {account.invested:,.2f}")
            print(f"  Total: {account.currency} {account.total_value:,.2f}")
        else:
            print("✗ Connection failed")
        return
    
    if args.positions:
        t212 = T212Client(paper=paper)
        positions = t212.get_positions()
        if positions:
            print(f"\nPositions ({len(positions)}):")
            for p in positions:
                emoji = "🟢" if p.pnl >= 0 else "🔴"
                print(f"  {emoji} {p.symbol}: {p.quantity:.4f} @ ${p.current_price:.2f} ({p.pnl_pct:+.1f}%)")
        else:
            print("No open positions")
        return
    
    if args.weekend:
        pipeline = WeekendAnalysisPipeline()
        pipeline.run_full_pipeline()
        return
    
    if args.test:
        print("Running tests...")
        from tests.test_runner import run_all_tests
        run_all_tests()
        return
    
    # Run main bot
    bot = TradingBot(paper=paper)
    bot.run()


if __name__ == "__main__":
    main()
