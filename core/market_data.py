"""
core/market_data.py - Robust Market Data Fetcher (No yfinance)

Uses Yahoo Finance REST API directly via requests.
This eliminates ALL yfinance/numpy compatibility issues.

Architecture:
- Chart API (v8): prices & history - NO authentication needed
- QuoteSummary API (v10): company info - needs cookie/crumb
- Search API (v1): news - NO authentication needed

Features:
- Separate auth/no-auth request paths (avoids crumb rate-limits)
- Browser User-Agent headers
- Automatic retries with exponential backoff
- In-memory TTL cache
- Data validation
- Returns pandas DataFrames compatible with yfinance output
"""

import logging
import time
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from threading import Lock

import requests
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ==================== YAHOO FINANCE API CONFIG ====================

_BASE_URL = "https://query1.finance.yahoo.com"
_BASE_URL2 = "https://query2.finance.yahoo.com"

_USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
]

# Period/interval maps for v8 chart API
_PERIOD_MAP = {
    "1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo",
    "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y",
    "10y": "10y", "ytd": "ytd", "max": "max",
}

_INTERVAL_MAP = {
    "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m",
    "30m": "30m", "60m": "60m", "90m": "90m", "1h": "1h",
    "1d": "1d", "5d": "5d", "1wk": "1wk", "1mo": "1mo", "3mo": "3mo",
}


# ==================== SESSION MANAGEMENT ====================

_session: Optional[requests.Session] = None
_ua_index = 0

# Crumb auth state (only for quoteSummary)
_crumb: Optional[str] = None
_crumb_lock = Lock()
_crumb_expiry: Optional[datetime] = None
_crumb_failures: int = 0
_CRUMB_MAX_FAILURES = 3  # Stop trying crumb after N consecutive failures

# In-memory cache: key -> (data, expiry_time)
_cache: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 60  # 1 minute for prices
_CACHE_TTL_LONG = 300    # 5 minutes for info/news


def _get_session() -> requests.Session:
    """Get or create session with browser headers."""
    global _session, _ua_index
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": _USER_AGENTS[_ua_index % len(_USER_AGENTS)],
            "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        })
        logger.info("✓ Yahoo Finance session initialized")
    return _session


def _rotate_user_agent():
    """Rotate User-Agent on rate limit."""
    global _ua_index, _session
    _ua_index += 1
    if _session:
        _session.headers["User-Agent"] = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]


# ==================== CACHE ====================

def _cache_get(key: str) -> Optional[Any]:
    """Get from cache if not expired."""
    if key in _cache:
        data, expiry = _cache[key]
        if datetime.now() < expiry:
            return data
        else:
            del _cache[key]
    return None


def _cache_set(key: str, data: Any, ttl: int = _CACHE_TTL_SECONDS):
    """Store in cache with TTL."""
    _cache[key] = (data, datetime.now() + timedelta(seconds=ttl))


# ==================== REQUEST FUNCTIONS ====================

def _simple_request(url: str, params: Dict = None, retries: int = 2) -> Optional[Dict]:
    """
    Simple GET request - NO crumb auth.
    Used for: v8/finance/chart, v1/finance/search
    These endpoints work without cookies/crumb.
    """
    session = _get_session()
    if params is None:
        params = {}

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=15)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                wait = min(2 ** (attempt + 1), 10)
                logger.debug(f"Rate limited on {url}, waiting {wait}s...")
                _rotate_user_agent()
                time.sleep(wait)
                continue

            logger.debug(f"Yahoo returned {resp.status_code} for {url}")
            return None

        except requests.exceptions.Timeout:
            logger.debug(f"Timeout attempt {attempt + 1} for {url}")
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            logger.debug(f"Connection error for {url}")
            time.sleep(2)
        except json.JSONDecodeError:
            logger.debug(f"Invalid JSON from {url}")
            return None
        except Exception as e:
            logger.debug(f"Request error for {url}: {e}")
            time.sleep(1)

    return None


def _get_crumb() -> Optional[str]:
    """
    Get Yahoo Finance crumb token.
    Only called for endpoints that need it (quoteSummary).
    Caches result and backs off on repeated failures.
    """
    global _crumb, _crumb_expiry, _crumb_failures

    with _crumb_lock:
        # Return cached crumb if valid
        if _crumb and _crumb_expiry and datetime.now() < _crumb_expiry:
            return _crumb

        # If we've failed too many times, stop trying for a while
        if _crumb_failures >= _CRUMB_MAX_FAILURES:
            return None

        session = _get_session()

        try:
            # Step 1: Get cookies by visiting Yahoo
            try:
                session.get("https://fc.yahoo.com", timeout=8, allow_redirects=True)
            except Exception:
                pass  # Cookies may still have been set

            time.sleep(0.5)  # Small delay between requests

            # Step 2: Fetch crumb
            resp = session.get(
                f"{_BASE_URL2}/v1/test/getcrumb",
                timeout=8,
                allow_redirects=True,
            )

            if resp.status_code == 200 and resp.text and len(resp.text) < 50:
                _crumb = resp.text.strip()
                _crumb_expiry = datetime.now() + timedelta(hours=1)  # Cache for 1 hour
                _crumb_failures = 0
                logger.debug(f"Got Yahoo crumb OK")
                return _crumb

            if resp.status_code == 429:
                logger.warning("Crumb endpoint rate limited - will use fallback methods")
                _crumb_failures += 1
                return None

            logger.debug(f"Crumb fetch returned {resp.status_code}")
            _crumb_failures += 1
            return None

        except Exception as e:
            logger.debug(f"Crumb fetch error: {e}")
            _crumb_failures += 1
            return None


def _auth_request(url: str, params: Dict = None, retries: int = 2) -> Optional[Dict]:
    """
    Authenticated request WITH crumb.
    Used for: v10/finance/quoteSummary
    Falls back to no-crumb if crumb unavailable.
    """
    session = _get_session()
    if params is None:
        params = {}

    crumb = _get_crumb()
    if crumb:
        params["crumb"] = crumb

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=15)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (401, 403):
                # Try without crumb
                params.pop("crumb", None)
                logger.debug(f"Auth error {resp.status_code}, retrying without crumb...")
                continue

            if resp.status_code == 429:
                wait = min(2 ** (attempt + 1), 10)
                logger.debug(f"Rate limited, waiting {wait}s...")
                _rotate_user_agent()
                time.sleep(wait)
                continue

            logger.debug(f"Yahoo returned {resp.status_code} for {url}")
            return None

        except requests.exceptions.Timeout:
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            time.sleep(2)
        except json.JSONDecodeError:
            return None
        except Exception as e:
            logger.debug(f"Auth request error: {e}")
            time.sleep(1)

    return None


# ==================== SYMBOL VALIDATION ====================

_bad_symbols: set = set()
_good_symbols: set = set()


def clean_symbol(symbol: str) -> str:
    """Clean and validate a symbol string."""
    if not symbol:
        return ""
    symbol = symbol.replace("$", "").strip().upper()
    if symbol and symbol[0].isdigit():
        return ""
    if len(symbol) > 5:
        return ""
    if not all(c.isalnum() or c in ("-", ".") for c in symbol):
        return ""
    return symbol


def is_valid_symbol(symbol: str) -> bool:
    """Check if symbol is valid on Yahoo Finance."""
    symbol = clean_symbol(symbol)
    if not symbol:
        return False
    if symbol in _bad_symbols:
        return False
    if symbol in _good_symbols:
        return True

    price = get_current_price(symbol)
    if price is not None and price > 0:
        _good_symbols.add(symbol)
        return True
    _bad_symbols.add(symbol)
    return False


# ==================== PRICE DATA (no auth needed) ====================

def get_current_price(symbol: str) -> Optional[float]:
    """Get current/latest price for a symbol. Uses chart API (no crumb)."""
    symbol = clean_symbol(symbol)
    if not symbol or symbol in _bad_symbols:
        return None

    cache_key = f"price:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"{_BASE_URL}/v8/finance/chart/{symbol}"
        data = _simple_request(url, {
            "range": "1d",
            "interval": "5m",
            "includePrePost": "true",
        })

        if not data:
            return None

        result = data.get("chart", {}).get("result")
        if not result:
            _bad_symbols.add(symbol)
            return None

        meta = result[0].get("meta", {})

        # Try regularMarketPrice first
        price = meta.get("regularMarketPrice")
        if price is None:
            price = meta.get("previousClose")
        if price is None:
            # Last data point
            indicators = result[0].get("indicators", {})
            quotes = indicators.get("quote", [{}])[0]
            closes = quotes.get("close", [])
            valid = [c for c in closes if c is not None]
            if valid:
                price = valid[-1]

        if price is not None and price > 0:
            price = float(price)
            _good_symbols.add(symbol)
            _cache_set(cache_key, price)
            return price

        return None

    except Exception as e:
        logger.debug(f"Error getting price for {symbol}: {e}")
        return None


def get_history(symbol: str, period: str = "1mo", interval: str = "1d", **kwargs) -> Optional[pd.DataFrame]:
    """
    Get historical OHLCV data. Uses chart API (no crumb needed).

    Args:
        symbol: Stock symbol
        period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
        interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
        Index: DatetimeIndex
    """
    symbol = clean_symbol(symbol)
    if not symbol or symbol in _bad_symbols:
        return None

    cache_key = f"hist:{symbol}:{period}:{interval}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        yf_period = _PERIOD_MAP.get(period, period)
        yf_interval = _INTERVAL_MAP.get(interval, interval)

        url = f"{_BASE_URL}/v8/finance/chart/{symbol}"
        data = _simple_request(url, {
            "range": yf_period,
            "interval": yf_interval,
            "includePrePost": "false",
            "events": "div,splits",
        })

        if not data:
            return None

        result = data.get("chart", {}).get("result")
        if not result:
            logger.debug(f"No chart data for {symbol}")
            return None

        chart = result[0]
        timestamps = chart.get("timestamp")
        if not timestamps:
            logger.debug(f"No timestamps for {symbol}")
            return None

        indicators = chart.get("indicators", {})
        quotes = indicators.get("quote", [{}])[0]

        df = pd.DataFrame({
            "Open": quotes.get("open", []),
            "High": quotes.get("high", []),
            "Low": quotes.get("low", []),
            "Close": quotes.get("close", []),
            "Volume": quotes.get("volume", []),
        })

        # Adjusted close
        adj = indicators.get("adjclose", [{}])
        if adj and adj[0].get("adjclose"):
            df["Adj Close"] = adj[0]["adjclose"]
        else:
            df["Adj Close"] = df["Close"]

        # Set datetime index
        meta = chart.get("meta", {})
        tz = meta.get("exchangeTimezoneName", "US/Eastern")

        try:
            df.index = pd.to_datetime(timestamps, unit="s", utc=True)
            try:
                df.index = df.index.tz_convert(tz)
            except Exception:
                pass
        except Exception:
            df.index = pd.to_datetime(timestamps, unit="s")

        df.index.name = "Date"

        # Clean up
        df = df.dropna(subset=["Open", "High", "Low", "Close"], how="all")
        if df.empty:
            return None

        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(np.int64)

        _good_symbols.add(symbol)
        _cache_set(cache_key, df)
        return df

    except Exception as e:
        logger.debug(f"Error getting history for {symbol}: {e}")
        return None


# ==================== COMPANY INFO (needs auth) ====================

def get_info(symbol: str) -> Optional[Dict]:
    """Get company info. Uses quoteSummary API (may need crumb)."""
    symbol = clean_symbol(symbol)
    if not symbol or symbol in _bad_symbols:
        return None

    cache_key = f"info:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Try quoteSummary first (rich data, may need crumb)
    info = _get_info_quotesummary(symbol)

    # Fallback: extract what we can from the chart API (no crumb)
    if not info:
        info = _get_info_from_chart(symbol)

    if info:
        _good_symbols.add(symbol)
        _cache_set(cache_key, info, _CACHE_TTL_LONG)

    return info


def _get_info_quotesummary(symbol: str) -> Optional[Dict]:
    """Get full info from quoteSummary endpoint."""
    try:
        modules = "price,summaryDetail,defaultKeyStatistics,assetProfile,financialData,earningsHistory,earningsTrend,calendarEvents"
        url = f"{_BASE_URL2}/v10/finance/quoteSummary/{symbol}"
        data = _auth_request(url, {"modules": modules})

        if not data:
            return None

        summary = data.get("quoteSummary", {}).get("result")
        if not summary:
            return None

        result = summary[0]

        def _raw(val):
            if isinstance(val, dict):
                return val.get("raw")
            return val

        info = {}

        # Price module
        pd_data = result.get("price", {})
        info["shortName"] = pd_data.get("shortName")
        info["longName"] = pd_data.get("longName")
        info["symbol"] = pd_data.get("symbol", symbol)
        info["currency"] = pd_data.get("currency")
        info["exchange"] = pd_data.get("exchangeName")
        info["quoteType"] = pd_data.get("quoteType")
        info["regularMarketPrice"] = _raw(pd_data.get("regularMarketPrice"))
        info["currentPrice"] = info["regularMarketPrice"]
        info["regularMarketChange"] = _raw(pd_data.get("regularMarketChange"))
        info["regularMarketChangePercent"] = _raw(pd_data.get("regularMarketChangePercent"))
        info["marketCap"] = _raw(pd_data.get("marketCap"))
        info["regularMarketVolume"] = _raw(pd_data.get("regularMarketVolume"))

        # Summary detail
        sd = result.get("summaryDetail", {})
        for key in ["previousClose", "open", "dayHigh", "dayLow", "volume",
                     "averageVolume", "averageVolume10days", "fiftyTwoWeekHigh",
                     "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
                     "trailingPE", "forwardPE", "dividendYield", "beta"]:
            info[key] = _raw(sd.get(key))

        # Default key stats
        dks = result.get("defaultKeyStatistics", {})
        for key in ["enterpriseValue", "forwardEps", "trailingEps",
                     "pegRatio", "shortPercentOfFloat", "sharesOutstanding",
                     "heldPercentInsiders", "heldPercentInstitutions"]:
            info[key] = _raw(dks.get(key))

        # Asset profile
        ap = result.get("assetProfile", {})
        info["sector"] = ap.get("sector")
        info["industry"] = ap.get("industry")
        info["longBusinessSummary"] = ap.get("longBusinessSummary")
        info["country"] = ap.get("country")
        info["fullTimeEmployees"] = ap.get("fullTimeEmployees")

        # Financial data
        fd = result.get("financialData", {})
        for key in ["targetHighPrice", "targetLowPrice", "targetMeanPrice",
                     "recommendationMean", "recommendationKey", "numberOfAnalystOpinions",
                     "totalRevenue", "revenuePerShare", "revenueGrowth",
                     "grossMargins", "operatingMargins", "profitMargins"]:
            info[key] = _raw(fd.get(key))

        # Earnings history
        eh = result.get("earningsHistory", {})
        if eh and eh.get("history"):
            info["_earningsHistory"] = eh["history"]

        # Earnings trend
        et = result.get("earningsTrend", {})
        if et and et.get("trend"):
            info["_earningsTrend"] = et["trend"]

        # Calendar events
        ce = result.get("calendarEvents", {})
        if ce and ce.get("earnings"):
            edates = ce["earnings"].get("earningsDate", [])
            if edates:
                info["_nextEarningsDate"] = _raw(edates[0])

        # Filter None
        info = {k: v for k, v in info.items() if v is not None}
        return info if info else None

    except Exception as e:
        logger.debug(f"quoteSummary error for {symbol}: {e}")
        return None


def _get_info_from_chart(symbol: str) -> Optional[Dict]:
    """
    Fallback: extract basic info from the chart API.
    Works WITHOUT crumb. Gives us price, volume, exchange info.
    """
    try:
        url = f"{_BASE_URL}/v8/finance/chart/{symbol}"
        data = _simple_request(url, {
            "range": "5d",
            "interval": "1d",
            "includePrePost": "false",
        })

        if not data:
            return None

        result = data.get("chart", {}).get("result")
        if not result:
            return None

        meta = result[0].get("meta", {})
        indicators = result[0].get("indicators", {})
        quotes = indicators.get("quote", [{}])[0]
        volumes = [v for v in quotes.get("volume", []) if v is not None]

        info = {
            "symbol": meta.get("symbol", symbol),
            "shortName": meta.get("shortName", symbol),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "currentPrice": meta.get("regularMarketPrice"),
            "previousClose": meta.get("chartPreviousClose") or meta.get("previousClose"),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
            "fiftyDayAverage": meta.get("fiftyDayAverage"),
            "twoHundredDayAverage": meta.get("twoHundredDayAverage"),
        }

        # Estimate average volume from recent data
        if volumes:
            info["averageVolume"] = int(sum(volumes) / len(volumes))
            info["volume"] = volumes[-1] if volumes else None

        # Filter None
        info = {k: v for k, v in info.items() if v is not None}
        return info if len(info) > 2 else None

    except Exception as e:
        logger.debug(f"Chart info fallback error for {symbol}: {e}")
        return None


# ==================== NEWS (no auth needed) ====================

def get_news(symbol: str, max_items: int = 5) -> List[Dict]:
    """Get recent news. Uses search API (no crumb)."""
    symbol = clean_symbol(symbol)
    if not symbol or symbol in _bad_symbols:
        return []

    cache_key = f"news:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"{_BASE_URL}/v1/finance/search"
        data = _simple_request(url, {
            "q": symbol,
            "newsCount": max_items,
            "quotesCount": 0,
            "enableFuzzyQuery": "false",
            "newsQueryId": "tss_stock_news",
        })

        if not data:
            return []

        news_items = data.get("news", [])

        formatted = []
        for item in news_items[:max_items]:
            formatted.append({
                "title": item.get("title", ""),
                "publisher": item.get("publisher", "Unknown"),
                "link": item.get("link", ""),
                "providerPublishTime": item.get("providerPublishTime", 0),
                "type": item.get("type", "STORY"),
                "relatedTickers": item.get("relatedTickers", []),
            })

        _cache_set(cache_key, formatted, _CACHE_TTL_LONG)
        return formatted

    except Exception as e:
        logger.debug(f"Error getting news for {symbol}: {e}")
        return []


# ==================== EARNINGS DATES ====================

def get_earnings_dates(symbol: str) -> Optional[pd.DataFrame]:
    """Get earnings dates (past and upcoming)."""
    symbol = clean_symbol(symbol)
    if not symbol or symbol in _bad_symbols:
        return None

    cache_key = f"earnings:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        # Try quoteSummary (needs crumb)
        url = f"{_BASE_URL2}/v10/finance/quoteSummary/{symbol}"
        data = _auth_request(url, {"modules": "earningsHistory,calendarEvents"})

        if not data:
            # Fallback: try to get earnings from the info we may already have
            info = get_info(symbol)
            if info and "_earningsHistory" in info:
                return _parse_earnings_from_info(info)
            return None

        summary = data.get("quoteSummary", {}).get("result")
        if not summary:
            return None

        result = summary[0]
        rows = []

        def _raw(val):
            if isinstance(val, dict):
                return val.get("raw")
            return val

        # Past earnings
        eh = result.get("earningsHistory", {})
        for item in eh.get("history", []):
            date_val = _raw(item.get("quarter"))
            if date_val:
                rows.append({
                    "date": datetime.fromtimestamp(date_val) if isinstance(date_val, (int, float)) else date_val,
                    "EPS Estimate": _raw(item.get("epsEstimate")),
                    "Reported EPS": _raw(item.get("epsActual")),
                    "EPS Difference": _raw(item.get("epsDifference")),
                    "Surprise(%)": _raw(item.get("surprisePercent")),
                })

        # Future earnings
        ce = result.get("calendarEvents", {})
        edates = ce.get("earnings", {}).get("earningsDate", [])
        for fd in edates:
            date_val = _raw(fd)
            if date_val:
                rows.append({
                    "date": datetime.fromtimestamp(date_val) if isinstance(date_val, (int, float)) else date_val,
                    "EPS Estimate": None,
                    "Reported EPS": None,
                    "EPS Difference": None,
                    "Surprise(%)": None,
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        if "date" in df.columns:
            df.index = pd.to_datetime(df["date"])
            df = df.drop(columns=["date"])
            df.index.name = "Earnings Date"
            df = df.sort_index()

        _cache_set(cache_key, df, _CACHE_TTL_LONG)
        return df

    except Exception as e:
        logger.debug(f"Error getting earnings dates for {symbol}: {e}")
        return None


def _parse_earnings_from_info(info: Dict) -> Optional[pd.DataFrame]:
    """Extract earnings DataFrame from cached info dict."""
    try:
        rows = []

        def _raw(val):
            if isinstance(val, dict):
                return val.get("raw")
            return val

        for item in info.get("_earningsHistory", []):
            date_val = _raw(item.get("quarter"))
            if date_val:
                rows.append({
                    "date": datetime.fromtimestamp(date_val) if isinstance(date_val, (int, float)) else date_val,
                    "EPS Estimate": _raw(item.get("epsEstimate")),
                    "Reported EPS": _raw(item.get("epsActual")),
                    "EPS Difference": _raw(item.get("epsDifference")),
                    "Surprise(%)": _raw(item.get("surprisePercent")),
                })

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["date"])
        df = df.drop(columns=["date"])
        df.index.name = "Earnings Date"
        df = df.sort_index()
        return df
    except Exception:
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

    print("Testing market_data.py (direct Yahoo Finance API)...")
    print("=" * 55)

    # Test 1: Prices (chart API - no crumb)
    print("\n[1] Prices (chart API - no auth needed)")
    symbols = ["AAPL", "MSFT", "SPY", "GOOGL", "TSLA"]
    for s in symbols:
        price = get_current_price(s)
        if price:
            print(f"  ✓ {s}: ${price:.2f}")
        else:
            print(f"  ✗ {s}: No data")
        time.sleep(0.3)

    # Test 2: History (chart API - no crumb)
    print("\n[2] History (chart API - no auth needed)")
    hist = get_history("AAPL", period="5d")
    if hist is not None:
        print(f"  ✓ AAPL 5d history: {len(hist)} rows")
        print(hist.tail(2).to_string(max_cols=5))
    else:
        print("  ✗ AAPL history failed")

    hist2 = get_history("SPY", period="1y")
    if hist2 is not None:
        print(f"  ✓ SPY 1y history: {len(hist2)} rows")
    else:
        print("  ✗ SPY 1y history failed")

    # Test 3: Info (quoteSummary - needs crumb, has fallback)
    print("\n[3] Info (quoteSummary - crumb with fallback)")
    info = get_info("AAPL")
    if info:
        print(f"  ✓ AAPL: {info.get('shortName')} | Sector: {info.get('sector', 'N/A')} | MCap: {info.get('marketCap', 'N/A')}")
    else:
        print("  ✗ AAPL info failed")

    # Test 4: News (search API - no crumb)
    print("\n[4] News (search API - no auth needed)")
    news = get_news("AAPL", max_items=3)
    if news:
        for n in news:
            print(f"  📰 {n['title'][:65]}")
    else:
        print("  ✗ AAPL news failed")

    # Test 5: Earnings dates (quoteSummary)
    print("\n[5] Earnings dates")
    earnings = get_earnings_dates("AAPL")
    if earnings is not None:
        print(f"  ✓ AAPL earnings: {len(earnings)} entries")
    else:
        print("  ✗ AAPL earnings dates failed")

    print("\n" + "=" * 55)
    print("Done!")
