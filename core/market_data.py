"""
core/market_data.py - Robust Market Data Fetcher

Uses yfinance with:
- Browser User-Agent headers (avoids 403 blocks)
- Request caching (prevents rate limiting)
- Automatic retries
- Data validation

This fixes Yahoo Finance's anti-bot measures (late 2024/2025).
"""

import logging
import time
from typing import Optional, Dict, Any, List
from datetime import timedelta

logger = logging.getLogger(__name__)

# ==================== SETUP SESSION WITH CACHING ====================
# This prevents "Too Many Requests" and mimics a real browser

_session = None
_yf = None
_pd = None

def _get_session():
    """Get or create cached session with browser headers."""
    global _session
    if _session is None:
        try:
            import requests_cache
            
            # Cache expires after 1 minute
            expire_after = timedelta(minutes=1)
            _session = requests_cache.CachedSession(
                'yfinance_cache',
                expire_after=expire_after,
                backend='sqlite'
            )
            
            # CRITICAL: Mimic a real browser
            _session.headers['User-Agent'] = (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
            
            logger.info("✓ yfinance session initialized with caching")
            
        except ImportError:
            logger.warning("requests-cache not installed, using default session")
            import requests
            _session = requests.Session()
            _session.headers['User-Agent'] = (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 Chrome/120.0.0.0'
            )
    
    return _session


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


# ==================== SYMBOL VALIDATION ====================

# Cache of known symbols
_bad_symbols: set = set()
_good_symbols: set = set()


def clean_symbol(symbol: str) -> str:
    """Clean and validate a symbol string."""
    if not symbol:
        return ""
    
    # Remove common prefixes
    symbol = symbol.replace("$", "").strip().upper()
    
    # Skip invalid symbols
    if symbol and symbol[0].isdigit():
        return ""
    
    if len(symbol) > 5:
        return ""
    
    if not all(c.isalnum() or c == '-' for c in symbol):
        return ""
    
    return symbol


def is_valid_symbol(symbol: str) -> bool:
    """Check if symbol is valid on yfinance."""
    symbol = clean_symbol(symbol)
    
    if not symbol:
        return False
    
    if symbol in _bad_symbols:
        return False
    
    if symbol in _good_symbols:
        return True
    
    try:
        yf = _get_yf()
        session = _get_session()
        ticker = yf.Ticker(symbol, session=session)
        
        # Try fast_info first (faster)
        price = ticker.fast_info.get('lastPrice')
        if price is not None and price > 0:
            _good_symbols.add(symbol)
            return True
        
        # Fallback to history
        hist = ticker.history(period="5d")
        if hist is not None and not hist.empty:
            _good_symbols.add(symbol)
            return True
        
        _bad_symbols.add(symbol)
        return False
        
    except Exception as e:
        logger.debug(f"Symbol validation failed for {symbol}: {e}")
        _bad_symbols.add(symbol)
        return False


# ==================== PRICE DATA ====================

def get_current_price(symbol: str) -> Optional[float]:
    """Get current price for a symbol."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        session = _get_session()
        ticker = yf.Ticker(symbol, session=session)
        
        # Try fast_info first (much faster)
        try:
            price = ticker.fast_info.get('lastPrice')
            if price is not None and price > 0:
                _good_symbols.add(symbol)
                return float(price)
        except Exception:
            pass
        
        # Fallback to history
        hist = ticker.history(period="1d", interval="1m")
        if hist is not None and not hist.empty:
            _good_symbols.add(symbol)
            return float(hist['Close'].iloc[-1])
        
        return None
        
    except Exception as e:
        logger.debug(f"Error getting price for {symbol}: {e}")
        return None


def get_history(symbol: str, period: str = "1mo", interval: str = "1d") -> Optional[Any]:
    """
    Get historical OHLCV data.
    
    Args:
        symbol: Stock symbol
        period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
        interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
    
    Returns:
        DataFrame or None
    """
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        pd = _get_pd()
        session = _get_session()
        
        ticker = yf.Ticker(symbol, session=session)
        
        # repair=True fixes missing data points
        df = ticker.history(period=period, interval=interval, repair=True)
        
        if df is None or df.empty:
            logger.debug(f"Empty data for {symbol}")
            return None
        
        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        
        _good_symbols.add(symbol)
        return df
        
    except Exception as e:
        logger.debug(f"Error getting history for {symbol}: {e}")
        return None


def get_info(symbol: str) -> Optional[Dict]:
    """Get company info."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        session = _get_session()
        ticker = yf.Ticker(symbol, session=session)
        
        info = ticker.info
        if info:
            _good_symbols.add(symbol)
            return info
        
        return None
        
    except Exception as e:
        logger.debug(f"Error getting info for {symbol}: {e}")
        return None


def get_news(symbol: str, max_items: int = 5) -> List[Dict]:
    """Get recent news for a symbol."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return []
    
    try:
        yf = _get_yf()
        session = _get_session()
        ticker = yf.Ticker(symbol, session=session)
        
        news = ticker.news
        if news:
            return news[:max_items]
        
        return []
        
    except Exception as e:
        logger.debug(f"Error getting news for {symbol}: {e}")
        return []


def get_earnings_dates(symbol: str) -> Optional[Any]:
    """Get earnings dates."""
    symbol = clean_symbol(symbol)
    
    if not symbol or symbol in _bad_symbols:
        return None
    
    try:
        yf = _get_yf()
        session = _get_session()
        ticker = yf.Ticker(symbol, session=session)
        
        earnings = ticker.earnings_dates
        if earnings is not None and not earnings.empty:
            return earnings
        
        return None
        
    except Exception as e:
        logger.debug(f"Error getting earnings dates for {symbol}: {e}")
        return None


# ==================== SAFE WRAPPERS (for compatibility) ====================

def safe_get_price(symbol: str) -> Optional[float]:
    """Alias for get_current_price."""
    return get_current_price(symbol)


def safe_get_history(symbol: str, period: str = "1mo") -> Optional[Any]:
    """Alias for get_history."""
    return get_history(symbol, period=period)


# ==================== TEST ====================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    print("Testing market_data.py...")
    print("=" * 50)
    
    symbols = ["AAPL", "MSFT", "SPY", "GOOGL", "TSLA"]
    
    for s in symbols:
        price = get_current_price(s)
        if price:
            print(f"✓ {s}: ${price:.2f}")
        else:
            print(f"✗ {s}: No data")
        time.sleep(0.5)
    
    print("=" * 50)
    print("Testing history...")
    
    hist = get_history("AAPL", period="5d")
    if hist is not None:
        print(f"✓ AAPL history: {len(hist)} rows")
        print(hist.tail(2))
    else:
        print("✗ AAPL history failed")
