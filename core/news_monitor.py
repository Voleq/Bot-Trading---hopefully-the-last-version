"""
core/news_monitor.py - Real-Time News Monitoring

Monitors news during market hours for:
1. Earnings releases
2. Material news that could affect positions
3. Market-moving events

Sources:
- yfinance news (free)
- FMP news API (free tier)

Runs continuously during market hours.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum
import threading

import requests

import config
from core import market_data
from core.telegram import Telegram

logger = logging.getLogger(__name__)


class NewsImpact(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass
class NewsItem:
    symbol: str
    headline: str
    source: str
    timestamp: datetime
    url: str
    impact: NewsImpact
    keywords: List[str]


class NewsMonitor:
    """
    Real-time news monitoring during market hours.
    
    Checks for:
    - Earnings releases
    - FDA approvals/rejections
    - Analyst upgrades/downgrades
    - Lawsuits/investigations
    - Management changes
    - Guidance updates
    - M&A news
    """
    
    # Keywords for classification
    POSITIVE_KEYWORDS = [
        "beats", "exceeds", "raises", "upgraded", "buy", "outperform",
        "approval", "approved", "wins", "awarded", "record", "surge",
        "soars", "jumps", "rallies", "breakthrough", "innovation",
        "partnership", "acquisition", "dividend", "buyback", "profit"
    ]
    
    NEGATIVE_KEYWORDS = [
        "misses", "disappoints", "lowers", "downgraded", "sell", "underperform",
        "rejection", "rejected", "loses", "lawsuit", "investigation", "probe",
        "plunges", "crashes", "tumbles", "warning", "recall", "fraud",
        "bankruptcy", "layoffs", "cuts", "loss", "decline", "weak"
    ]
    
    MATERIAL_KEYWORDS = [
        "earnings", "revenue", "guidance", "outlook", "forecast",
        "fda", "sec", "doj", "ftc", "ceo", "cfo", "merger", "acquisition",
        "buyout", "takeover", "spin-off", "restructuring", "bankruptcy"
    ]
    
    def __init__(self):
        self.telegram = Telegram()
        
        # Track seen news to avoid duplicates
        self._seen_news: Set[str] = set()
        self._news_cache: Dict[str, List[NewsItem]] = {}
        self._last_check: Dict[str, datetime] = {}
        
        # Watchlist (symbols to monitor)
        self._watchlist: Set[str] = set()
        
        # Check interval (seconds)
        self.check_interval = 60  # Check every minute during market hours
        
        # Running flag
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        logger.info("News Monitor initialized")
    
    def add_to_watchlist(self, symbols: List[str]):
        """Add symbols to monitor."""
        for s in symbols:
            self._watchlist.add(s.upper())
        logger.info(f"Watchlist updated: {len(self._watchlist)} symbols")
    
    def remove_from_watchlist(self, symbol: str):
        """Remove symbol from watchlist."""
        self._watchlist.discard(symbol.upper())
    
    def clear_watchlist(self):
        """Clear watchlist."""
        self._watchlist.clear()
    
    # ==================== NEWS FETCHING ====================
    
    def check_news(self, symbol: str) -> List[NewsItem]:
        """
        Check for recent news on a symbol.
        Returns news from last hour.
        """
        symbol = symbol.upper()
        news_items = []
        
        # Rate limit: don't check same symbol more than once per minute
        last = self._last_check.get(symbol)
        if last and (datetime.now() - last).seconds < 60:
            return self._news_cache.get(symbol, [])
        
        self._last_check[symbol] = datetime.now()
        
        # Get from yfinance
        yf_news = self._get_yfinance_news(symbol)
        news_items.extend(yf_news)
        
        # Get from FMP if configured
        if config.FMP_API_KEY:
            fmp_news = self._get_fmp_news(symbol)
            news_items.extend(fmp_news)
        
        # Filter to recent only (last 2 hours)
        cutoff = datetime.now() - timedelta(hours=2)
        recent = [n for n in news_items if n.timestamp > cutoff]
        
        # Deduplicate
        unique = []
        seen_headlines = set()
        for n in recent:
            headline_key = n.headline[:50].lower()
            if headline_key not in seen_headlines:
                seen_headlines.add(headline_key)
                unique.append(n)
        
        # Cache
        self._news_cache[symbol] = unique
        
        return unique
    
    def _get_yfinance_news(self, symbol: str) -> List[NewsItem]:
        """Get news from yfinance."""
        news_items = []
        
        try:
            raw_news = market_data.get_news(symbol, max_items=10)
            
            for item in raw_news:
                headline = item.get("title", "")
                
                # Skip if already seen
                news_id = f"{symbol}:{headline[:30]}"
                if news_id in self._seen_news:
                    continue
                
                # Parse timestamp
                pub_time = item.get("providerPublishTime", 0)
                if pub_time:
                    timestamp = datetime.fromtimestamp(pub_time)
                else:
                    timestamp = datetime.now()
                
                # Classify impact
                impact = self._classify_impact(headline)
                keywords = self._extract_keywords(headline)
                
                news_items.append(NewsItem(
                    symbol=symbol,
                    headline=headline,
                    source=item.get("publisher", "Unknown"),
                    timestamp=timestamp,
                    url=item.get("link", ""),
                    impact=impact,
                    keywords=keywords
                ))
                
                self._seen_news.add(news_id)
                
        except Exception as e:
            logger.debug(f"yfinance news error for {symbol}: {e}")
        
        return news_items
    
    def _get_fmp_news(self, symbol: str) -> List[NewsItem]:
        """Get news from FMP API."""
        news_items = []
        
        try:
            url = f"https://financialmodelingprep.com/api/v3/stock_news"
            params = {
                "tickers": symbol,
                "limit": 10,
                "apikey": config.FMP_API_KEY
            }
            
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            
            for item in data:
                headline = item.get("title", "")
                
                # Skip if seen
                news_id = f"{symbol}:{headline[:30]}"
                if news_id in self._seen_news:
                    continue
                
                # Parse timestamp
                pub_date = item.get("publishedDate", "")
                try:
                    timestamp = datetime.fromisoformat(pub_date.replace("Z", ""))
                except:
                    timestamp = datetime.now()
                
                impact = self._classify_impact(headline)
                keywords = self._extract_keywords(headline)
                
                news_items.append(NewsItem(
                    symbol=symbol,
                    headline=headline,
                    source=item.get("site", "FMP"),
                    timestamp=timestamp,
                    url=item.get("url", ""),
                    impact=impact,
                    keywords=keywords
                ))
                
                self._seen_news.add(news_id)
                
        except Exception as e:
            logger.debug(f"FMP news error for {symbol}: {e}")
        
        return news_items
    
    # ==================== NEWS CLASSIFICATION ====================
    
    def _classify_impact(self, headline: str) -> NewsImpact:
        """Classify news impact as positive/negative/neutral."""
        headline_lower = headline.lower()
        
        pos_count = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in headline_lower)
        neg_count = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in headline_lower)
        
        if pos_count > neg_count and pos_count >= 1:
            return NewsImpact.POSITIVE
        elif neg_count > pos_count and neg_count >= 1:
            return NewsImpact.NEGATIVE
        elif pos_count == neg_count and pos_count > 0:
            return NewsImpact.NEUTRAL
        else:
            return NewsImpact.UNKNOWN
    
    def _extract_keywords(self, headline: str) -> List[str]:
        """Extract material keywords from headline."""
        headline_lower = headline.lower()
        found = []
        
        for kw in self.MATERIAL_KEYWORDS:
            if kw in headline_lower:
                found.append(kw)
        
        return found
    
    def is_material_news(self, news: NewsItem) -> bool:
        """Check if news is material (could affect position)."""
        # Has material keywords
        if news.keywords:
            return True
        
        # Strong sentiment
        if news.impact in [NewsImpact.POSITIVE, NewsImpact.NEGATIVE]:
            return True
        
        return False
    
    # ==================== CONTINUOUS MONITORING ====================
    
    def check_watchlist(self) -> List[NewsItem]:
        """Check all symbols in watchlist for news."""
        all_news = []
        
        for symbol in list(self._watchlist):
            news = self.check_news(symbol)
            
            for item in news:
                if self.is_material_news(item):
                    all_news.append(item)
                    self._send_news_alert(item)
        
        return all_news
    
    def _send_news_alert(self, news: NewsItem):
        """Send Telegram alert for material news."""
        impact_emoji = {
            NewsImpact.POSITIVE: "🟢",
            NewsImpact.NEGATIVE: "🔴",
            NewsImpact.NEUTRAL: "🟡",
            NewsImpact.UNKNOWN: "⚪"
        }
        
        emoji = impact_emoji.get(news.impact, "⚪")
        
        msg = (
            f"{emoji} <b>NEWS: {news.symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{news.headline[:200]}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Source: {news.source}\n"
            f"Impact: {news.impact.value}\n"
            f"⏰ {news.timestamp.strftime('%H:%M')}"
        )
        
        self.telegram.send(msg)
    
    def start_monitoring(self):
        """Start background news monitoring."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("News monitoring started")
    
    def stop_monitoring(self):
        """Stop background monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("News monitoring stopped")
    
    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._running:
            try:
                # Only check during market hours
                if self._is_market_hours():
                    self.check_watchlist()
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"News monitor error: {e}")
                time.sleep(60)
    
    def _is_market_hours(self) -> bool:
        """Check if market is open."""
        import pytz
        ET = pytz.timezone('US/Eastern')
        now = datetime.now(ET)
        
        if now.weekday() >= 5:  # Weekend
            return False
        
        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)
        
        return market_open <= now <= market_close
    
    # ==================== POSITION IMPACT CHECK ====================
    
    def check_position_news(self, symbol: str, position_data: Dict) -> Optional[Dict]:
        """
        Check if recent news should affect a position.
        
        Returns action recommendation if news is significant.
        """
        news = self.check_news(symbol)
        
        if not news:
            return None
        
        # Check for strongly negative news
        for item in news:
            if item.impact == NewsImpact.NEGATIVE and self.is_material_news(item):
                # Check if news is very recent (last 30 min)
                age = (datetime.now() - item.timestamp).seconds / 60
                
                if age < 30:
                    return {
                        "action": "REVIEW",
                        "reason": f"Negative news: {item.headline[:100]}",
                        "news": item,
                        "urgency": "high" if age < 10 else "medium"
                    }
        
        return None


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    monitor = NewsMonitor()
    
    print("=" * 60)
    print("NEWS MONITOR TEST")
    print("=" * 60)
    
    # Test with some stocks
    test_symbols = ["AAPL", "TSLA", "NVDA", "META", "GOOGL"]
    
    for symbol in test_symbols:
        print(f"\n{symbol}:")
        news = monitor.check_news(symbol)
        
        if news:
            for item in news[:3]:
                impact_emoji = "🟢" if item.impact == NewsImpact.POSITIVE else "🔴" if item.impact == NewsImpact.NEGATIVE else "⚪"
                print(f"  {impact_emoji} {item.headline[:60]}...")
                print(f"     Source: {item.source}, Keywords: {item.keywords}")
        else:
            print("  No recent news")
    
    print("\n✓ News monitor test complete")
