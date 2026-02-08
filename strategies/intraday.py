"""
strategies/gap_fade.py - Gap Fade Strategy

Fades overnight gaps on quality stocks.
Buy gap downs, sell gap ups (mean reversion on gaps).

Schedule:
- Pre-market (9:00 AM): Identify gaps
- Market open: Enter positions
- Same day: Exit by close or when gap fills

Universe: S&P 500 quality stocks with gaps > 3%
"""

import logging
from datetime import datetime, time, timedelta
from typing import List, Dict, Tuple, Optional

import numpy as np
import pandas as pd

import config
from core import market_data
from core.t212_client import clean_symbol
from core.storage import Storage, get_week_id
from strategies.base_strategy import (
    BaseStrategy, StrategyConfig, Signal, SignalType
)

logger = logging.getLogger(__name__)


# Quality stocks for gap fading
GAP_FADE_UNIVERSE = [
    # Large cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "CRM", "ADBE", "ORCL",
    # Finance
    "JPM", "BAC", "GS", "MS", "V", "MA", "BLK", "SCHW",
    # Healthcare
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "TMO", "DHR",
    # Consumer
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NKE",
    # Industrial
    "CAT", "DE", "HON", "GE", "UPS", "FDX", "LMT", "RTX",
    # Sector ETFs (very liquid)
    "SPY", "QQQ", "IWM", "XLK", "XLF", "XLV", "XLE", "XLY",
]


class GapFadeStrategy(BaseStrategy):
    """
    Gap Fade Strategy - Fade overnight gaps.
    
    Logic:
    - Gap DOWN > 3%: BUY (expect bounce)
    - Gap UP > 3%: SELL/SHORT (expect fade)
    
    Entry: 9:00 AM pre-market scan, enter at open
    Exit: Gap fills (50-80%), end of day, or stop loss
    
    Scoring:
    - Gap size (larger = better opportunity)
    - Historical gap fill rate
    - Pre-market volume
    - Overall market direction
    """
    
    def __init__(self):
        cfg = StrategyConfig(
            name="Gap Fade",
            enabled=True,
            check_time=time(9, 0),     # 9:00 AM - 30 min before open
            min_hold_days=0,           # Intraday
            max_hold_days=1,           # Close by end of day
            max_positions=3,
            position_size_pct=0.08     # 8% per position
        )
        super().__init__(cfg)
        
        self.storage = Storage()
        
        # Thresholds
        self.min_gap_pct = 3.0         # Minimum gap to trade
        self.max_gap_pct = 10.0        # Max gap (too risky beyond this)
        self.gap_fill_target = 0.5     # Target 50% gap fill
        self.stop_loss_pct = 3.0       # 3% stop loss
        
        self.score_weights = {
            "gap_size": 0.30,
            "fill_rate": 0.25,
            "volume": 0.25,
            "market_direction": 0.20
        }
    
    def get_universe(self) -> List[str]:
        return GAP_FADE_UNIVERSE
    
    def analyze(self) -> List[Dict]:
        """Weekend: Analyze historical gap fill rates."""
        logger.info(f"[{self.name}] Analyzing historical gap fills...")
        
        results = []
        
        for symbol in self.get_universe():
            data = self._analyze_gap_history(symbol)
            if data:
                results.append(data)
        
        # Save
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        return results
    
    def _analyze_gap_history(self, symbol: str) -> Optional[Dict]:
        """Analyze historical gap fill behavior."""
        symbol = clean_symbol(symbol)
        if not symbol:
            return None
        
        hist = market_data.get_history(symbol, period="3mo")
        if hist is None or len(hist) < 50:
            return None
        
        # Find gaps
        gaps = []
        fills = []
        
        for i in range(1, len(hist)):
            prev_close = hist['Close'].iloc[i-1]
            today_open = hist['Open'].iloc[i]
            today_high = hist['High'].iloc[i]
            today_low = hist['Low'].iloc[i]
            today_close = hist['Close'].iloc[i]
            
            gap_pct = (today_open - prev_close) / prev_close * 100
            
            if abs(gap_pct) >= self.min_gap_pct:
                gaps.append(gap_pct)
                
                # Check if gap filled
                if gap_pct > 0:  # Gap up
                    filled = today_low <= prev_close
                else:  # Gap down
                    filled = today_high >= prev_close
                
                fills.append(1 if filled else 0)
        
        if not gaps:
            return None
        
        return {
            "symbol": symbol,
            "total_gaps": len(gaps),
            "fill_rate": np.mean(fills) if fills else 0,
            "avg_gap_size": np.mean(np.abs(gaps)),
            "avg_volume": hist['Volume'].mean(),
            "analyzed_at": datetime.now().isoformat()
        }
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        from core.utils import safe_json_dump
        filepath = config.DATA_DIR / f"gap_fade_{week_id}.json"
        safe_json_dump({"results": results}, filepath)
    
    def _load_analysis(self) -> Dict[str, Dict]:
        week_id = get_week_id()
        filepath = config.DATA_DIR / f"gap_fade_{week_id}.json"
        import json
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return {r["symbol"]: r for r in data.get("results", [])}
        return {}
    
    def scan(self) -> List[Signal]:
        """Pre-market scan for gaps."""
        logger.info(f"[{self.name}] Scanning for gaps...")
        
        signals = []
        pre_analysis = self._load_analysis()
        
        for symbol in self.get_universe():
            symbol = clean_symbol(symbol)
            if not symbol:
                continue
            
            gap_data = self._check_gap(symbol)
            if not gap_data:
                continue
            
            gap_pct = gap_data.get("gap_pct", 0)
            
            # Check if gap is in tradeable range
            if abs(gap_pct) < self.min_gap_pct or abs(gap_pct) > self.max_gap_pct:
                continue
            
            # Check NO-TRADE
            should_skip, reason = self.check_no_trade(symbol)
            if should_skip:
                continue
            
            # Score
            hist_data = pre_analysis.get(symbol, {})
            score, components = self.score(symbol, {
                "gap_data": gap_data,
                "hist_data": hist_data
            })
            
            if score >= 3:
                # Gap down = BUY, Gap up = could short (but we only go long)
                if gap_pct < 0:  # Gap down - buy the dip
                    signals.append(Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        score=score,
                        strategy=self.name,
                        reason=f"Gap down {gap_pct:.1f}%, expecting bounce",
                        score_components=components,
                        entry_price=gap_data.get("current_price"),
                        stop_loss=gap_data.get("current_price") * (1 - self.stop_loss_pct/100),
                        target_price=gap_data.get("prev_close") * (1 - self.gap_fill_target * abs(gap_pct)/100)
                    ))
        
        return signals
    
    def _check_gap(self, symbol: str) -> Optional[Dict]:
        """Check current gap for a symbol."""
        hist = market_data.get_history(symbol, period="5d")
        if hist is None or len(hist) < 2:
            return None
        
        prev_close = hist['Close'].iloc[-2]
        today_open = hist['Open'].iloc[-1]
        current = hist['Close'].iloc[-1]
        
        gap_pct = (today_open - prev_close) / prev_close * 100
        
        return {
            "prev_close": prev_close,
            "today_open": today_open,
            "current_price": current,
            "gap_pct": gap_pct,
            "volume": hist['Volume'].iloc[-1]
        }
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        components = {}
        
        gap_data = data.get("gap_data", {})
        hist_data = data.get("hist_data", {})
        
        gap_pct = abs(gap_data.get("gap_pct", 0))
        
        # Gap size score (3-5% is sweet spot)
        if 3 <= gap_pct <= 5:
            components["gap_size"] = 1.0
        elif 5 < gap_pct <= 7:
            components["gap_size"] = 0.8
        elif 7 < gap_pct <= 10:
            components["gap_size"] = 0.5
        else:
            components["gap_size"] = 0.3
        
        # Historical fill rate
        fill_rate = hist_data.get("fill_rate", 0.5)
        components["fill_rate"] = fill_rate
        
        # Volume (higher = better)
        volume = gap_data.get("volume", 0)
        avg_vol = hist_data.get("avg_volume", volume)
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1
        
        if vol_ratio >= 2:
            components["volume"] = 1.0
        elif vol_ratio >= 1.5:
            components["volume"] = 0.8
        elif vol_ratio >= 1:
            components["volume"] = 0.6
        else:
            components["volume"] = 0.4
        
        # Market direction (check SPY)
        spy_data = self._check_gap("SPY")
        if spy_data:
            spy_gap = spy_data.get("gap_pct", 0)
            gap_dir = gap_data.get("gap_pct", 0)
            
            # Fading against market is riskier
            if (spy_gap > 0 and gap_dir < 0) or (spy_gap < 0 and gap_dir > 0):
                components["market_direction"] = 0.5  # Counter-trend
            else:
                components["market_direction"] = 0.8  # With market
        else:
            components["market_direction"] = 0.6
        
        return self.calculate_weighted_score(components), components
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        reasons = []
        
        # Check if earnings today
        # (would check earnings calendar)
        
        # Check if already have position
        
        # Check volume
        hist = market_data.get_history(symbol, period="1mo")
        if hist is not None:
            avg_vol = hist['Volume'].mean()
            if avg_vol < 500000:
                reasons.append("Low volume")
        
        if reasons:
            return True, "; ".join(reasons)
        return False, ""
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        entry = position.get("entry_price", 0)
        target = position.get("target_price")
        entry_date = position.get("entry_date")
        
        if not entry:
            return False, ""
        
        current = market_data.get_current_price(symbol)
        if not current:
            return False, ""
        
        pnl_pct = (current - entry) / entry * 100
        
        # Stop loss
        if pnl_pct <= -self.stop_loss_pct:
            return True, f"Stop loss ({pnl_pct:.1f}%)"
        
        # Target reached (gap fill)
        if target and current >= target:
            return True, f"Target reached (gap fill)"
        
        # End of day exit
        import pytz
        ET = pytz.timezone('US/Eastern')
        now = datetime.now(ET)
        if now.hour >= 15 and now.minute >= 45:
            return True, "End of day exit"
        
        return False, ""


class VWAPReversionStrategy(BaseStrategy):
    """
    VWAP Reversion Strategy
    
    Buy when price drops significantly below VWAP.
    Expect mean reversion back to VWAP.
    
    Best for: Range-bound days, high volume stocks
    """
    
    def __init__(self):
        cfg = StrategyConfig(
            name="VWAP Reversion",
            enabled=True,
            check_time=time(10, 0),    # 10:00 AM - after initial volatility
            min_hold_days=0,
            max_hold_days=1,
            max_positions=3,
            position_size_pct=0.06
        )
        super().__init__(cfg)
        
        self.storage = Storage()
        
        # Thresholds
        self.min_deviation_pct = 1.5   # Min % below VWAP to enter
        self.max_deviation_pct = 4.0   # Max (too risky)
        
        self.score_weights = {
            "deviation": 0.35,
            "volume_profile": 0.25,
            "trend": 0.20,
            "market_regime": 0.20
        }
    
    def get_universe(self) -> List[str]:
        # High volume stocks work best for VWAP
        return [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN",
            "META", "GOOGL", "NFLX", "V", "MA", "JPM", "BAC", "XLF", "XLK"
        ]
    
    def analyze(self) -> List[Dict]:
        """Analyze VWAP reversion statistics."""
        results = []
        
        for symbol in self.get_universe():
            hist = market_data.get_history(symbol, period="1mo")
            if hist is None:
                continue
            
            results.append({
                "symbol": symbol,
                "avg_volume": hist['Volume'].mean(),
                "volatility": hist['Close'].pct_change().std() * 100,
                "analyzed_at": datetime.now().isoformat()
            })
        
        return results
    
    def scan(self) -> List[Signal]:
        """Scan for VWAP deviation opportunities."""
        signals = []
        
        for symbol in self.get_universe():
            data = self._check_vwap_deviation(symbol)
            if not data:
                continue
            
            deviation = data.get("deviation_pct", 0)
            
            # Only buy when significantly below VWAP
            if deviation < -self.min_deviation_pct and deviation > -self.max_deviation_pct:
                score, components = self.score(symbol, data)
                
                if score >= 3:
                    signals.append(Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        score=score,
                        strategy=self.name,
                        reason=f"{deviation:.1f}% below VWAP, expecting reversion",
                        score_components=components,
                        entry_price=data.get("current_price"),
                        target_price=data.get("vwap")
                    ))
        
        return signals
    
    def _check_vwap_deviation(self, symbol: str) -> Optional[Dict]:
        """Calculate VWAP and current deviation."""
        hist = market_data.get_history(symbol, period="1d")
        if hist is None or len(hist) < 1:
            return None
        
        # Simplified VWAP calculation (typical price * volume)
        typical_price = (hist['High'] + hist['Low'] + hist['Close']) / 3
        vwap = (typical_price * hist['Volume']).sum() / hist['Volume'].sum()
        
        current = hist['Close'].iloc[-1]
        deviation_pct = (current - vwap) / vwap * 100
        
        return {
            "vwap": vwap,
            "current_price": current,
            "deviation_pct": deviation_pct,
            "volume": hist['Volume'].sum()
        }
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        components = {}
        
        deviation = abs(data.get("deviation_pct", 0))
        
        # Deviation score
        if 1.5 <= deviation <= 2.5:
            components["deviation"] = 1.0
        elif 2.5 < deviation <= 3.5:
            components["deviation"] = 0.8
        else:
            components["deviation"] = 0.5
        
        # Volume profile
        components["volume_profile"] = 0.7  # Simplified
        components["trend"] = 0.6
        components["market_regime"] = 0.6
        
        return self.calculate_weighted_score(components), components
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        return False, ""
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        entry = position.get("entry_price", 0)
        target = position.get("target_price")
        
        if not entry:
            return False, ""
        
        current = market_data.get_current_price(symbol)
        if not current:
            return False, ""
        
        pnl_pct = (current - entry) / entry * 100
        
        if pnl_pct <= -2:
            return True, "Stop loss"
        
        if target and current >= target * 0.98:  # Near VWAP
            return True, "VWAP target reached"
        
        return False, ""


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """
    Opening Range Breakout (ORB) Strategy
    
    Wait for first 15-30 minutes to establish range.
    Trade breakout of that range.
    
    Best for: Trending days, momentum stocks
    """
    
    def __init__(self):
        cfg = StrategyConfig(
            name="ORB",
            enabled=True,
            check_time=time(10, 0),    # 10:00 AM - after opening range
            min_hold_days=0,
            max_hold_days=1,
            max_positions=2,
            position_size_pct=0.08
        )
        super().__init__(cfg)
        
        self.storage = Storage()
        
        self.orb_minutes = 30  # First 30 minutes
        
        self.score_weights = {
            "breakout_strength": 0.35,
            "volume_confirmation": 0.30,
            "trend_alignment": 0.35
        }
    
    def get_universe(self) -> List[str]:
        return [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN",
            "META", "GOOGL", "NFLX", "CRM", "ADBE"
        ]
    
    def analyze(self) -> List[Dict]:
        return []  # ORB is intraday, no weekend analysis needed
    
    def scan(self) -> List[Signal]:
        """Scan for ORB setups after opening range."""
        signals = []
        
        for symbol in self.get_universe():
            orb_data = self._check_orb(symbol)
            if not orb_data:
                continue
            
            if orb_data.get("breakout_direction") == "up":
                score, components = self.score(symbol, orb_data)
                
                if score >= 3:
                    signals.append(Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        score=score,
                        strategy=self.name,
                        reason=f"ORB breakout up, range ${orb_data['range_low']:.2f}-${orb_data['range_high']:.2f}",
                        score_components=components,
                        entry_price=orb_data.get("current_price"),
                        stop_loss=orb_data.get("range_low")
                    ))
        
        return signals
    
    def _check_orb(self, symbol: str) -> Optional[Dict]:
        """Check opening range breakout status."""
        # This would need intraday data
        # Simplified version using daily data
        hist = market_data.get_history(symbol, period="5d")
        if hist is None or len(hist) < 1:
            return None
        
        today = hist.iloc[-1]
        
        # Approximate opening range as first hour's range
        # (In production, would use intraday data)
        range_high = today['Open'] * 1.005  # Approximate
        range_low = today['Open'] * 0.995
        current = today['Close']
        
        breakout_direction = None
        if current > range_high:
            breakout_direction = "up"
        elif current < range_low:
            breakout_direction = "down"
        
        return {
            "range_high": range_high,
            "range_low": range_low,
            "current_price": current,
            "breakout_direction": breakout_direction,
            "volume": today['Volume']
        }
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        components = {}
        
        components["breakout_strength"] = 0.7
        components["volume_confirmation"] = 0.7
        components["trend_alignment"] = 0.6
        
        return self.calculate_weighted_score(components), components
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        return False, ""
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        entry = position.get("entry_price", 0)
        stop = position.get("stop_loss")
        
        if not entry:
            return False, ""
        
        current = market_data.get_current_price(symbol)
        if not current:
            return False, ""
        
        if stop and current < stop:
            return True, "Stop loss (below ORB low)"
        
        pnl_pct = (current - entry) / entry * 100
        if pnl_pct <= -1.5:
            return True, "Stop loss"
        
        return False, ""
