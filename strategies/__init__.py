"""
strategies - Trading Strategies Module

Available Strategies:

SWING STRATEGIES (Pre-market scan at 9:00 AM):
1. Sector Momentum - Rotate between sector ETFs
2. Mean Reversion - Buy oversold quality stocks  
3. Breakout - Buy new 52-week highs
4. Gap Fade - Fade overnight gaps

INTRADAY STRATEGIES (Scan at 10:00 AM):
5. VWAP Reversion - Buy below VWAP
6. ORB - Opening Range Breakout

All strategies follow the same interface:
- analyze(): Weekend analysis
- scan(): Daily signal generation
- score(): 1-5 confidence scoring
- check_no_trade(): Skip conditions
- check_invalidation(): Exit conditions
"""

from strategies.base_strategy import BaseStrategy, StrategyConfig, Signal, SignalType
from strategies.sector_momentum import SectorMomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.intraday import GapFadeStrategy, VWAPReversionStrategy, OpeningRangeBreakoutStrategy
from strategies.manager import StrategyManager

__all__ = [
    "BaseStrategy",
    "StrategyConfig", 
    "Signal",
    "SignalType",
    "SectorMomentumStrategy",
    "MeanReversionStrategy",
    "BreakoutStrategy",
    "GapFadeStrategy",
    "VWAPReversionStrategy",
    "OpeningRangeBreakoutStrategy",
    "StrategyManager",
]
