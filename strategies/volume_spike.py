"""
strategies/volume_spike.py - Volume Spike Momentum Strategy

Detects unusual volume surges that often precede significant price moves.

Logic:
- Volume > 2x 20-day average = spike
- If spike + price up + above SMA20 → bullish momentum BUY
- If spike + price down + below SMA20 → distribution SELL/AVOID
- Extra scoring for: breakout from range, sector alignment, news catalyst

Best for: Catching institutional accumulation and breakout entries.
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import numpy as np

import config
from core import market_data
from core.storage import Storage, get_week_id
from core.utils import safe_json_dump
from strategies.base_strategy import BaseStrategy, Signal, SignalType

logger = logging.getLogger(__name__)


class VolumeSpikeStrategy(BaseStrategy):
    """
    Volume Spike Momentum Strategy.
    
    Detects stocks with unusual volume that signals institutional activity.
    
    Parameters:
        volume_threshold: Min volume multiple vs 20-day avg (default: 2.0)
        min_avg_volume: Min average daily volume (default: 500,000)
        price_min: Min stock price (default: 5.0)
        consolidation_days: Days to check for consolidation (default: 10)
    """
    
    def __init__(self):
        super().__init__(
            name="volume_spike",
            description="Detects unusual volume surges signaling institutional activity",
            min_score=2.5,
        )
        
        self.volume_threshold = 2.0     # 2x average volume
        self.min_avg_volume = 500_000   # Min average daily volume
        self.price_min = 5.0
        self.consolidation_days = 10
        
        self.storage = Storage()
    
    def analyze(self) -> List[Dict]:
        """Weekend analysis: scan for recent volume spikes."""
        logger.info(f"[{self.name}] Running weekend analysis...")
        
        symbols = self.storage.get_universe_symbols()
        if not symbols:
            logger.warning("No universe loaded")
            return []
        
        scan_list = list(symbols)[:500]
        
        results = []
        checked = 0
        
        for symbol in scan_list:
            try:
                result = self._scan_symbol(symbol)
                if result:
                    results.append(result)
                checked += 1
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        logger.info(f"[{self.name}] Found {len(results)} volume spikes from {checked} stocks")
        return results
    
    def scan(self) -> List[Signal]:
        """Daily scan: check for fresh volume spikes today."""
        analysis = self._load_analysis()
        if not analysis:
            return []
        
        signals = []
        
        for data in analysis:
            symbol = data.get("symbol")
            score = data.get("score", 0)
            spike_type = data.get("spike_type", "")
            
            if score < self.min_score:
                continue
            
            if spike_type == "accumulation":
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    strategy=self.name,
                    score=score,
                    reason=f"Volume spike accumulation ({data.get('volume_ratio', 0):.1f}x avg vol)",
                    entry_price=data.get("current_price"),
                    stop_loss=data.get("stop_loss"),
                    target=data.get("target"),
                ))
        
        return signals
    
    def _scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Scan a single symbol for volume spikes."""
        hist = market_data.get_history(symbol, period="3mo")
        
        if hist is None or len(hist) < 30:
            return None
        
        close = hist["Close"]
        volume = hist["Volume"]
        
        current_price = float(close.iloc[-1])
        
        # Filter: price too low
        if current_price < self.price_min:
            return None
        
        # Calculate volume metrics
        avg_vol_20 = float(volume.iloc[-21:-1].mean())  # Exclude today
        
        if avg_vol_20 < self.min_avg_volume:
            return None
        
        # Check last 5 days for volume spikes
        spike_days = []
        for i in range(-5, 0):
            day_vol = float(volume.iloc[i])
            if day_vol > avg_vol_20 * self.volume_threshold:
                day_close = float(close.iloc[i])
                day_open = float(hist["Open"].iloc[i])
                price_change = (day_close - day_open) / day_open * 100
                
                spike_days.append({
                    "day_offset": i,
                    "volume": day_vol,
                    "volume_ratio": day_vol / avg_vol_20,
                    "price_change": price_change,
                    "close": day_close,
                })
        
        if not spike_days:
            return None
        
        # Use the strongest spike
        best_spike = max(spike_days, key=lambda x: x["volume_ratio"])
        vol_ratio = best_spike["volume_ratio"]
        spike_price_change = best_spike["price_change"]
        
        # SMAs
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
        
        above_sma20 = current_price > sma20
        above_sma50 = current_price > sma50
        
        # Determine spike type
        if spike_price_change > 0.5 and above_sma20:
            spike_type = "accumulation"  # Bullish
        elif spike_price_change < -0.5 and not above_sma20:
            spike_type = "distribution"  # Bearish
        elif abs(spike_price_change) < 0.5 and vol_ratio > 3:
            spike_type = "churning"  # Indecision at high volume
        else:
            spike_type = "mixed"
        
        # Check for consolidation before spike (range-bound = better breakout)
        recent_range = (float(close.iloc[-self.consolidation_days:].max()) - 
                       float(close.iloc[-self.consolidation_days:].min()))
        range_pct = recent_range / current_price * 100
        is_tight_range = range_pct < 8  # < 8% range = consolidation
        
        # Score (1-5)
        score = self._score_spike(vol_ratio, spike_price_change, above_sma20, 
                                  above_sma50, is_tight_range, spike_type)
        
        if score < 2.0:
            return None
        
        # Stops and targets
        if spike_type == "accumulation":
            stop_loss = min(current_price * 0.96, sma20 * 0.99)
            target = current_price * 1.08
        else:
            stop_loss = current_price * 1.04
            target = current_price * 0.92
        
        return {
            "symbol": symbol,
            "spike_type": spike_type,
            "current_price": round(current_price, 2),
            "volume_ratio": round(vol_ratio, 2),
            "spike_price_change": round(spike_price_change, 2),
            "avg_volume_20d": int(avg_vol_20),
            "spike_volume": int(best_spike["volume"]),
            "above_sma20": above_sma20,
            "above_sma50": above_sma50,
            "is_consolidation_breakout": is_tight_range,
            "range_pct": round(range_pct, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "score": score,
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "spike_days_count": len(spike_days),
            "analyzed_at": datetime.now().isoformat(),
        }
    
    def _score_spike(self, vol_ratio, price_change, above_sma20, 
                     above_sma50, is_tight_range, spike_type) -> float:
        """Score volume spike from 1-5."""
        score = 1.5  # Base
        
        # Volume magnitude
        if vol_ratio > 5:
            score += 1.5
        elif vol_ratio > 3:
            score += 1.0
        elif vol_ratio > 2:
            score += 0.5
        
        # Price direction with volume
        if spike_type == "accumulation":
            score += 0.5
            if price_change > 2:
                score += 0.5
        
        # Trend alignment
        if above_sma20:
            score += 0.3
        if above_sma50:
            score += 0.2
        
        # Consolidation breakout bonus
        if is_tight_range and spike_type == "accumulation":
            score += 0.5
        
        return min(5.0, round(score, 1))
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        filepath = config.DATA_DIR / f"volume_spike_{week_id}.json"
        safe_json_dump({
            "week_id": week_id,
            "strategy": self.name,
            "analyzed_at": datetime.now().isoformat(),
            "results": results,
        }, filepath)
        logger.info(f"[{self.name}] Saved to {filepath}")
    
    def _load_analysis(self) -> List[Dict]:
        import json
        week_id = get_week_id()
        filepath = config.DATA_DIR / f"volume_spike_{week_id}.json"
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("results", [])
        return []
    
    def check_invalidation(self, symbol: str, position_data: Dict) -> Optional[str]:
        """Check if volume spike setup invalidated."""
        hist = market_data.get_history(symbol, period="5d")
        if hist is None or len(hist) < 3:
            return None
        
        # If entered on accumulation but price reverses on high volume
        recent_vol = float(hist["Volume"].iloc[-1])
        avg_vol = float(hist["Volume"].mean())
        price_change = float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100)
        
        if recent_vol > avg_vol * 2 and price_change < -2:
            return f"Distribution detected: high volume selloff ({price_change:.1f}%)"
        
        return None
