"""
analysis/earnings_executor.py - Earnings Week Execution Logic

Runs during the trading week (Monday-Friday).

Key Principle: Only use data computed during the weekend.
NO RECOMPUTATION of historical analysis during execution.
"""

import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
import pytz

import config
from core.t212_client import T212Client, clean_symbol
from core.storage import Storage, get_week_id
from core.telegram import Telegram
from core import market_data

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


class EarningsExecutor:
    """Earnings week execution engine."""
    
    def __init__(self):
        self.t212 = T212Client(paper=config.PAPER_MODE)
        self.storage = Storage()
        self.telegram = Telegram()
        
        self._processed_today: set = set()
        self._last_date: str = ""
    
    def _reset_daily(self):
        """Reset daily tracking."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_date:
            self._processed_today = set()
            self._last_date = today
    
    # ==================== EARNINGS MONITORING ====================
    
    def get_todays_earnings(self) -> List[Dict]:
        """Get earnings candidates for today."""
        today = datetime.now().strftime("%Y-%m-%d")
        candidates = self.storage.get_earnings_candidates()
        return [c for c in candidates if c.get("date") == today]
    
    def check_earnings_released(self, symbol: str, candidate: Dict) -> Optional[Dict]:
        """Check if earnings have been released."""
        symbol = clean_symbol(symbol)
        if not symbol:
            return None
        
        try:
            # Check news for earnings mention
            news = market_data.get_news(symbol, max_items=5)
            
            for item in news:
                title = item.get("title", "").lower()
                if any(kw in title for kw in ["earnings", "results", "reports", "beats", "misses", "profit"]):
                    return {
                        "released": True,
                        "headline": item.get("title"),
                        "time": datetime.now().isoformat()
                    }
            
            # Check if past expected time
            expected_time = candidate.get("time", "")
            now = datetime.now(ET)
            
            if expected_time == "bmo" and now.time() > time(10, 0):
                return {"released": True, "headline": "Expected (bmo)", "time": now.isoformat()}
            elif expected_time == "amc" and now.time() > time(16, 30):
                return {"released": True, "headline": "Expected (amc)", "time": now.isoformat()}
            
            return None
        except:
            return None
    
    # ==================== NO-TRADE VALIDATION ====================
    
    def check_no_trade_conditions(self, symbol: str) -> Tuple[bool, str]:
        """
        Check NO-TRADE conditions.
        Returns: (should_skip, reason)
        """
        symbol = clean_symbol(symbol)
        if not symbol:
            return True, "Invalid symbol"
        
        reasons = []
        
        try:
            info = market_data.get_info(symbol)
            hist = market_data.get_history(symbol, period="5d")
            
            if info is None:
                return True, "Cannot get stock info"
            
            if hist is None:
                return True, "Cannot get price history"
            
            # 1. Insufficient liquidity
            avg_vol = info.get("averageVolume", 0)
            if avg_vol < config.NO_TRADE_RULES["min_avg_volume"]:
                reasons.append(f"Low volume ({avg_vol:,.0f})")
            
            # 2. Gap already too large
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                current = hist['Close'].iloc[-1]
                gap_pct = abs((current - prev_close) / prev_close * 100)
                
                if gap_pct > config.NO_TRADE_RULES["max_premarket_gap_pct"]:
                    reasons.append(f"Gap too large ({gap_pct:.1f}%)")
            
            # 3. Market cap
            mkt_cap = info.get("marketCap", 0)
            if mkt_cap and mkt_cap < config.NO_TRADE_RULES["min_market_cap"]:
                reasons.append(f"Small market cap (${mkt_cap/1e6:.0f}M)")
            
            # 4. Check precomputed analysis for conflicts
            analysis = self.storage.get_analysis_for_symbol(symbol)
            if analysis:
                score = analysis.get("final_score", 0)
                behavior = analysis.get("gap_behavior", "")
                
                if score <= 2:
                    reasons.append(f"Low score ({score}/5)")
                
                if behavior == "fade" and score < 4:
                    reasons.append("Historical fader")
            
            # 5. Already have position
            if self.t212.get_position(symbol):
                reasons.append("Already have position")
            
        except Exception as e:
            logger.error(f"NO-TRADE check failed for {symbol}: {e}")
            return True, f"Check error: {str(e)}"
        
        if reasons:
            return True, "; ".join(reasons)
        return False, ""
    
    # ==================== TRADE DECISION ====================
    
    def evaluate_trade(self, symbol: str, earnings_data: Dict) -> Tuple[bool, str, int]:
        """
        Evaluate whether to trade.
        
        Uses ONLY precomputed analysis from weekend.
        Returns: (should_trade, reason, score)
        """
        # Get precomputed analysis
        analysis = self.storage.get_analysis_for_symbol(symbol)
        
        if not analysis:
            return False, "No precomputed analysis", 0
        
        score = analysis.get("final_score", 0)
        behavior = analysis.get("gap_behavior", "unknown")
        
        # Check NO-TRADE conditions
        should_skip, skip_reason = self.check_no_trade_conditions(symbol)
        if should_skip:
            return False, skip_reason, score
        
        # Decision logic based on score and behavior
        if score >= 4:
            if behavior == "continuation":
                return True, f"Strong continuation pattern (score {score})", score
            elif behavior == "fade":
                return True, f"Predictable fade pattern (score {score})", score
            else:
                return True, f"High score ({score}) despite mixed pattern", score
        
        elif score == 3:
            if behavior in ["continuation", "fade"]:
                return True, f"Medium score ({score}) with clear pattern", score
            else:
                return False, f"Medium score but unclear pattern", score
        
        else:
            return False, f"Low score ({score})", score
    
    # ==================== EXECUTION ====================
    
    def execute_entry(self, symbol: str, score: int, reason: str) -> bool:
        """Execute trade entry."""
        symbol = clean_symbol(symbol)
        if not symbol:
            return False
        
        try:
            # Get account info
            account = self.t212.get_account()
            if not account:
                logger.error("Cannot get account info")
                return False
            
            # Calculate position size based on score
            base_size = account.free_cash * config.MAX_POSITION_PCT
            multiplier = config.POSITION_SIZE_BY_SCORE.get(score, 0.5)
            position_value = base_size * multiplier
            
            if position_value < 50:
                logger.info(f"Position too small: ${position_value:.2f}")
                return False
            
            # Get current price using safe fetcher
            price = market_data.get_current_price(symbol)
            if not price:
                logger.error(f"Cannot get price for {symbol}")
                return False
            
            quantity = position_value / price
            
            # Execute buy
            result = self.t212.buy(symbol, quantity)
            
            if result:
                # Log trade
                self.storage.log_trade({
                    "action": "BUY",
                    "symbol": symbol,
                    "price": price,
                    "quantity": quantity,
                    "value": position_value,
                    "score": score,
                    "reason": reason
                })
                
                # Track position
                positions = self.storage.get_tracked_positions()
                positions[symbol] = {
                    "entry_price": price,
                    "entry_time": datetime.now().isoformat(),
                    "quantity": quantity,
                    "score": score,
                    "reason": reason,
                    "highest_price": price
                }
                self.storage.save_tracked_positions(positions)
                
                # Notify
                self.telegram.trade_entry(symbol, price, quantity, score, reason)
                
                logger.info(f"✓ Bought {symbol}: {quantity:.4f} @ ${price:.2f}")
                return True
            
        except Exception as e:
            logger.error(f"Failed to execute entry for {symbol}: {e}")
            self.telegram.error("Trade Entry", str(e))
        
        return False
    
    # ==================== POSITION MANAGEMENT ====================
    
    def check_invalidation(self, symbol: str, position_data: Dict) -> Tuple[bool, str]:
        """
        Check if position should be closed (invalidation).
        
        Only close if explicit rule triggered.
        """
        symbol = clean_symbol(symbol)
        if not symbol:
            return False, ""
        
        try:
            entry_price = position_data.get("entry_price", 0)
            highest = position_data.get("highest_price", entry_price)
            entry_time = datetime.fromisoformat(position_data.get("entry_time", datetime.now().isoformat()))
            
            # Get current price using safe fetcher
            current = market_data.get_current_price(symbol)
            if not current:
                return False, ""
            
            # Update highest price
            if current > highest:
                positions = self.storage.get_tracked_positions()
                if symbol in positions:
                    positions[symbol]["highest_price"] = current
                    self.storage.save_tracked_positions(positions)
                highest = current
            
            pnl_pct = ((current - entry_price) / entry_price) * 100
            
            # Rule 1: Max loss (thesis break)
            if pnl_pct <= config.INVALIDATION_RULES["max_loss_pct"]:
                return True, f"Max loss triggered ({pnl_pct:.1f}%)"
            
            # Rule 2: Trailing stop
            if highest > entry_price:
                drop_from_high = ((highest - current) / highest) * 100
                if drop_from_high >= config.INVALIDATION_RULES["trailing_stop_pct"]:
                    return True, f"Trailing stop ({drop_from_high:.1f}% from high)"
            
            # Rule 3: Max hold period
            days_held = (datetime.now() - entry_time).days
            if days_held >= config.INVALIDATION_RULES["max_hold_days"]:
                return True, f"Max hold period ({days_held} days)"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"Invalidation check failed for {symbol}: {e}")
            return False, ""
    
    def manage_positions(self):
        """Check all positions for invalidation."""
        positions = self.storage.get_tracked_positions()
        
        for symbol, data in list(positions.items()):
            should_close, reason = self.check_invalidation(symbol, data)
            
            if should_close:
                self.execute_exit(symbol, reason)
    
    def execute_exit(self, symbol: str, reason: str) -> bool:
        """Execute position exit."""
        try:
            position = self.t212.get_position(symbol)
            tracked = self.storage.get_tracked_positions().get(symbol, {})
            
            if not position:
                # Remove from tracking
                positions = self.storage.get_tracked_positions()
                positions.pop(symbol, None)
                self.storage.save_tracked_positions(positions)
                return True
            
            entry_price = tracked.get("entry_price", position.avg_price)
            
            # Execute sell
            result = self.t212.close_position(symbol)
            
            if result:
                pnl = position.pnl
                pnl_pct = position.pnl_pct
                
                # Log trade
                self.storage.log_trade({
                    "action": "SELL",
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "exit_price": position.current_price,
                    "quantity": position.quantity,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "reason": reason
                })
                
                # Remove from tracking
                positions = self.storage.get_tracked_positions()
                positions.pop(symbol, None)
                self.storage.save_tracked_positions(positions)
                
                # Notify
                self.telegram.trade_exit(symbol, entry_price, position.current_price, pnl, pnl_pct, reason)
                
                logger.info(f"✓ Sold {symbol}: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                return True
                
        except Exception as e:
            logger.error(f"Failed to exit {symbol}: {e}")
        
        return False
    
    # ==================== MAIN LOOP ====================
    
    def run_cycle(self):
        """Run one execution cycle."""
        self._reset_daily()
        
        # 1. Check positions for invalidation (highest priority)
        self.manage_positions()
        
        # 2. Process today's earnings
        if config.EARNINGS_ENABLED:
            todays = self.get_todays_earnings()
            
            for candidate in todays:
                symbol = candidate.get("symbol")
                
                if symbol in self._processed_today:
                    continue
                
                # Check if earnings released
                released = self.check_earnings_released(symbol, candidate)
                
                if released:
                    logger.info(f"Earnings released: {symbol}")
                    
                    # Evaluate trade
                    should_trade, reason, score = self.evaluate_trade(symbol, released)
                    
                    if should_trade:
                        self.execute_entry(symbol, score, reason)
                    else:
                        self.telegram.no_trade(symbol, reason)
                        self.storage.log_execution("NO_TRADE", {
                            "symbol": symbol,
                            "reason": reason,
                            "score": score
                        })
                    
                    self._processed_today.add(symbol)
