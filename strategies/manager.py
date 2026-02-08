"""
strategies/manager.py - Strategy Manager

Orchestrates all non-earnings strategies:
1. Sector Momentum (9:00 AM pre-market)
2. Mean Reversion (9:00 AM pre-market)
3. Breakout (9:00 AM pre-market)
4. Gap Fade (9:00 AM pre-market)
5. VWAP Reversion (10:00 AM)
6. ORB (10:00 AM)

Schedule:
- Weekend: Run analyze() for all strategies
- Pre-market (9:00 AM): Run scan() for swing strategies
- Intraday (10:00 AM): Run scan() for intraday strategies
- Continuous: Check invalidation for open positions
- Continuous: Monitor news for position impact
"""

import logging
from datetime import datetime, time
from typing import List, Dict, Optional
import pytz

import config
from core.storage import Storage, get_week_id
from core.telegram import Telegram
from core.t212_client import T212Client
from core.news_monitor import NewsMonitor
from core import market_data

from strategies.base_strategy import Signal, SignalType
from strategies.sector_momentum import SectorMomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.intraday import GapFadeStrategy, VWAPReversionStrategy, OpeningRangeBreakoutStrategy
from strategies.rsi_divergence import RSIDivergenceStrategy
from strategies.volume_spike import VolumeSpikeStrategy

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


class StrategyManager:
    """
    Manages all non-earnings strategies.
    
    Responsibilities:
    1. Run weekend analysis for all strategies
    2. Run pre-market scans (9:00 AM)
    3. Run intraday scans (10:00 AM)
    4. Track positions per strategy
    5. Check invalidation rules
    6. Monitor news for position impact
    7. Execute trades
    """
    
    def __init__(self, t212_client: T212Client = None):
        self.t212 = t212_client or T212Client(paper=config.PAPER_MODE)
        self.storage = Storage()
        self.telegram = Telegram()
        
        # News monitor for real-time updates
        self.news_monitor = NewsMonitor()
        
        # Initialize all strategies (with updated times)
        self.strategies = {
            # Pre-market strategies (9:00 AM)
            "sector_momentum": SectorMomentumStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "breakout": BreakoutStrategy(),
            "gap_fade": GapFadeStrategy(),
            
            # Intraday strategies (10:00 AM)
            "vwap_reversion": VWAPReversionStrategy(),
            "orb": OpeningRangeBreakoutStrategy(),
            
            # Swing strategies (9:00 AM)
            "rsi_divergence": RSIDivergenceStrategy(),
            "volume_spike": VolumeSpikeStrategy(),
        }
        
        # Update check times to pre-market for swing strategies
        self.strategies["sector_momentum"].config.check_time = time(9, 0)
        self.strategies["mean_reversion"].config.check_time = time(9, 0)
        self.strategies["breakout"].config.check_time = time(9, 0)
        self.strategies["rsi_divergence"].config.check_time = time(9, 0)
        self.strategies["volume_spike"].config.check_time = time(9, 0)
        
        # Track which strategies have been scanned today
        self._scanned_today: Dict[str, str] = {}  # strategy -> date
        
        logger.info(f"Strategy Manager initialized with {len(self.strategies)} strategies")
        for name, strategy in self.strategies.items():
            logger.info(f"  - {name}: {strategy.config.check_time}")
    
    # ==================== WEEKEND ANALYSIS ====================
    
    def run_weekend_analysis(self):
        """
        Run weekend analysis for all strategies.
        Called on Saturday/Sunday.
        """
        logger.info("=" * 60)
        logger.info("STRATEGY MANAGER: Weekend Analysis")
        logger.info("=" * 60)
        
        results = {}
        
        for name, strategy in self.strategies.items():
            if not strategy.enabled:
                logger.info(f"[{name}] Skipped (disabled)")
                continue
            
            try:
                logger.info(f"\n[{name}] Running analysis...")
                analysis = strategy.analyze()
                results[name] = {
                    "count": len(analysis),
                    "top_signals": analysis[:5] if analysis else []
                }
                logger.info(f"[{name}] Completed: {len(analysis)} results")
                
            except Exception as e:
                logger.error(f"[{name}] Analysis failed: {e}")
                results[name] = {"error": str(e)}
        
        # Send summary
        self._send_weekend_summary(results)
        
        return results
    
    def _send_weekend_summary(self, results: Dict):
        """Send Telegram summary of weekend analysis."""
        msg = "🔬 <b>Weekend Analysis Complete</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        
        for name, data in results.items():
            if "error" in data:
                msg += f"❌ {name}: {data['error'][:50]}\n"
            else:
                msg += f"✓ {name}: {data['count']} analyzed\n"
        
        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        self.telegram.send(msg)
    
    # ==================== DAILY SCAN ====================
    
    def run_daily_scans(self) -> List[Signal]:
        """
        Run daily scans for strategies at their check times.
        Returns all signals generated.
        """
        all_signals = []
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now(ET)
        
        for name, strategy in self.strategies.items():
            if not strategy.enabled:
                continue
            
            # Check if already scanned today
            if self._scanned_today.get(name) == today:
                continue
            
            # Check if it's time for this strategy
            if not self._is_scan_time(strategy, now):
                continue
            
            try:
                logger.info(f"[{name}] Running daily scan...")
                signals = strategy.scan()
                
                if signals:
                    all_signals.extend(signals)
                    self._send_signals_alert(name, signals)
                
                self._scanned_today[name] = today
                logger.info(f"[{name}] Generated {len(signals)} signals")
                
            except Exception as e:
                logger.error(f"[{name}] Scan failed: {e}")
        
        return all_signals
    
    def _is_scan_time(self, strategy, now: datetime) -> bool:
        """Check if it's time to run this strategy's scan."""
        check_time = strategy.config.check_time
        check_minutes = check_time.hour * 60 + check_time.minute
        now_minutes = now.hour * 60 + now.minute
        
        # Run if within 30 minute window after check time
        return 0 <= (now_minutes - check_minutes) <= 30
    
    def _send_signals_alert(self, strategy_name: str, signals: List[Signal]):
        """Send Telegram alert for new signals."""
        if not signals:
            return
        
        msg = f"📊 <b>{strategy_name} Signals</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        
        for s in signals[:5]:  # Max 5 signals
            emoji = "🟢" if s.signal_type == SignalType.BUY else "🔴"
            msg += f"{emoji} <b>{s.symbol}</b>: Score {s.score}/5\n"
            msg += f"   {s.reason[:50]}\n"
        
        if len(signals) > 5:
            msg += f"\n... and {len(signals) - 5} more"
        
        self.telegram.send(msg)
    
    # ==================== POSITION MANAGEMENT ====================
    
    def check_all_invalidations(self) -> List[Dict]:
        """
        Check invalidation rules for all strategy positions.
        Returns list of positions to close.
        """
        to_close = []
        
        # Load tracked positions
        positions = self._load_strategy_positions()
        
        for symbol, pos_data in positions.items():
            strategy_name = pos_data.get("strategy")
            strategy = self.strategies.get(strategy_name)
            
            if not strategy:
                continue
            
            try:
                should_close, reason = strategy.check_invalidation(symbol, pos_data)
                
                if should_close:
                    to_close.append({
                        "symbol": symbol,
                        "strategy": strategy_name,
                        "reason": reason,
                        "position": pos_data
                    })
                    logger.info(f"[{strategy_name}] INVALIDATION {symbol}: {reason}")
                    
            except Exception as e:
                logger.error(f"Invalidation check failed for {symbol}: {e}")
        
        return to_close
    
    def _load_strategy_positions(self) -> Dict[str, Dict]:
        """Load positions tracked by strategies."""
        filepath = config.DATA_DIR / "strategy_positions.json"
        
        import json
        if filepath.exists():
            with open(filepath) as f:
                return json.load(f)
        return {}
    
    def save_strategy_position(self, symbol: str, strategy: str, data: Dict):
        """Save a new strategy position."""
        positions = self._load_strategy_positions()
        
        positions[symbol] = {
            "strategy": strategy,
            "entry_price": data.get("entry_price"),
            "entry_date": datetime.now().isoformat(),
            "highest_price": data.get("entry_price"),
            "score": data.get("score"),
            "reason": data.get("reason"),
        }
        
        filepath = config.DATA_DIR / "strategy_positions.json"
        from core.utils import safe_json_dump
        safe_json_dump(positions, filepath)
    
    def remove_strategy_position(self, symbol: str):
        """Remove a strategy position after closing."""
        positions = self._load_strategy_positions()
        positions.pop(symbol, None)
        
        filepath = config.DATA_DIR / "strategy_positions.json"
        from core.utils import safe_json_dump
        safe_json_dump(positions, filepath)
    
    # ==================== EXECUTION ====================
    
    def execute_signals(self, signals: List[Signal]) -> List[Dict]:
        """
        Execute trading signals.
        Returns list of executed trades.
        """
        executed = []
        
        for signal in signals:
            if signal.signal_type != SignalType.BUY:
                continue
            
            # Check if we already have a position
            positions = self._load_strategy_positions()
            if signal.symbol in positions:
                logger.info(f"Already have position in {signal.symbol}")
                continue
            
            # Check max positions per strategy
            strategy = self.strategies.get(signal.strategy.lower().replace(" ", "_"))
            if strategy:
                current_count = sum(1 for p in positions.values() 
                                   if p.get("strategy") == signal.strategy)
                if current_count >= strategy.config.max_positions:
                    logger.info(f"Max positions reached for {signal.strategy}")
                    continue
            
            # Execute trade
            result = self._execute_buy(signal)
            
            if result:
                executed.append(result)
                self.save_strategy_position(signal.symbol, signal.strategy, {
                    "entry_price": result.get("price"),
                    "score": signal.score,
                    "reason": signal.reason
                })
        
        return executed
    
    def _execute_buy(self, signal: Signal) -> Optional[Dict]:
        """Execute a buy order."""
        try:
            # Get account info
            account = self.t212.get_account()
            if not account:
                return None
            
            # Calculate position size
            strategy = self.strategies.get(signal.strategy.lower().replace(" ", "_"))
            if strategy:
                pos_size_pct = strategy.config.position_size_pct
            else:
                pos_size_pct = 0.10
            
            # Adjust by score
            score_mult = config.POSITION_SIZE_BY_SCORE.get(signal.score, 0.5)
            position_value = account.free_cash * pos_size_pct * score_mult
            
            if position_value < 50:
                logger.info(f"Position too small: ${position_value:.2f}")
                return None
            
            # Get price
            price = signal.entry_price or market_data.get_current_price(signal.symbol)
            if not price:
                return None
            
            quantity = position_value / price
            
            # Execute
            result = self.t212.buy(signal.symbol, quantity)
            
            if result:
                # Notify
                self.telegram.send(
                    f"🟢 <b>BUY {signal.symbol}</b>\n"
                    f"Strategy: {signal.strategy}\n"
                    f"Price: ${price:.2f}\n"
                    f"Qty: {quantity:.4f}\n"
                    f"Score: {signal.score}/5\n"
                    f"Reason: {signal.reason}"
                )
                
                return {
                    "symbol": signal.symbol,
                    "strategy": signal.strategy,
                    "price": price,
                    "quantity": quantity,
                    "score": signal.score
                }
                
        except Exception as e:
            logger.error(f"Execute buy failed: {e}")
        
        return None
    
    def execute_close(self, symbol: str, reason: str) -> bool:
        """Close a position."""
        try:
            result = self.t212.close_position(symbol)
            
            if result:
                positions = self._load_strategy_positions()
                pos_data = positions.get(symbol, {})
                
                # Get exit details
                current = market_data.get_current_price(symbol)
                entry = pos_data.get("entry_price", current)
                pnl = (current - entry) if current and entry else 0
                pnl_pct = (pnl / entry * 100) if entry else 0
                
                # Notify
                emoji = "📈" if pnl >= 0 else "📉"
                self.telegram.send(
                    f"🔴 <b>SELL {symbol}</b>\n"
                    f"Strategy: {pos_data.get('strategy', 'Unknown')}\n"
                    f"Entry: ${entry:.2f}\n"
                    f"Exit: ${current:.2f}\n"
                    f"{emoji} P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
                    f"Reason: {reason}"
                )
                
                # Remove from tracking
                self.remove_strategy_position(symbol)
                
                return True
                
        except Exception as e:
            logger.error(f"Execute close failed: {e}")
        
        return False
    
    # ==================== MAIN RUN CYCLE ====================
    
    def run_cycle(self):
        """
        Run one cycle of strategy management.
        Called from main bot loop.
        """
        # 1. Check news for all positions (highest priority)
        self._check_news_impact()
        
        # 2. Check invalidations
        to_close = self.check_all_invalidations()
        
        for item in to_close:
            self.execute_close(item["symbol"], item["reason"])
        
        # 3. Run daily scans (pre-market and intraday)
        signals = self.run_daily_scans()
        
        # 4. Execute signals
        if signals:
            self.execute_signals(signals)
    
    def _check_news_impact(self):
        """Check if news affects any open positions."""
        positions = self._load_strategy_positions()
        
        if not positions:
            return
        
        # Add all position symbols to watchlist
        self.news_monitor.add_to_watchlist(list(positions.keys()))
        
        # Check each position for news impact
        for symbol, pos_data in positions.items():
            impact = self.news_monitor.check_position_news(symbol, pos_data)
            
            if impact and impact.get("urgency") == "high":
                logger.warning(f"HIGH URGENCY NEWS for {symbol}: {impact.get('reason')}")
                
                # Alert via Telegram
                self.telegram.send(
                    f"⚠️ <b>NEWS ALERT: {symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{impact.get('reason', 'Material news detected')}\n"
                    f"Action: Review position immediately"
                )
    
    def start_news_monitoring(self):
        """Start background news monitoring."""
        # Add current positions to watchlist
        positions = self._load_strategy_positions()
        if positions:
            self.news_monitor.add_to_watchlist(list(positions.keys()))
        
        # Start monitoring
        self.news_monitor.start_monitoring()
    
    def stop_news_monitoring(self):
        """Stop background news monitoring."""
        self.news_monitor.stop_monitoring()
    
    # ==================== STATUS ====================
    
    def get_status(self) -> Dict:
        """Get status of all strategies."""
        positions = self._load_strategy_positions()
        
        status = {
            "strategies": {},
            "total_positions": len(positions),
            "positions": positions
        }
        
        for name, strategy in self.strategies.items():
            strategy_positions = [s for s, p in positions.items() 
                                 if p.get("strategy") == name]
            
            status["strategies"][name] = {
                "enabled": strategy.enabled,
                "check_time": str(strategy.config.check_time),
                "max_positions": strategy.config.max_positions,
                "current_positions": len(strategy_positions),
                "scanned_today": self._scanned_today.get(name) == datetime.now().strftime("%Y-%m-%d")
            }
        
        return status


# ==================== CLI ====================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
    
    manager = StrategyManager()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "analyze":
            manager.run_weekend_analysis()
        elif cmd == "scan":
            signals = manager.run_daily_scans()
            print(f"\nGenerated {len(signals)} total signals")
        elif cmd == "status":
            from core.utils import safe_json_dumps
            print(safe_json_dumps(manager.get_status()))
        elif cmd == "check":
            to_close = manager.check_all_invalidations()
            print(f"\n{len(to_close)} positions to close")
            for item in to_close:
                print(f"  {item['symbol']}: {item['reason']}")
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python -m strategies.manager [analyze|scan|status|check]")
    else:
        print("Strategy Manager")
        print("=" * 40)
        print("Commands:")
        print("  analyze  - Run weekend analysis")
        print("  scan     - Run daily scans")
        print("  status   - Show status")
        print("  check    - Check invalidations")
