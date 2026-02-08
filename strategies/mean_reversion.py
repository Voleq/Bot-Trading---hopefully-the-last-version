"""
strategies/mean_reversion.py - Oversold Bounce Strategy

Buys quality stocks that are oversold (RSI < 10) for quick bounces.
Classic mean reversion on S&P 500 components.

Schedule:
- Weekend: Pre-screen quality stocks, identify earnings dates
- Daily: Scan for RSI extremes at 9:45 AM
- Exit: RSI > 70 or 5 days max hold

Universe: S&P 500 stocks in T212 universe
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


# Quality large caps for mean reversion
# These are stable companies that tend to bounce
QUALITY_UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "CSCO", "ORCL", "CRM",
    "ADBE", "ACN", "IBM", "INTC", "AMD", "QCOM", "TXN", "AMAT", "MU", "LRCX",
    
    # Finance
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "C", "USB", "PNC",
    "AXP", "COF", "BK", "TFC", "CME", "ICE", "MMC", "AON", "SPGI", "MCO",
    
    # Healthcare
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "TMO", "DHR", "BMY", "LLY", "AMGN",
    "GILD", "MDT", "SYK", "BSX", "ISRG", "EW", "ZBH", "BDX", "ABT", "CVS",
    
    # Consumer
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT",
    "LOW", "TJX", "DG", "DLTR", "ROST", "YUM", "CMG", "DPZ", "ORLY", "AZO",
    
    # Industrial
    "CAT", "DE", "HON", "MMM", "GE", "UPS", "FDX", "LMT", "RTX", "BA",
    "NOC", "GD", "EMR", "ETN", "ITW", "PH", "ROK", "CMI", "PCAR", "WM",
    
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "VLO", "PSX", "HES",
    
    # Other
    "DIS", "NFLX", "CMCSA", "T", "VZ", "NEE", "DUK", "SO", "D", "AEP",
]


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion on oversold quality stocks.
    
    Entry Conditions:
    - RSI(2) < 10 (extremely oversold)
    - Price above 200 SMA (uptrend)
    - No earnings within 3 days
    - VIX < 35 (not panic selling)
    
    Exit Conditions:
    - RSI(2) > 70 (overbought bounce)
    - 5 days max hold
    - -5% stop loss
    
    Scoring Components:
    - RSI extremity (30%)
    - Distance from 200 SMA (25%)
    - Recent drawdown (25%)
    - Volume spike (20%)
    """
    
    def __init__(self):
        cfg = StrategyConfig(
            name="Mean Reversion",
            enabled=True,
            check_time=time(9, 45),    # 9:45 AM ET (after open volatility)
            min_hold_days=1,
            max_hold_days=5,           # Quick trades
            max_positions=5,
            position_size_pct=0.08     # 8% per position (smaller for quick trades)
        )
        super().__init__(cfg)
        
        self.storage = Storage()
        
        # Score weights
        self.score_weights = {
            "rsi_extremity": 0.30,
            "trend_strength": 0.25,
            "drawdown_depth": 0.25,
            "volume_spike": 0.20
        }
        
        # RSI thresholds
        self.rsi_entry = 10    # RSI below this to enter
        self.rsi_exit = 70     # RSI above this to exit
    
    def get_universe(self) -> List[str]:
        """Quality large caps for mean reversion."""
        return QUALITY_UNIVERSE
    
    # ==================== WEEKEND ANALYSIS ====================
    
    def analyze(self) -> List[Dict]:
        """
        Weekend analysis: Pre-screen stocks for quality metrics.
        Identify upcoming earnings to avoid.
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
        
        # Save
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        logger.info(f"[{self.name}] Analyzed {len(results)} stocks")
        return results
    
    def _analyze_stock(self, symbol: str) -> Optional[Dict]:
        """Pre-analyze a stock for quality metrics."""
        symbol = clean_symbol(symbol)
        if not symbol:
            return None
        
        hist = market_data.get_history(symbol, period="1y")
        if hist is None or len(hist) < 200:
            return None
        
        info = market_data.get_info(symbol)
        
        close = hist['Close']
        
        # Calculate metrics
        sma200 = close.rolling(200).mean().iloc[-1]
        current = close.iloc[-1]
        above_sma200 = current > sma200
        
        # Quality score (market cap, analyst coverage)
        market_cap = info.get("marketCap", 0) if info else 0
        num_analysts = info.get("numberOfAnalystOpinions", 0) if info else 0
        
        # Skip if not quality
        if market_cap < 10_000_000_000:  # $10B minimum
            return None
        
        return {
            "symbol": symbol,
            "market_cap": market_cap,
            "num_analysts": num_analysts,
            "above_sma200": above_sma200,
            "sma200": sma200,
            "current_price": current,
            "avg_volume": hist['Volume'].mean(),
            "quality_score": min(1.0, market_cap / 100_000_000_000) * 0.5 + min(1.0, num_analysts / 20) * 0.5,
            "analyzed_at": datetime.now().isoformat()
        }
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        """Save analysis results."""
        from core.utils import safe_json_dump
        filepath = config.DATA_DIR / f"mean_reversion_{week_id}.json"
        
        safe_json_dump({
            "week_id": week_id,
            "strategy": self.name,
            "analyzed_at": datetime.now().isoformat(),
            "results": results
        }, filepath)
    
    def _load_analysis(self, week_id: str = None) -> Dict[str, Dict]:
        """Load precomputed analysis as dict by symbol."""
        week_id = week_id or get_week_id()
        filepath = config.DATA_DIR / f"mean_reversion_{week_id}.json"
        
        import json
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return {r["symbol"]: r for r in data.get("results", [])}
        return {}
    
    # ==================== DAILY SCAN ====================
    
    def scan(self) -> List[Signal]:
        """
        Daily scan for oversold stocks.
        Runs at 9:45 AM after open volatility settles.
        """
        logger.info(f"[{self.name}] Running daily scan...")
        
        signals = []
        
        # Load precomputed quality data
        quality_data = self._load_analysis()
        
        if not quality_data:
            # Run analysis if missing
            self.analyze()
            quality_data = self._load_analysis()
        
        # Scan for oversold conditions
        for symbol in self.get_universe():
            symbol = clean_symbol(symbol)
            if not symbol:
                continue
            
            # Get precomputed quality data
            pre_data = quality_data.get(symbol, {})
            
            # Skip if not above 200 SMA (from weekend analysis)
            if not pre_data.get("above_sma200", True):
                continue
            
            # Check current conditions
            oversold_data = self._check_oversold(symbol)
            
            if not oversold_data:
                continue
            
            rsi = oversold_data.get("rsi", 50)
            
            # Only signal if RSI < threshold
            if rsi >= self.rsi_entry:
                continue
            
            # Check NO-TRADE conditions
            should_skip, skip_reason = self.check_no_trade(symbol)
            if should_skip:
                logger.info(f"[{self.name}] SKIP {symbol}: {skip_reason}")
                continue
            
            # Calculate score
            score, components = self.score(symbol, {
                "rsi": rsi,
                "pre_data": pre_data,
                "oversold_data": oversold_data
            })
            
            if score >= 3:
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    score=score,
                    strategy=self.name,
                    reason=f"RSI(2) = {rsi:.1f}, oversold bounce setup",
                    score_components=components,
                    entry_price=oversold_data.get("price"),
                    stop_loss=oversold_data.get("price") * 0.95  # 5% stop
                ))
        
        logger.info(f"[{self.name}] Generated {len(signals)} signals")
        return signals
    
    def _check_oversold(self, symbol: str) -> Optional[Dict]:
        """Check if stock is currently oversold."""
        hist = market_data.get_history(symbol, period="1mo")
        
        if hist is None or len(hist) < 14:
            return None
        
        close = hist['Close']
        volume = hist['Volume']
        
        # RSI(2)
        rsi2 = self._calculate_rsi(close, period=2)
        
        if rsi2 is None:
            return None
        
        # Current metrics
        current = close.iloc[-1]
        sma200 = close.rolling(min(200, len(close))).mean().iloc[-1]
        
        # Recent drawdown
        high_20 = close.iloc[-20:].max()
        drawdown = (current - high_20) / high_20 * 100
        
        # Volume spike
        recent_vol = volume.iloc[-1]
        avg_vol = volume.iloc[-20:].mean()
        vol_spike = recent_vol / avg_vol if avg_vol > 0 else 1
        
        return {
            "rsi": rsi2,
            "price": current,
            "sma200": sma200,
            "above_sma200": current > sma200,
            "drawdown": drawdown,
            "volume_spike": vol_spike
        }
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 2) -> Optional[float]:
        """Calculate RSI."""
        try:
            delta = prices.diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None
        except:
            return None
    
    # ==================== SCORING ====================
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        """Calculate score for oversold stock."""
        components = {}
        
        rsi = data.get("rsi", 50)
        pre_data = data.get("pre_data", {})
        oversold_data = data.get("oversold_data", {})
        
        # 1. RSI extremity (lower is better)
        if rsi < 5:
            components["rsi_extremity"] = 1.0
        elif rsi < 10:
            components["rsi_extremity"] = 0.8
        elif rsi < 15:
            components["rsi_extremity"] = 0.6
        elif rsi < 20:
            components["rsi_extremity"] = 0.4
        else:
            components["rsi_extremity"] = 0.2
        
        # 2. Trend strength (distance above 200 SMA)
        price = oversold_data.get("price", 0)
        sma200 = oversold_data.get("sma200", price)
        
        if sma200 > 0:
            pct_above = (price - sma200) / sma200 * 100
            
            if pct_above > 20:
                components["trend_strength"] = 1.0
            elif pct_above > 10:
                components["trend_strength"] = 0.8
            elif pct_above > 0:
                components["trend_strength"] = 0.6
            elif pct_above > -5:
                components["trend_strength"] = 0.4
            else:
                components["trend_strength"] = 0.2
        else:
            components["trend_strength"] = 0.5
        
        # 3. Drawdown depth (deeper = better bounce potential)
        drawdown = abs(oversold_data.get("drawdown", 0))
        
        if drawdown > 15:
            components["drawdown_depth"] = 1.0
        elif drawdown > 10:
            components["drawdown_depth"] = 0.8
        elif drawdown > 5:
            components["drawdown_depth"] = 0.6
        else:
            components["drawdown_depth"] = 0.4
        
        # 4. Volume spike (higher = capitulation)
        vol_spike = oversold_data.get("volume_spike", 1)
        
        if vol_spike > 3:
            components["volume_spike"] = 1.0
        elif vol_spike > 2:
            components["volume_spike"] = 0.8
        elif vol_spike > 1.5:
            components["volume_spike"] = 0.6
        else:
            components["volume_spike"] = 0.4
        
        final_score = self.calculate_weighted_score(components)
        return final_score, components
    
    # ==================== NO-TRADE CONDITIONS ====================
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        """Check NO-TRADE conditions."""
        reasons = []
        
        # 1. Check VIX (panic mode)
        try:
            # Use SPY volatility as proxy
            spy_hist = market_data.get_history("SPY", period="1mo")
            if spy_hist is not None:
                returns = spy_hist['Close'].pct_change()
                vol = returns.std() * np.sqrt(252) * 100
                if vol > 35:
                    reasons.append(f"High volatility ({vol:.0f}%)")
        except:
            pass
        
        # 2. Earnings within 3 days
        # Would check earnings calendar here
        # For now, skip this check
        
        # 3. Below 200 SMA (not in uptrend)
        hist = market_data.get_history(symbol, period="1y")
        if hist is not None and len(hist) >= 200:
            close = hist['Close']
            sma200 = close.rolling(200).mean().iloc[-1]
            if close.iloc[-1] < sma200:
                reasons.append("Below 200 SMA")
        
        # 4. Already gapped down too much today
        if hist is not None and len(hist) >= 2:
            prev_close = hist['Close'].iloc[-2]
            current = hist['Close'].iloc[-1]
            gap = (current - prev_close) / prev_close * 100
            
            if gap < -8:
                reasons.append(f"Gap down too large ({gap:.1f}%)")
        
        if reasons:
            return True, "; ".join(reasons)
        return False, ""
    
    # ==================== INVALIDATION ====================
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        """Check if mean reversion position should be closed."""
        entry_price = position.get("entry_price", 0)
        entry_date = position.get("entry_date")
        
        if not entry_price:
            return False, ""
        
        # Get current data
        hist = market_data.get_history(symbol, period="1mo")
        if hist is None:
            return False, ""
        
        current = hist['Close'].iloc[-1]
        pnl_pct = (current - entry_price) / entry_price * 100
        
        # 1. Stop loss at -5%
        if pnl_pct <= -5:
            return True, f"Stop loss ({pnl_pct:.1f}%)"
        
        # 2. RSI > 70 (target reached)
        rsi = self._calculate_rsi(hist['Close'], period=2)
        if rsi and rsi > self.rsi_exit:
            return True, f"RSI target reached ({rsi:.0f})"
        
        # 3. Max hold (5 days)
        if entry_date:
            try:
                entry_dt = datetime.fromisoformat(entry_date)
                days = (datetime.now() - entry_dt).days
                if days >= self.config.max_hold_days:
                    return True, f"Max hold ({days} days)"
            except:
                pass
        
        # 4. Take profit at +5%
        if pnl_pct >= 5:
            return True, f"Take profit ({pnl_pct:.1f}%)"
        
        return False, ""


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    strategy = MeanReversionStrategy()
    
    print("=" * 60)
    print("MEAN REVERSION STRATEGY TEST")
    print("=" * 60)
    
    # Run analysis
    print("\n1. Running weekend analysis...")
    results = strategy.analyze()
    print(f"   Analyzed {len(results)} quality stocks")
    
    # Run scan
    print("\n2. Running daily scan...")
    signals = strategy.scan()
    
    print(f"\n3. Signals ({len(signals)}):")
    if signals:
        for s in signals:
            print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}")
            print(f"    {s.reason}")
            print(f"    Entry: ${s.entry_price:.2f}, Stop: ${s.stop_loss:.2f}")
    else:
        print("  No oversold stocks found (RSI < 10)")
        
        # Show closest to threshold
        print("\n  Stocks closest to oversold:")
        for symbol in strategy.get_universe()[:20]:
            data = strategy._check_oversold(symbol)
            if data and data.get("rsi", 100) < 30:
                print(f"    {symbol}: RSI = {data['rsi']:.1f}")
