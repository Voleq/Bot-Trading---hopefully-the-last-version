"""
strategies/sector_momentum.py - Sector Rotation Strategy

Rotates between sector ETFs based on momentum.
Buy top performing sectors, avoid/short bottom sectors.

Schedule:
- Weekend: Rank all sectors by momentum
- Weekly: Rebalance on Monday open
- Daily: Check for invalidation only

Universe: 11 Sector ETFs (all highly liquid, all on T212)
"""

import logging
from datetime import datetime, time, timedelta
from typing import List, Dict, Tuple, Optional

import numpy as np
import pandas as pd

import config
from core import market_data
from core.storage import Storage, get_week_id
from strategies.base_strategy import (
    BaseStrategy, StrategyConfig, Signal, SignalType
)

logger = logging.getLogger(__name__)


# Sector ETF Universe
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLI": "Industrials",
    "XLRE": "Real Estate",
    "XLC": "Communications",
}

# Broad market for comparison
BENCHMARK = "SPY"


class SectorMomentumStrategy(BaseStrategy):
    """
    Sector rotation based on momentum.
    
    Logic:
    1. Rank sectors by 1-month momentum
    2. Buy top 3 sectors
    3. Avoid bottom 3 sectors
    4. Rebalance weekly
    
    Scoring Components:
    - 1-month return rank (30%)
    - 20/50 SMA crossover (25%)
    - Relative strength vs SPY (25%)
    - Volume trend (20%)
    """
    
    def __init__(self):
        config = StrategyConfig(
            name="Sector Momentum",
            enabled=True,
            check_time=time(10, 30),  # 10:30 AM ET
            min_hold_days=5,          # Hold at least 5 days
            max_hold_days=30,         # Rebalance monthly max
            max_positions=3,          # Top 3 sectors
            position_size_pct=0.15    # 15% per sector
        )
        super().__init__(config)
        
        self.storage = Storage()
        
        # Score weights
        self.score_weights = {
            "momentum_rank": 0.30,
            "sma_trend": 0.25,
            "relative_strength": 0.25,
            "volume_trend": 0.20
        }
    
    def get_universe(self) -> List[str]:
        """Sector ETFs only."""
        return list(SECTOR_ETFS.keys())
    
    # ==================== WEEKEND ANALYSIS ====================
    
    def analyze(self) -> List[Dict]:
        """
        Weekend analysis: Rank all sectors.
        Called on Saturday/Sunday.
        """
        logger.info(f"[{self.name}] Running weekend analysis...")
        
        results = []
        sector_data = {}
        
        # Fetch data for all sectors
        for symbol, sector_name in SECTOR_ETFS.items():
            data = self._fetch_sector_data(symbol)
            if data:
                sector_data[symbol] = data
                sector_data[symbol]["sector_name"] = sector_name
        
        if len(sector_data) < 6:
            logger.error("Could not fetch enough sector data")
            return []
        
        # Fetch benchmark
        spy_data = self._fetch_sector_data(BENCHMARK)
        if not spy_data:
            logger.error("Could not fetch SPY data")
            return []
        
        # Calculate rankings
        momentum_ranks = self._rank_by_momentum(sector_data)
        
        # Score each sector
        for symbol, data in sector_data.items():
            score, components = self.score(symbol, {
                "sector_data": data,
                "spy_data": spy_data,
                "momentum_rank": momentum_ranks.get(symbol, 6),
                "total_sectors": len(sector_data)
            })
            
            results.append({
                "symbol": symbol,
                "sector_name": data["sector_name"],
                "momentum_rank": momentum_ranks.get(symbol, 0),
                "return_1m": data.get("return_1m", 0),
                "return_3m": data.get("return_3m", 0),
                "above_sma20": data.get("above_sma20", False),
                "above_sma50": data.get("above_sma50", False),
                "relative_strength": data.get("rs_vs_spy", 0),
                "volume_trend": data.get("volume_trend", 0),
                "score": score,
                "score_components": components,
                "signal": "BUY" if momentum_ranks.get(symbol, 99) <= 3 else "AVOID",
                "analyzed_at": datetime.now().isoformat()
            })
        
        # Sort by rank
        results.sort(key=lambda x: x["momentum_rank"])
        
        # Save results
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        # Log top and bottom
        logger.info(f"[{self.name}] Top 3 sectors:")
        for r in results[:3]:
            logger.info(f"  {r['symbol']} ({r['sector_name']}): Score {r['score']}, Return {r['return_1m']:.1f}%")
        
        logger.info(f"[{self.name}] Bottom 3 sectors:")
        for r in results[-3:]:
            logger.info(f"  {r['symbol']} ({r['sector_name']}): Score {r['score']}, Return {r['return_1m']:.1f}%")
        
        return results
    
    def _fetch_sector_data(self, symbol: str) -> Optional[Dict]:
        """Fetch and calculate metrics for a sector ETF."""
        hist = market_data.get_history(symbol, period="3mo")
        
        if hist is None or len(hist) < 50:
            logger.warning(f"Insufficient data for {symbol}")
            return None
        
        try:
            close = hist['Close']
            volume = hist['Volume']
            
            # Returns
            return_1m = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0
            return_3m = (close.iloc[-1] / close.iloc[0] - 1) * 100
            
            # SMAs
            sma20 = close.rolling(20).mean().iloc[-1]
            sma50 = close.rolling(50).mean().iloc[-1]
            
            # Volume trend (recent vs average)
            recent_vol = volume.iloc[-5:].mean()
            avg_vol = volume.iloc[-20:].mean()
            volume_trend = (recent_vol / avg_vol - 1) if avg_vol > 0 else 0
            
            return {
                "return_1m": return_1m,
                "return_3m": return_3m,
                "price": close.iloc[-1],
                "sma20": sma20,
                "sma50": sma50,
                "above_sma20": close.iloc[-1] > sma20,
                "above_sma50": close.iloc[-1] > sma50,
                "volume_trend": volume_trend,
                "history": hist
            }
        except Exception as e:
            logger.error(f"Error calculating metrics for {symbol}: {e}")
            return None
    
    def _rank_by_momentum(self, sector_data: Dict) -> Dict[str, int]:
        """Rank sectors by 1-month momentum."""
        returns = []
        for symbol, data in sector_data.items():
            returns.append((symbol, data.get("return_1m", -999)))
        
        # Sort descending (best first)
        returns.sort(key=lambda x: x[1], reverse=True)
        
        ranks = {}
        for i, (symbol, _) in enumerate(returns):
            ranks[symbol] = i + 1
        
        return ranks
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        """Save analysis results."""
        filepath = config.DATA_DIR / f"sector_momentum_{week_id}.json"
        
        import json
        data = {
            "week_id": week_id,
            "strategy": self.name,
            "analyzed_at": datetime.now().isoformat(),
            "results": results
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"[{self.name}] Analysis saved to {filepath}")
    
    def _load_analysis(self, week_id: str = None) -> List[Dict]:
        """Load precomputed analysis."""
        week_id = week_id or get_week_id()
        filepath = config.DATA_DIR / f"sector_momentum_{week_id}.json"
        
        import json
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("results", [])
        
        return []
    
    # ==================== DAILY SCAN ====================
    
    def scan(self) -> List[Signal]:
        """
        Daily scan - generate signals based on precomputed analysis.
        """
        logger.info(f"[{self.name}] Running daily scan...")
        
        signals = []
        
        # Load weekend analysis
        analysis = self._load_analysis()
        
        if not analysis:
            logger.warning(f"[{self.name}] No precomputed analysis found")
            # Run analysis now if missing
            analysis = self.analyze()
        
        # Generate signals for top sectors
        for result in analysis:
            symbol = result.get("symbol")
            rank = result.get("momentum_rank", 99)
            score = result.get("score", 0)
            
            # Check NO-TRADE conditions
            should_skip, skip_reason = self.check_no_trade(symbol)
            if should_skip:
                logger.info(f"[{self.name}] SKIP {symbol}: {skip_reason}")
                continue
            
            # Only signal top 3 sectors with score >= 3
            if rank <= 3 and score >= 3:
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    score=score,
                    strategy=self.name,
                    reason=f"Rank #{rank} sector, {result.get('return_1m', 0):.1f}% 1M return",
                    score_components=result.get("score_components", {}),
                    entry_price=market_data.get_current_price(symbol)
                ))
        
        logger.info(f"[{self.name}] Generated {len(signals)} signals")
        return signals
    
    # ==================== SCORING ====================
    
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        """Calculate score for a sector ETF."""
        components = {}
        
        sector_data = data.get("sector_data", {})
        spy_data = data.get("spy_data", {})
        rank = data.get("momentum_rank", 6)
        total = data.get("total_sectors", 11)
        
        # 1. Momentum rank (0-1, where 1 is best)
        components["momentum_rank"] = 1 - (rank - 1) / max(total - 1, 1)
        
        # 2. SMA trend
        above_20 = sector_data.get("above_sma20", False)
        above_50 = sector_data.get("above_sma50", False)
        
        if above_20 and above_50:
            components["sma_trend"] = 1.0
        elif above_50:
            components["sma_trend"] = 0.7
        elif above_20:
            components["sma_trend"] = 0.5
        else:
            components["sma_trend"] = 0.2
        
        # 3. Relative strength vs SPY
        sector_return = sector_data.get("return_1m", 0)
        spy_return = spy_data.get("return_1m", 0)
        rs = sector_return - spy_return
        
        if rs > 5:
            components["relative_strength"] = 1.0
        elif rs > 2:
            components["relative_strength"] = 0.8
        elif rs > 0:
            components["relative_strength"] = 0.6
        elif rs > -2:
            components["relative_strength"] = 0.4
        else:
            components["relative_strength"] = 0.2
        
        # 4. Volume trend
        vol_trend = sector_data.get("volume_trend", 0)
        if vol_trend > 0.2:
            components["volume_trend"] = 0.9
        elif vol_trend > 0:
            components["volume_trend"] = 0.7
        elif vol_trend > -0.2:
            components["volume_trend"] = 0.5
        else:
            components["volume_trend"] = 0.3
        
        # Calculate final score
        final_score = self.calculate_weighted_score(components)
        
        return final_score, components
    
    # ==================== NO-TRADE CONDITIONS ====================
    
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        """Check NO-TRADE conditions for sector ETFs."""
        reasons = []
        
        # 1. Market in extreme fear (VIX > 35)
        try:
            vix = market_data.get_current_price("VIXY")  # VIX proxy
            if vix and vix > 50:  # VIXY typically 2-3x VIX moves
                reasons.append(f"High VIX environment")
        except:
            pass
        
        # 2. Sector breaking down (below 50 SMA and falling)
        hist = market_data.get_history(symbol, period="3mo")
        if hist is not None and len(hist) >= 50:
            close = hist['Close']
            sma50 = close.rolling(50).mean().iloc[-1]
            current = close.iloc[-1]
            prev = close.iloc[-5]
            
            if current < sma50 and current < prev:
                reasons.append(f"Below 50 SMA and falling")
        
        # 3. Already have maximum positions in this strategy
        # (Would check tracked positions here)
        
        if reasons:
            return True, "; ".join(reasons)
        return False, ""
    
    # ==================== INVALIDATION ====================
    
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        """Check if sector position should be closed."""
        entry_price = position.get("entry_price", 0)
        entry_date = position.get("entry_date")
        
        if not entry_price:
            return False, ""
        
        current = market_data.get_current_price(symbol)
        if not current:
            return False, ""
        
        pnl_pct = (current - entry_price) / entry_price * 100
        
        # 1. Stop loss at -8%
        if pnl_pct <= -8:
            return True, f"Stop loss triggered ({pnl_pct:.1f}%)"
        
        # 2. Sector fell out of top 5
        analysis = self._load_analysis()
        for r in analysis:
            if r.get("symbol") == symbol:
                rank = r.get("momentum_rank", 99)
                if rank > 5:
                    return True, f"Sector dropped to rank #{rank}"
                break
        
        # 3. Max hold period (rebalance)
        if entry_date:
            try:
                entry_dt = datetime.fromisoformat(entry_date)
                days_held = (datetime.now() - entry_dt).days
                if days_held >= self.config.max_hold_days:
                    return True, f"Rebalance (held {days_held} days)"
            except:
                pass
        
        return False, ""


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    strategy = SectorMomentumStrategy()
    
    print("=" * 60)
    print("SECTOR MOMENTUM STRATEGY TEST")
    print("=" * 60)
    
    # Run analysis
    print("\n1. Running weekend analysis...")
    results = strategy.analyze()
    
    print(f"\n2. Results ({len(results)} sectors):")
    print("-" * 60)
    print(f"{'Rank':<6} {'Symbol':<8} {'Sector':<25} {'Score':<6} {'1M Ret':<8}")
    print("-" * 60)
    
    for r in results:
        print(f"{r['momentum_rank']:<6} {r['symbol']:<8} {r['sector_name']:<25} {r['score']:<6} {r['return_1m']:>+.1f}%")
    
    # Run scan
    print("\n3. Running daily scan...")
    signals = strategy.scan()
    
    print(f"\n4. Signals ({len(signals)}):")
    for s in signals:
        print(f"  {s.signal_type.value} {s.symbol}: Score {s.score}, {s.reason}")
