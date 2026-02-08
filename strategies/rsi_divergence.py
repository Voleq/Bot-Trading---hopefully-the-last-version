"""
strategies/rsi_divergence.py - RSI Divergence Strategy

Detects bullish and bearish divergences between price and RSI.

Bullish Divergence: Price makes lower low, RSI makes higher low → BUY signal
Bearish Divergence: Price makes higher high, RSI makes lower high → SELL signal

Best for: Mean reversion setups on quality stocks that are oversold/overbought.
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


class RSIDivergenceStrategy(BaseStrategy):
    """
    RSI Divergence Strategy.
    
    Scans for bullish divergences (oversold reversals) and
    bearish divergences (overbought reversals).
    
    Parameters:
        rsi_period: RSI calculation period (default: 14)
        lookback_days: How far back to look for divergences (default: 30)
        rsi_oversold: Oversold threshold (default: 35)
        rsi_overbought: Overbought threshold (default: 65)
        min_divergence_bars: Min bars between pivot points (default: 5)
    """
    
    def __init__(self):
        super().__init__(
            name="rsi_divergence",
            description="Detects bullish/bearish RSI divergences",
            min_score=2.5,
        )
        
        self.rsi_period = 14
        self.lookback_days = 30
        self.rsi_oversold = 35
        self.rsi_overbought = 65
        self.min_divergence_bars = 5
        
        self.storage = Storage()
    
    def analyze(self) -> List[Dict]:
        """Weekend analysis: scan universe for divergence setups."""
        logger.info(f"[{self.name}] Running weekend analysis...")
        
        symbols = self.storage.get_universe_symbols()
        if not symbols:
            logger.warning("No universe loaded")
            return []
        
        # Focus on liquid US stocks
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
        
        # Sort by absolute score (strongest divergences first)
        results.sort(key=lambda x: abs(x.get("score", 0)), reverse=True)
        
        # Save
        week_id = get_week_id()
        self._save_analysis(results, week_id)
        
        logger.info(f"[{self.name}] Found {len(results)} divergences from {checked} stocks")
        return results
    
    def scan(self) -> List[Signal]:
        """Daily scan: check precomputed divergences for entry timing."""
        analysis = self._load_analysis()
        if not analysis:
            return []
        
        signals = []
        
        for data in analysis:
            symbol = data.get("symbol")
            div_type = data.get("divergence_type")
            score = data.get("score", 0)
            
            if abs(score) < self.min_score:
                continue
            
            # Verify current RSI still supports the setup
            current_rsi = self._get_current_rsi(symbol)
            if current_rsi is None:
                continue
            
            if div_type == "bullish" and current_rsi < self.rsi_overbought:
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    strategy=self.name,
                    score=score,
                    reason=f"Bullish RSI divergence (RSI: {current_rsi:.0f})",
                    entry_price=data.get("current_price"),
                    stop_loss=data.get("stop_loss"),
                    target=data.get("target"),
                ))
            elif div_type == "bearish" and current_rsi > self.rsi_oversold:
                signals.append(Signal(
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    strategy=self.name,
                    score=score,
                    reason=f"Bearish RSI divergence (RSI: {current_rsi:.0f})",
                    entry_price=data.get("current_price"),
                    stop_loss=data.get("stop_loss"),
                    target=data.get("target"),
                ))
        
        return signals
    
    def _scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Scan a single symbol for RSI divergence."""
        hist = market_data.get_history(symbol, period="3mo")
        
        if hist is None or len(hist) < 50:
            return None
        
        close = hist["Close"].values
        rsi = self._calculate_rsi(close, self.rsi_period)
        
        if rsi is None or len(rsi) < self.lookback_days:
            return None
        
        # Check for bullish divergence (in last N days)
        bullish = self._find_bullish_divergence(close, rsi)
        bearish = self._find_bearish_divergence(close, rsi)
        
        if not bullish and not bearish:
            return None
        
        current_price = float(close[-1])
        current_rsi = float(rsi[-1])
        
        # Pick the stronger signal
        if bullish and bearish:
            div_type = "bullish" if bullish["strength"] > bearish["strength"] else "bearish"
            div_data = bullish if div_type == "bullish" else bearish
        elif bullish:
            div_type = "bullish"
            div_data = bullish
        else:
            div_type = "bearish"
            div_data = bearish
        
        # Score: 1-5 based on divergence strength and RSI extremity
        score = self._score_divergence(div_data, current_rsi, div_type)
        
        # Calculate stop and target
        if div_type == "bullish":
            stop_loss = current_price * 0.97  # 3% stop
            target = current_price * 1.06     # 6% target (2:1 R/R)
        else:
            stop_loss = current_price * 1.03
            target = current_price * 0.94
        
        return {
            "symbol": symbol,
            "divergence_type": div_type,
            "current_price": current_price,
            "current_rsi": round(current_rsi, 1),
            "strength": div_data["strength"],
            "price_low1": div_data.get("price1"),
            "price_low2": div_data.get("price2"),
            "rsi_low1": div_data.get("rsi1"),
            "rsi_low2": div_data.get("rsi2"),
            "score": score,
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "analyzed_at": datetime.now().isoformat(),
        }
    
    def _calculate_rsi(self, prices, period: int = 14):
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.zeros_like(deltas)
        avg_loss = np.zeros_like(deltas)
        
        # Initial average
        avg_gain[period - 1] = np.mean(gains[:period])
        avg_loss[period - 1] = np.mean(losses[:period])
        
        # Smoothed averages
        for i in range(period, len(deltas)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period
        
        rs = np.where(avg_loss != 0, avg_gain / avg_loss, 100)
        rsi = 100 - (100 / (1 + rs))
        
        # Pad front with NaN
        result = np.full(len(prices), np.nan)
        result[period:] = rsi[period - 1:]
        
        return result
    
    def _find_bullish_divergence(self, prices, rsi) -> Optional[Dict]:
        """
        Find bullish divergence: price makes lower low, RSI makes higher low.
        """
        lookback = min(self.lookback_days, len(prices) - 1)
        recent_prices = prices[-lookback:]
        recent_rsi = rsi[-lookback:]
        
        # Find price troughs (local minima)
        troughs = self._find_troughs(recent_prices)
        
        if len(troughs) < 2:
            return None
        
        # Check last two troughs
        for i in range(len(troughs) - 1):
            idx1 = troughs[i]
            idx2 = troughs[i + 1]
            
            if idx2 - idx1 < self.min_divergence_bars:
                continue
            
            price1 = recent_prices[idx1]
            price2 = recent_prices[idx2]
            rsi1 = recent_rsi[idx1]
            rsi2 = recent_rsi[idx2]
            
            if np.isnan(rsi1) or np.isnan(rsi2):
                continue
            
            # Bullish: price lower low, RSI higher low
            if price2 < price1 and rsi2 > rsi1 and rsi2 < self.rsi_oversold + 15:
                strength = (rsi2 - rsi1) / max(abs(price2 - price1) / price1 * 100, 0.1)
                return {
                    "price1": float(price1),
                    "price2": float(price2),
                    "rsi1": float(rsi1),
                    "rsi2": float(rsi2),
                    "strength": abs(strength),
                }
        
        return None
    
    def _find_bearish_divergence(self, prices, rsi) -> Optional[Dict]:
        """
        Find bearish divergence: price makes higher high, RSI makes lower high.
        """
        lookback = min(self.lookback_days, len(prices) - 1)
        recent_prices = prices[-lookback:]
        recent_rsi = rsi[-lookback:]
        
        # Find price peaks (local maxima)
        peaks = self._find_peaks(recent_prices)
        
        if len(peaks) < 2:
            return None
        
        for i in range(len(peaks) - 1):
            idx1 = peaks[i]
            idx2 = peaks[i + 1]
            
            if idx2 - idx1 < self.min_divergence_bars:
                continue
            
            price1 = recent_prices[idx1]
            price2 = recent_prices[idx2]
            rsi1 = recent_rsi[idx1]
            rsi2 = recent_rsi[idx2]
            
            if np.isnan(rsi1) or np.isnan(rsi2):
                continue
            
            # Bearish: price higher high, RSI lower high
            if price2 > price1 and rsi2 < rsi1 and rsi2 > self.rsi_overbought - 15:
                strength = (rsi1 - rsi2) / max(abs(price2 - price1) / price1 * 100, 0.1)
                return {
                    "price1": float(price1),
                    "price2": float(price2),
                    "rsi1": float(rsi1),
                    "rsi2": float(rsi2),
                    "strength": abs(strength),
                }
        
        return None
    
    def _find_troughs(self, data, order: int = 3) -> List[int]:
        """Find local minima indices."""
        troughs = []
        for i in range(order, len(data) - order):
            if all(data[i] <= data[i - j] for j in range(1, order + 1)) and \
               all(data[i] <= data[i + j] for j in range(1, order + 1)):
                troughs.append(i)
        return troughs
    
    def _find_peaks(self, data, order: int = 3) -> List[int]:
        """Find local maxima indices."""
        peaks = []
        for i in range(order, len(data) - order):
            if all(data[i] >= data[i - j] for j in range(1, order + 1)) and \
               all(data[i] >= data[i + j] for j in range(1, order + 1)):
                peaks.append(i)
        return peaks
    
    def _score_divergence(self, div_data: Dict, current_rsi: float, div_type: str) -> float:
        """Score divergence from 1-5."""
        strength = div_data.get("strength", 0)
        
        score = 2.0  # Base
        
        # Strength of divergence
        if strength > 5:
            score += 1.5
        elif strength > 2:
            score += 1.0
        elif strength > 1:
            score += 0.5
        
        # RSI extremity bonus
        if div_type == "bullish" and current_rsi < 30:
            score += 1.0
        elif div_type == "bullish" and current_rsi < 40:
            score += 0.5
        elif div_type == "bearish" and current_rsi > 70:
            score += 1.0
        elif div_type == "bearish" and current_rsi > 60:
            score += 0.5
        
        return min(5.0, round(score, 1))
    
    def _get_current_rsi(self, symbol: str) -> Optional[float]:
        """Get current RSI for a symbol."""
        hist = market_data.get_history(symbol, period="1mo")
        if hist is None or len(hist) < 20:
            return None
        rsi = self._calculate_rsi(hist["Close"].values, self.rsi_period)
        if rsi is None:
            return None
        valid = rsi[~np.isnan(rsi)]
        return float(valid[-1]) if len(valid) > 0 else None
    
    def _save_analysis(self, results: List[Dict], week_id: str):
        filepath = config.DATA_DIR / f"rsi_divergence_{week_id}.json"
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
        filepath = config.DATA_DIR / f"rsi_divergence_{week_id}.json"
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("results", [])
        return []
    
    def check_invalidation(self, symbol: str, position_data: Dict) -> Optional[str]:
        """Check if RSI divergence setup has been invalidated."""
        current_rsi = self._get_current_rsi(symbol)
        if current_rsi is None:
            return None
        
        div_type = position_data.get("divergence_type", "bullish")
        
        # Bullish divergence invalidated if RSI goes even lower
        if div_type == "bullish" and current_rsi < 20:
            return f"RSI extremely oversold ({current_rsi:.0f}) - divergence may fail"
        
        # Bearish divergence invalidated if RSI goes even higher
        if div_type == "bearish" and current_rsi > 80:
            return f"RSI extremely overbought ({current_rsi:.0f}) - divergence may fail"
        
        return None
