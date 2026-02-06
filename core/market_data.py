"""
core/market_data.py - Safe Market Data Fetcher

Wraps yfinance with proper error handling to prevent crashes.
Validates symbols before fetching data.
"""

import logging
from typing import Optional, Dict, Any
from functools import lru_cache
import time

import yfinance as yf
import pandas as pd

from core.t212_client import clean_symbol

logger = logging.getLogger(__name__)

# Cache of known bad symbols (don't retry)
_bad_symbols: set = set()
_good_symbols: set = set()


def is_valid_symbol(symbol: str) -> bool:
    """
    Check if symbol is valid on yfinance.
    Uses caching to avoid repeated API calls.
    """
    symbol = clean_symbol(symbol)
    
    if not symbol:
        return False
    
    # Check caches first
    if symbol in _bad_symbols:
        return False
    if symbol in _good_symbols:
        return True
    
    # Try to validate
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        
        if hist.empty:
            _bad_symbols.add(symbol)
            return False
        
        _good_symbols.add(symbol)
        return True
        
    except Exception:
        _bad_symbols.add(symbol)
        return False


def get_history(
    symbol: str,
    period: str = "1mo",
    validate: bool = True
) -> Optional[pd.DataFrame]:
    """
    Get historical data for a symbol safely.
    
    Args:
        symbol: Stock symbol
        period: Time period (1d, 5d, 1mo, 3mo, 1y, 2y)
        validate: Whether to validate symbol first
    
    Returns:
        DataFrame or None if error
    """
    symbol = clean_symbol(symbol)
    
    if not symbol:
        return None
    
    # Skip known bad symbols
    if symbol in _bad_symbols:
        return None
    
    # Validate if requested
    if validate and symbol not in _good_symbols:
        if not is_valid_symbol(symbol):
            return None
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            _bad_symbols.add(symbol)
            return None
        
        _good_symbols.add(symbol)
        return hist
        
    except Exception as e:
        logger.debug(f"Failed to get history for {symbol}: {e}")
        _bad_symbols.add(symbol)
        return None


def get_info(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get stock info safely.
    
    Returns:
        Info dict or None if error
    """
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if not info or not info.get('symbol'):
            # Sometimes yfinance returns empty info
            _bad_symbols.add(symbol)
            return None
        
        _good_symbols.add(symbol)
        return info
        
    except Exception as e:
        logger.debug(f"Failed to get info for {symbol}: {e}")
        _bad_symbols.add(symbol)
        return None


def get_current_price(symbol: str) -> Optional[float]:
    """Get current/last price safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        
        if hist.empty:
            _bad_symbols.add(symbol)
            return None
        
        _good_symbols.add(symbol)
        return float(hist['Close'].iloc[-1])
        
    except Exception:
        _bad_symbols.add(symbol)
        return None


def get_earnings_dates(symbol: str) -> Optional[pd.DataFrame]:
    """Get earnings dates safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        ticker = yf.Ticker(symbol)
        earnings = ticker.earnings_dates
        
        if earnings is None or earnings.empty:
            return None
        
        return earnings
        
    except Exception:
        return None


def get_news(symbol: str, max_items: int = 5) -> list:
    """Get recent news safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return []
    
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        
        if not news:
            return []
        
        return news[:max_items]
        
    except Exception:
        return []


def batch_validate(symbols: list) -> list:
    """
    Validate multiple symbols efficiently.
    Returns list of valid symbols.
    """
    valid = []
    
    for symbol in symbols:
        symbol = clean_symbol(symbol)
        
        if not symbol:
            continue
        
        if symbol in _good_symbols:
            valid.append(symbol)
            continue
        
        if symbol in _bad_symbols:
            continue
        
        # Need to validate
        if is_valid_symbol(symbol):
            valid.append(symbol)
        
        # Small delay to avoid rate limiting
        time.sleep(0.1)
    
    return valid


def clear_cache():
    """Clear symbol caches."""
    global _bad_symbols, _good_symbols
    _bad_symbols = set()
    _good_symbols = set()


def get_cache_stats() -> Dict:
    """Get cache statistics."""
    return {
        "good_symbols": len(_good_symbols),
        "bad_symbols": len(_bad_symbols),
        "sample_bad": list(_bad_symbols)[:10]
    }
