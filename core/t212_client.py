"""
core/t212_client.py - Trading212 API Client

Based on official docs: https://docs.trading212.com/api

Key limitations:
- LIVE: Only MARKET orders
- Sell orders use NEGATIVE quantity
"""

import base64
import requests
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def clean_symbol(symbol: str) -> str:
    """
    Clean stock symbol for yfinance compatibility.
    
    Handles:
    - $ prefix ($AAPL -> AAPL)
    - Dots (BRK.B -> BRK-B)
    - Spaces
    - Weird FMP symbols (filters them out)
    """
    if not symbol:
        return ""
    
    # Remove $ prefix
    symbol = symbol.lstrip('$')
    
    # Strip whitespace
    symbol = symbol.strip()
    
    # Replace . with - (for BRK.B -> BRK-B)
    symbol = symbol.replace('.', '-')
    
    # Uppercase
    symbol = symbol.upper()
    
    # Filter out invalid symbols:
    # - Must be 1-5 characters for US stocks
    # - Must be alphanumeric (with possible -)
    # - Skip if it has numbers at the start (like 2MXP)
    # - Skip if it looks like a weird derivative (contains multiple numbers)
    
    if len(symbol) < 1 or len(symbol) > 5:
        return ""
    
    # Skip if starts with number
    if symbol[0].isdigit():
        return ""
    
    # Skip if has more than one number (likely not a real stock)
    digit_count = sum(1 for c in symbol if c.isdigit())
    if digit_count > 1:
        return ""
    
    # Must be alphanumeric or contain -
    if not all(c.isalnum() or c == '-' for c in symbol):
        return ""
    
    return symbol


def validate_symbol(symbol: str) -> bool:
    """
    Validate that symbol exists on yfinance.
    Quick check without full data download.
    """
    symbol = clean_symbol(symbol)
    if not symbol:
        return False
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        # Quick check - just get info
        info = ticker.info
        # If we get a valid response with a price, it's valid
        if info and info.get('regularMarketPrice'):
            return True
        if info and info.get('currentPrice'):
            return True
        return False
    except:
        return False


@dataclass
class Instrument:
    ticker: str      # AAPL_US_EQ
    symbol: str      # AAPL
    name: str
    type: str
    currency: str


@dataclass
class Position:
    ticker: str
    symbol: str
    quantity: float
    avg_price: float
    current_price: float
    pnl: float
    pnl_pct: float


@dataclass
class Account:
    id: str
    currency: str
    free_cash: float
    invested: float
    total_value: float


class RateLimiter:
    def __init__(self):
        self.last_calls = {}
        self.limits = {
            "account": 6, "instruments": 55, "positions": 2,
            "orders": 6, "market_order": 2, "default": 2
        }
    
    def wait(self, key: str):
        limit = self.limits.get(key, 2)
        elapsed = time.time() - self.last_calls.get(key, 0)
        if elapsed < limit:
            time.sleep(limit - elapsed)
        self.last_calls[key] = time.time()


class T212Client:
    """Trading212 API Client."""
    
    def __init__(self, paper: bool = True):
        if not config.T212_API_KEY or not config.T212_API_SECRET:
            raise ValueError("T212_API_KEY and T212_API_SECRET required")
        
        self.paper = paper
        env = "demo" if paper else "live"
        self.base_url = f"https://{env}.trading212.com/api/v0"
        
        creds = f"{config.T212_API_KEY}:{config.T212_API_SECRET}"
        auth = base64.b64encode(creds.encode()).decode()
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        })
        
        self.rate_limiter = RateLimiter()
        self._instruments: Dict[str, Instrument] = {}
        
        logger.info(f"T212 client initialized ({env})")
    
    def _request(self, method: str, endpoint: str, rate_key: str = "default",
                 params: Dict = None, data: Dict = None) -> Any:
        """Make API request."""
        self.rate_limiter.wait(rate_key)
        
        for attempt in range(3):
            try:
                resp = self.session.request(
                    method, f"{self.base_url}{endpoint}",
                    params=params, json=data, timeout=30
                )
                
                if resp.status_code in [200, 201]:
                    return resp.json() if resp.text else {}
                elif resp.status_code == 204:
                    return {"ok": True}
                elif resp.status_code == 429:
                    time.sleep(60)
                    continue
                elif resp.status_code == 401:
                    raise ValueError("Auth failed")
                else:
                    logger.error(f"API error {resp.status_code}: {resp.text}")
                    if attempt < 2:
                        time.sleep(5)
                        continue
                    return None
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}")
                if attempt < 2:
                    time.sleep(5)
        return None
    
    # === Account ===
    def get_account(self) -> Optional[Account]:
        """Get account info."""
        data = self._request("GET", "/equity/account/summary", "account")
        if not data:
            return None
        
        cash = data.get("cash", {})
        inv = data.get("investments", {})
        
        free = cash.get("availableToTrade", 0) if isinstance(cash, dict) else 0
        invested = inv.get("totalCost", 0) if isinstance(inv, dict) else 0
        
        return Account(
            id=str(data.get("id", "")),
            currency=data.get("currency", "EUR"),
            free_cash=float(free),
            invested=float(invested),
            total_value=float(data.get("totalValue", free + invested))
        )
    
    # === Instruments ===
    def get_all_instruments(self, refresh: bool = False) -> List[Instrument]:
        """Get ALL tradeable instruments."""
        if self._instruments and not refresh:
            return list(self._instruments.values())
        
        logger.info("Fetching all T212 instruments...")
        data = self._request("GET", "/equity/metadata/instruments", "instruments")
        
        if not data:
            return []
        
        self._instruments = {}
        instruments = []
        
        for item in data:
            ticker = item.get("ticker", "")
            symbol = clean_symbol(ticker.split("_")[0])
            
            if not symbol:
                continue
            
            inst = Instrument(
                ticker=ticker,
                symbol=symbol,
                name=item.get("name", ""),
                type=item.get("type", ""),
                currency=item.get("currencyCode", "")
            )
            instruments.append(inst)
            self._instruments[ticker] = inst
            self._instruments[symbol] = inst
        
        logger.info(f"Loaded {len(instruments)} instruments")
        return instruments
    
    def get_ticker(self, symbol: str) -> Optional[str]:
        """Get T212 ticker for symbol."""
        symbol = clean_symbol(symbol)
        if not self._instruments:
            self.get_all_instruments()
        
        if symbol in self._instruments:
            return self._instruments[symbol].ticker
        
        for pattern in [f"{symbol}_US_EQ", f"{symbol}_EQ"]:
            if pattern in self._instruments:
                return pattern
        return None
    
    def is_tradeable(self, symbol: str) -> bool:
        """Check if symbol is on T212."""
        return self.get_ticker(symbol) is not None
    
    # === Positions ===
    def get_positions(self) -> List[Position]:
        """Get open positions."""
        data = self._request("GET", "/equity/positions", "positions")
        if not data:
            return []
        
        positions = []
        for item in data:
            ticker = item.get("ticker", "")
            positions.append(Position(
                ticker=ticker,
                symbol=clean_symbol(ticker.split("_")[0]),
                quantity=float(item.get("quantity", 0)),
                avg_price=float(item.get("averagePrice", 0)),
                current_price=float(item.get("currentPrice", 0)),
                pnl=float(item.get("ppl", 0)),
                pnl_pct=float(item.get("pplPercentage", 0)) * 100
            ))
        return positions
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for symbol."""
        symbol = clean_symbol(symbol)
        for pos in self.get_positions():
            if pos.symbol == symbol:
                return pos
        return None
    
    # === Orders ===
    def buy(self, symbol: str, quantity: float) -> Optional[Dict]:
        """Place buy order."""
        ticker = self.get_ticker(symbol)
        if not ticker:
            logger.error(f"Symbol not tradeable: {symbol}")
            return None
        
        # Round quantity to 2 decimal places (T212 requirement)
        quantity = round(abs(quantity), 2)
        
        if quantity < 0.01:
            logger.error(f"Quantity too small: {quantity}")
            return None
        
        return self._request("POST", "/equity/orders/market", "market_order",
                           data={"ticker": ticker, "quantity": quantity})
    
    def sell(self, symbol: str, quantity: float) -> Optional[Dict]:
        """Place sell order (negative quantity)."""
        ticker = self.get_ticker(symbol)
        if not ticker:
            return None
        
        # Round quantity to 2 decimal places (T212 requirement)
        quantity = round(abs(quantity), 2)
        
        if quantity < 0.01:
            logger.error(f"Quantity too small: {quantity}")
            return None
        
        return self._request("POST", "/equity/orders/market", "market_order",
                           data={"ticker": ticker, "quantity": -quantity})
    
    def close_position(self, symbol: str) -> Optional[Dict]:
        """Close entire position."""
        pos = self.get_position(symbol)
        if not pos or pos.quantity == 0:
            return None
        return self.sell(symbol, pos.quantity)
    
    # === Test ===
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            account = self.get_account()
            if account:
                logger.info(f"✓ Connected: {account.currency} {account.total_value:,.2f}")
                return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
        return False
