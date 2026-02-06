"""
strategies/base_strategy.py - Base Strategy Interface

All strategies must implement this interface.
Ensures consistent behavior across all strategies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import List, Dict, Tuple, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Trading signal from a strategy."""
    symbol: str
    signal_type: SignalType
    score: int                    # 1-5 confidence score
    strategy: str                 # Strategy name
    reason: str                   # Human-readable explanation
    
    # Score components (explainable)
    score_components: Dict[str, float] = field(default_factory=dict)
    
    # Additional data
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type.value,
            "score": self.score,
            "strategy": self.strategy,
            "reason": self.reason,
            "score_components": self.score_components,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "timestamp": self.timestamp
        }


@dataclass
class StrategyConfig:
    """Strategy configuration."""
    name: str
    enabled: bool = True
    check_time: time = time(10, 0)    # Default 10:00 AM ET
    min_hold_days: int = 1
    max_hold_days: int = 10
    max_positions: int = 5
    position_size_pct: float = 0.10   # 10% of portfolio per position


class BaseStrategy(ABC):
    """
    Base class for all trading strategies.
    
    All strategies must implement:
    - get_universe(): What symbols to scan
    - analyze(): Weekend analysis (if needed)
    - scan(): Daily signal generation
    - score(): Calculate 1-5 score for a symbol
    - check_no_trade(): NO-TRADE conditions
    - check_invalidation(): Exit conditions
    """
    
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.name = config.name
        self.enabled = config.enabled
        
        # Score weights (override in subclass)
        self.score_weights: Dict[str, float] = {}
        
        logger.info(f"Strategy initialized: {self.name}")
    
    @abstractmethod
    def get_universe(self) -> List[str]:
        """
        Get the universe of symbols this strategy trades.
        Must be subset of T212 weekly universe.
        """
        pass
    
    @abstractmethod
    def analyze(self) -> List[Dict]:
        """
        Weekend analysis - precompute data for the week.
        Called on Saturday/Sunday.
        Returns list of analysis results.
        """
        pass
    
    @abstractmethod
    def scan(self) -> List[Signal]:
        """
        Daily scan for trading signals.
        Called once per day at check_time.
        Uses precomputed analysis where possible.
        """
        pass
    
    @abstractmethod
    def score(self, symbol: str, data: Dict) -> Tuple[int, Dict[str, float]]:
        """
        Calculate confidence score (1-5) for a symbol.
        
        Returns:
            (score, score_components)
        """
        pass
    
    @abstractmethod
    def check_no_trade(self, symbol: str) -> Tuple[bool, str]:
        """
        Check NO-TRADE conditions.
        
        Returns:
            (should_skip, reason)
        """
        pass
    
    @abstractmethod
    def check_invalidation(self, symbol: str, position: Dict) -> Tuple[bool, str]:
        """
        Check if position should be closed.
        
        Returns:
            (should_close, reason)
        """
        pass
    
    # ==================== HELPER METHODS ====================
    
    def calculate_weighted_score(self, components: Dict[str, float]) -> int:
        """
        Calculate final 1-5 score from weighted components.
        Each component should be 0-1.
        """
        if not self.score_weights:
            return 3
        
        weighted_sum = 0
        total_weight = 0
        
        for name, weight in self.score_weights.items():
            if name in components:
                weighted_sum += components[name] * weight
                total_weight += weight
        
        if total_weight == 0:
            return 3
        
        avg = weighted_sum / total_weight
        
        # Map to 1-5
        if avg >= 0.8:
            return 5
        elif avg >= 0.65:
            return 4
        elif avg >= 0.5:
            return 3
        elif avg >= 0.35:
            return 2
        else:
            return 1
    
    def should_run_now(self) -> bool:
        """Check if it's time to run the daily scan."""
        from datetime import datetime
        import pytz
        
        ET = pytz.timezone('US/Eastern')
        now = datetime.now(ET)
        
        # Check if within 5 minutes of check_time
        check_minutes = self.config.check_time.hour * 60 + self.config.check_time.minute
        now_minutes = now.hour * 60 + now.minute
        
        return abs(now_minutes - check_minutes) <= 5
