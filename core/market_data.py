"""
core/market_data.py - Safe Market Data Fetcher

Wraps yfinance with proper error handling to prevent crashes.
Validates symbols before fetching data.
Uses lazy imports to avoid circular dependencies.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Lazy imports - loaded on first use
_yf = None
_pd = None

def _get_yf():
    """Lazy load yfinance."""
    global _yf
    if _yf is None:
        import yfinance
        _yf = yfinance
    return _yf

def _get_pd():
    """Lazy load pandas."""
    global _pd
    if _pd is None:
        import pandas
        _pd = pandas
    return _pd

# Cache of known bad symbols (don't retry)
_bad_symbols: set = set()
_good_symbols: set = set()


def clean_symbol(symbol: str) -> str:
    """Clean and validate a symbol string."""
    if not symbol:
        return ""
    
    # Remove common prefixes
    symbol = symbol.replace("$", "").strip().upper()
    
    # Skip symbols starting with numbers
    if symbol and symbol[0].isdigit():
        return ""
    
    # Skip symbols with too many numbers (like SB1D)
    digit_count = sum(1 for c in symbol if c.isdigit())
    if digit_count > 1:
        return ""
    
    # Skip too long symbols (US stocks are 1-5 chars typically)
    if len(symbol) > 5:
        return ""
    
    # Only allow alphanumeric and hyphen
    if not all(c.isalnum() or c == '-' for c in symbol):
        return ""
    
    return symbol


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
        yf = _get_yf()
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


def get_history(symbol: str, period: str = "1mo", validate: bool = True):
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
        yf = _get_yf()
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            _bad_symbols.add(symbol)
            return None
        
        _good_symbols.add(symbol)
        return hist
        
    except Exception as e:
        logger.debug(f"Error getting history for {symbol}: {e}")
        return None


def get_info(symbol: str) -> Optional[Dict[str, Any]]:
    """Get stock info safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if not info or info.get("regularMarketPrice") is None:
            return None
        
        return info
        
    except Exception:
        return None


def get_current_price(symbol: str) -> Optional[float]:
    """Get current price safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        ticker = yf.Ticker(symbol)
        
        # Try fast info first
        try:
            fast = ticker.fast_info
            if hasattr(fast, 'last_price') and fast.last_price:
                return float(fast.last_price)
        except:
            pass
        
        # Fallback to history
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        
        return None
        
    except Exception:
        return None


def get_earnings_dates(symbol: str):
    """Get earnings dates safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        ticker = yf.Ticker(symbol)
        earnings = ticker.earnings_dates
        
        if earnings is None or earnings.empty:
            return None
        
        return earnings
        
    except ImportError as e:
        # lxml not installed
        logger.debug(f"Earnings dates requires lxml: {e}")
        return None
    except Exception:
        return None


def get_news(symbol: str, max_items: int = 10) -> List[Dict]:
    """Get recent news safely."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return []
    
    try:
        yf = _get_yf()
        ticker = yf.Ticker(symbol)
        news = ticker.news
        
        if not news:
            return []
        
        return news[:max_items]
        
    except Exception:
        return []


def batch_validate(symbols: List[str]) -> List[str]:
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
        elif symbol in _bad_symbols:
            continue
        elif is_valid_symbol(symbol):
            valid.append(symbol)
    
    return valid


def clear_cache():
    """Clear symbol caches."""
    global _bad_symbols, _good_symbols
    _bad_symbols = set()
    _good_symbols = set()


def get_cache_stats() -> Dict[str, int]:
    """Get cache statistics."""
    return {
        "good_symbols": len(_good_symbols),
        "bad_symbols": len(_bad_symbols)
    }


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing market_data module...")
    
    # Test symbols
    test_symbols = ["AAPL", "MSFT", "INVALID123", "$SB1D", "2MXP"]
    
    for sym in test_symbols:
        cleaned = clean_symbol(sym)
        print(f"{sym} -> {cleaned or 'INVALID'}")
    
    print("\nTesting AAPL data fetch:")
    hist = get_history("AAPL", period="5d")
    if hist is not None:
        print(f"  Got {len(hist)} days of history")
        print(f"  Latest close: ${hist['Close'].iloc[-1]:.2f}")
    
    price = get_current_price("AAPL")
    if price:
        print(f"  Current price: ${price:.2f}")
    
    print(f"\nCache stats: {get_cache_stats()}")
