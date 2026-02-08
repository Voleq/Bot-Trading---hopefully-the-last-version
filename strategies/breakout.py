"""
strategies/breakout.py - New Highs Breakout Strategy

Buys stocks breaking out to new 52-week highs with volume confirmation.
Momentum following strategy.

Schedule:
- Weekend: Identify stocks near 52-week highs
- Daily: Scan for breakouts at 10:30 AM
- Exit: 10% trailing stop

Universe: Mid/Large caps in T212 universe
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


# Mid/Large cap universe for breakouts
BREAKOUT_UNIVERSE = [
    # Tech leaders
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "CRM", "ADBE", "ORCL",
    "AMD", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL", "SNPS", "CDNS", "PANW", "NOW",
    
    # Growth tech
    "CRWD", "ZS", "DDOG", "NET", "SNOW", "MDB", "TEAM", "HUBS", "VEEV", "WDAY",
    
    # Finance
    "V", "MA", "JPM", "GS", "MS", "BLK", "SCHW", "CME", "ICE", "SPGI",
    
    # Healthcare
    "UNH", "LLY", "NVO", "ISRG", "DXCM", "IDXX", "EW", "SYK", "BSX", "MDT",
    
    # Consumer
    "COST", "HD", "MCD", "SBUX", "NKE", "LULU", "CMG", "DPZ", "ORLY", "AZO",
    
    # Industrial
    "CAT", "DE", "GE", "HON", "ETN", "PH", "ROK", "EMR", "ITW", "WM",
    
    # Sector ETFs
    "XLK", "XLV", "XLF", "XLY", "XLI", "XLE",
]


class BreakoutStrategy(BaseStrategy):
    """
    Breakout strategy - buy new 52-week highs with volume.
    
    Entry Conditions:
    - Price within 2% of 52-week high
    - Volume > 1.5x average
    - RSI > 50 (momentum)
    - Sector in uptrend
    
    Exit Conditions:
    - 10% trailing stop
    - Close below 20 SMA
    - 30 days max hold
    
    Scoring Components:
    - Distance to high (30%)
    - Volume surge (25%)
    - RSI momentum (25%)
    - Sector strength (20%)
    """
    
    def __init__(self):
        cfg = StrategyConfig(
            name="Breakout",
            enabled=True,
            check_time=time(10, 30),   # 10:30 AM ET
            min_hold_days=3,
            max_hold_days=30,
            max_positions=5,
            position_size_pct=0.10     # 10% per position
        )
        super().__init__(cfg)
        
        self.storage = Storage()
        
        # Score weights
        self.score_weights = {
            "proximity_to_high": 0.30,
            "volume_surge": 0.25,
            "momentum": 0.25,
            "sector_strength": 0.20
        }
        
        # Thresholds
        self.max_pct_from_high = 2.0    # Within 2% of high
        self.min_volume_ratio = 1.5     # 1.5x average volume
    
    def get_universe(self) -> List[str]:
        """Breakout candidates."""
        return BREAKOUT_UNIVERSE
    
    # ==================== WEEKEND ANALYSIS ====================
    
    def analyze(self) -> List[Dict]:
        """
        Weekend analysis: Identify stocks near 52-week highs.
        """
        logger.info(f"[{self.name}] Running weekend analysis...")
        
        results = []
        
        for symbol in self.get_universe():
            try:
                data = self._analyze_stock(symbol)
                if data:
                    results.append(data)
            except Exception as e:
                logger.debug(f"Error analyzing {symbol}: {e}")
        
        # Sort by proximity to high
        results.sort(key=lambda x: x.get("pct_from_high", 100))
        
        # Save
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        # Log watchlist
        watchlist = [r for r in results if r.get("pct_from_high", 100) <= 5]
        logger.info(f"[{self.name}] {len(watchlist)} stocks within 5% of 52-week high:")
        for r in watchlist[:10]:
            logger.info(f"  {r['symbol']}: {r['pct_from_high']:.1f}% from high")
        
        return results
    
    def _analyze_stock(self, symbol: str) -> Optional[Dict]:
        """Analyze stock for breakout potential."""
        symbol = clean_symbol(symbol)
        if not symbol:
            return None
        
        hist = market_data.get_history(symbol, period="1y")
        if hist is None or len(hist) < 200:
            return None
        
        close = hist['Close']
        high = hist['High']
        volume = hist['Volume']
        
        # 52-week high
        high_52w = high.max()
        current = close.iloc[-1]
        pct_from_high = (high_52w - current) / high_52w * 100
        
        # Volume metrics
        avg_volume = volume.iloc[-20:].mean()
        recent_volume = volume.iloc[-5:].mean()
        
        # RSI
        rsi = self._calculate_rsi(close)
        
        # Trend (above 20 and 50 SMA)
        sma20 = close.rolling(20).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        
        return {
            "symbol": symbol,
            "current_price": current,
            "high_52w": high_52w,
            "pct_from_high": pct_from_high,
            "rsi": rsi,
            "above_sma20": current > sma20,
            "above_sma50": current > sma50,
            "sma20": sma20,
            "avg_volume": avg_volume,
            "recent_volume": recent_volume,
            "volume_ratio": recent_volume / avg_volume if avg_volume > 0 else 1,
            "in_uptrend": current > sma20 > sma50,
            "analyzed_at": datetime.now().isoformat()
        }
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI."""
        try:
            delta = prices.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        except:
            return 50
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        """Save analysis results."""
        from core.utils import safe_json_dump
        filepath = config.DATA_DIR / f"breakout_{week_id}.json"
        
        safe_json_dump({
            "week_id": week_id,
            "strategy": self.name,
            "analyzed_at": datetime.now().isoformat(),
            "results": results
        }, filepath)
    
    def _load_analysis(self, week_id: str = None) -> Dict[str, Dict]:
        """Load precomputed analysis."""
        week_id = week_id or get_week_id()
        filepath = config.DATA_DIR / f"breakout_{week_id}.json"
        
        import json
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return {r["symbol"]: r for r in data.get("results", [])}
        return {}
    
    # ==================== DAILY SCAN ====================
    
    def scan(self) -> List[Signal]:
        """
        Daily scan for breakout setups.
        """
        logger.info(f"[{self.name}] Running daily scan...")
        
        signals = []
        
        # Load weekend analysis
        pre_analysis = self._load_analysis()
        
        if not pre_analysis:
            self.analyze()
            pre_analysis = self._load_analysis()
        
        # Get sector strength
        sector_strength = self._get_sector_strength()
        
        for symbol in self.get_universe():
            symbol = clean_symbol(symbol)
            if not symbol:
                continue
            
            pre_data = pre_analysis.get(symbol, {})
            
            # Skip if not near high (from weekend analysis)
            if pre_data.get("pct_from_high", 100) > 10:
                continue
            
            # Check current breakout conditions
            breakout_data = self._check_breakout(symbol)
            
            if not breakout_data:
                continue
            
            if not breakout_data.get("is_breakout"):
                continue
            
            # Check NO-TRADE conditions
            should_skip, skip_reason = self.check_no_trade(symbol)
            if should_skip:
                logger.info(f"[{self.name}] SKIP {symbol}: {skip_reason}")
                continue
            
            # Calculate score
            score, components = self.score(symbol, {
                "pre_data": pre_data,
                "breakout_data": breakout_data,
                "sector_strength": sector_strength
            })
            
            if score >= 3:
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    score=score,
                    strategy=self.name,
                    reason=f"Breaking out: {breakout_data['pct_from_high']:.1f}% from 52W high, {breakout_data['volume_ratio']:.1f}x volume",
                    score_components=components,
                    entry_price=breakout_data.get("price"),
                    stop_loss=breakout_data.get("price") * 0.90  # 10% stop
                ))
        
        logger.info(f"[{self.name}] Generated {len(signals)} signals")
        return signals
    
    def _check_breakout(self, symbol: str) -> Optional[Dict]:
        """Check if stock is breaking out now."""
        hist = market_data.get_history(symbol, period="1y")
        
        if hist is None or len(hist) < 200:
            return None
        
        close = hist['Close']
        high = hist['High']
        volume = hist['Volume']
        
        current = close.iloc[-1]
        high_52w = high.max()
        pct_from_high = (high_52w - current) / high_52w * 100
        
        # Volume ratio
        today_volume = volume.iloc[-1]
        avg_volume = volume.iloc[-20:-1].mean()
        volume_ratio = today_volume / avg_volume if avg_volume > 0 else 1
        
        # RSI
        rsi = self._calculate_rsi(close)
        
        # SMA
        sma20 = close.rolling(20).mean().iloc[-1]
        
        # Is it a breakout?
        is_breakout = (
            pct_from_high <= self.max_pct_from_high and
            volume_ratio >= self.min_volume_ratio and
            rsi > 50 and
            current > sma20
        )
        
        return {
            "price": current,
            "high_52w": high_52w,
            "pct_from_high": pct_from_high,
            "volume_ratio": volume_ratio,
            "rsi": rsi,
            "sma20": sma20,
            "is_breakout": is_breakout
        }
    
    def _get_sector_strength(self) -> Dict[str, float]:
        """Get sector ETF strengths."""
        sectors = ["XLK", "XLV", "XLF", "XLY", "XLI", "XLE", "XLC", "XLU", "XLB", "XLRE", "XLP"]
        strength = {}
        
        spy_hist = market_data.get_history("SPY", period="1mo")
        spy_return = 0
        if spy_hist is not None:
            spy_return = (spy_hist['Close'].iloc[-1] / spy_hist['Close'].iloc[0] - 1) * 100
        
        for sector in sectors:
            hist = market_data.get_history(sector, period="1mo")
            if hist is not None:
                ret = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                strength[sector] = ret - spy_return  # Relative strength
            else:
                strength[sector] = 0
        
        return strength
    
    def _get_stock_sector(self, symbol: str) -> str:
        """Map stock to sector ETF (simplified)."""
        tech = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AMD", "CRM", "ADBE", "ORCL",
                "AVGO", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL", "SNPS", "CDNS", "PANW", "NOW",
                "CRWD", "ZS", "DDOG", "NET", "SNOW", "MDB", "TEAM", "HUBS", "VEEV", "WDAY"]
        finance = ["V", "MA", "JPM", "GS", "MS", "BLK", "SCHW", "CME", "ICE", "SPGI"]
        healthcare = ["UNH", "LLY", "NVO", "ISRG", "DXCM", "IDXX", "EW", "SYK", "BSX", "MDT"]
        consumer = ["COST", "HD", "MCD", "SBUX", "NKE", "LULU", "CMG", "DPZ", "ORLY", "AZO"]
        industrial = ["CAT", "DE", "GE", "HON", "ETN", "PH", "ROK", "EMR", "ITW", "WM"]
        
        if symbol in tech:
            return "XLK"
        elif symbol in finance:
            return "XLF"
        elif symbol in healthcare:
            return "XLV"
        elif symbol in consumer:
            return "XLY"
        elif symbol in industrial:
            return "XLI"
        else:
            return "SPY"
    
    # ==================== SCORING ====================
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        """Calculate score for breakout setup."""
        components = {}
        
        breakout_data = data.get("breakout_data", {})
        sector_strength = data.get("sector_strength", {})
        
        # 1. Proximity to high (closer = better)
        pct_from_high = breakout_data.get("pct_from_high", 10)
        
        if pct_from_high <= 1:
            components["proximity_to_high"] = 1.0
        elif pct_from_high <= 2:
            components["proximity_to_high"] = 0.9
        elif pct_from_high <= 3:
            components["proximity_to_high"] = 0.7
        elif pct_from_high <= 5:
            components["proximity_to_high"] = 0.5
        else:
            components["proximity_to_high"] = 0.3
        
        # 2. Volume surge
        vol_ratio = breakout_data.get("volume_ratio", 1)
        
        if vol_ratio >= 3:
            components["volume_surge"] = 1.0
        elif vol_ratio >= 2:
            components["volume_surge"] = 0.8
        elif vol_ratio >= 1.5:
            components["volume_surge"] = 0.6
        else:
            components["volume_surge"] = 0.4
        
        # 3. Momentum (RSI)
        rsi = breakout_data.get("rsi", 50)
        
        if rsi >= 70:
            components["momentum"] = 0.9
        elif rsi >= 60:
            components["momentum"] = 0.8
        elif rsi >= 50:
            components["momentum"] = 0.6
        else:
            components["momentum"] = 0.3
        
        # 4. Sector strength
        sector = self._get_stock_sector(symbol)
        sector_rs = sector_strength.get(sector, 0)
        
        if sector_rs > 3:
            components["sector_strength"] = 1.0
        elif sector_rs > 1:
            components["sector_strength"] = 0.8
        elif sector_rs > -1:
            components["sector_strength"] = 0.6
        else:
            components["sector_strength"] = 0.3
        
        final_score = self.calculate_weighted_score(components)
        return final_score, components
    
    # ==================== NO-TRADE CONDITIONS ====================
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        """Check NO-TRADE conditions."""
        reasons = []
        
        # 1. Already extended (> 5% above breakout level)
        hist = market_data.get_history(symbol, period="1mo")
        if hist is not None:
            close = hist['Close']
            sma20 = close.rolling(20).mean().iloc[-1]
            current = close.iloc[-1]
            
            extension = (current - sma20) / sma20 * 100
            if extension > 10:
                reasons.append(f"Already extended ({extension:.1f}% above 20 SMA)")
        
        # 2. Low volume breakout
        if hist is not None:
            volume = hist['Volume']
            today_vol = volume.iloc[-1]
            avg_vol = volume.iloc[-20:-1].mean()
            
            if today_vol < avg_vol:
                reasons.append("Low volume breakout")
        
        # 3. Market weakness
        spy = market_data.get_history("SPY", period="5d")
        if spy is not None:
            spy_change = (spy['Close'].iloc[-1] / spy['Close'].iloc[0] - 1) * 100
            if spy_change < -3:
                reasons.append(f"Market weakness (SPY {spy_change:.1f}%)")
        
        if reasons:
            return True, "; ".join(reasons)
        return False, ""
    
    # ==================== INVALIDATION ====================
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        """Check if breakout position should be closed."""
        entry_price = position.get("entry_price", 0)
        highest_price = position.get("highest_price", entry_price)
        entry_date = position.get("entry_date")
        
        if not entry_price:
            return False, ""
        
        hist = market_data.get_history(symbol, period="1mo")
        if hist is None:
            return False, ""
        
        current = hist['Close'].iloc[-1]
        sma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        # Update highest
        if current > highest_price:
            highest_price = current
        
        pnl_pct = (current - entry_price) / entry_price * 100
        
        # 1. 10% trailing stop from highest
        if highest_price > entry_price:
            drop = (highest_price - current) / highest_price * 100
            if drop >= 10:
                return True, f"Trailing stop ({drop:.1f}% from high)"
        
        # 2. Close below 20 SMA
        if current < sma20:
            return True, "Closed below 20 SMA"
        
        # 3. Max hold
        if entry_date:
            try:
                entry_dt = datetime.fromisoformat(entry_date)
                days = (datetime.now() - entry_dt).days
                if days >= self.config.max_hold_days:
                    return True, f"Max hold ({days} days)"
            except:
                pass
        
        # 4. Initial stop at -5% (before trailing kicks in)
        if pnl_pct <= -5:
            return True, f"Initial stop ({pnl_pct:.1f}%)"
        
        return False, ""


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    strategy = BreakoutStrategy()
    
    print("=" * 60)
    print("BREAKOUT STRATEGY TEST")
    print("=" * 60)
    
    # Run analysis
    print("\n1. Running weekend analysis...")
    results = strategy.analyze()
    
    # Show watchlist
    watchlist = [r for r in results if r.get("pct_from_high", 100) <= 5]
    print(f"\n2. Watchlist ({len(watchlist)} stocks within 5% of high):")
    print("-" * 60)
    print(f"{'Symbol':<10} {'% From High':<12} {'RSI':<8} {'Vol Ratio':<10} {'Uptrend'}")
    print("-" * 60)
    
    for r in watchlist[:15]:
        uptrend = "✓" if r.get("in_uptrend") else "✗"
        print(f"{r['symbol']:<10} {r['pct_from_high']:<12.1f} {r.get('rsi', 0):<8.0f} {r.get('volume_ratio', 0):<10.1f} {uptrend}")
    
    # Run scan
    print("\n3. Running daily scan...")
    signals = strategy.scan()
    
    print(f"\n4. Signals ({len(signals)}):")
    for s in signals:
        print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}")
        print(f"    {s.reason}")
