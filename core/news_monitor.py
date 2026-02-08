"""
core/news_monitor.py - Real-Time News Monitoring

Monitors news during market hours for:
1. Earnings releases
2. Material news that could affect positions
3. Market-moving events

Sources:
- Yahoo Finance news (via REST API)
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
    sentiment_score: float = 0.0  # -1.0 to 1.0
    summary: str = ""  # Interpreted meaning


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
    
    def check_news(self, symbol: str, max_items: int = 20, store: bool = True) -> List[NewsItem]:
        """
        Check for recent news on a symbol.
        Fetches up to max_items, classifies, scores, and stores them.
        """
        symbol = symbol.upper()
        news_items = []
        
        # Rate limit: don't check same symbol more than once per minute
        last = self._last_check.get(symbol)
        if last and (datetime.now() - last).seconds < 60:
            return self._news_cache.get(symbol, [])
        
        self._last_check[symbol] = datetime.now()
        
        # Get from Yahoo Finance API (primary, no auth needed)
        yf_news = self._get_yfinance_news(symbol, max_items=max_items)
        news_items.extend(yf_news)
        
        # Get from FMP if configured (additional coverage)
        if config.FMP_API_KEY:
            fmp_news = self._get_fmp_news(symbol, max_items=max_items)
            news_items.extend(fmp_news)
        
        # Filter to recent only (last 24 hours for full reports, 2 hours for alerts)
        cutoff = datetime.now() - timedelta(hours=24)
        recent = [n for n in news_items if n.timestamp > cutoff]
        
        # Deduplicate by headline similarity
        unique = []
        seen_headlines = set()
        for n in recent:
            headline_key = n.headline[:50].lower()
            if headline_key not in seen_headlines:
                seen_headlines.add(headline_key)
                unique.append(n)
        
        # Sort by timestamp (newest first)
        unique.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Cache
        self._news_cache[symbol] = unique
        
        # Store to disk/MongoDB
        if store and unique:
            self._store_news(symbol, unique)
        
        return unique
    
    def _get_yfinance_news(self, symbol: str, max_items: int = 20) -> List[NewsItem]:
        """Get news from Yahoo Finance API."""
        news_items = []
        
        try:
            raw_news = market_data.get_news(symbol, max_items=max_items)
            
            for item in raw_news:
                headline = item.get("title", "")
                if not headline:
                    continue
                
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
                
                # Classify impact and score
                impact = self._classify_impact(headline)
                keywords = self._extract_keywords(headline)
                score = self._sentiment_score(headline)
                summary = self._interpret_headline(headline, symbol)
                
                news_items.append(NewsItem(
                    symbol=symbol,
                    headline=headline,
                    source=item.get("publisher", "Unknown"),
                    timestamp=timestamp,
                    url=item.get("link", ""),
                    impact=impact,
                    keywords=keywords,
                    sentiment_score=score,
                    summary=summary,
                ))
                
                self._seen_news.add(news_id)
                
        except Exception as e:
            logger.debug(f"Yahoo news error for {symbol}: {e}")
        
        return news_items
    
    def _get_fmp_news(self, symbol: str, max_items: int = 20) -> List[NewsItem]:
        """Get news from FMP API. Tries stable endpoint, then v3."""
        news_items = []
        
        endpoints = [
            f"https://financialmodelingprep.com/stable/news/stock-news",
            f"https://financialmodelingprep.com/api/v3/stock_news",
        ]
        
        for url in endpoints:
            try:
                params = {
                    "tickers": symbol,
                    "limit": max_items,
                    "apikey": config.FMP_API_KEY,
                }
                
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                if not isinstance(data, list):
                    continue
                
                for item in data:
                    headline = item.get("title", "")
                    if not headline:
                        continue
                    
                    news_id = f"{symbol}:{headline[:30]}"
                    if news_id in self._seen_news:
                        continue
                    
                    # Parse timestamp
                    pub_date = item.get("publishedDate", "")
                    try:
                        timestamp = datetime.fromisoformat(pub_date.replace("Z", "").replace(" ", "T"))
                    except Exception:
                        timestamp = datetime.now()
                    
                    impact = self._classify_impact(headline)
                    keywords = self._extract_keywords(headline)
                    score = self._sentiment_score(headline)
                    summary = self._interpret_headline(headline, symbol)
                    
                    news_items.append(NewsItem(
                        symbol=symbol,
                        headline=headline,
                        source=item.get("site", "FMP"),
                        timestamp=timestamp,
                        url=item.get("url", ""),
                        impact=impact,
                        keywords=keywords,
                        sentiment_score=score,
                        summary=summary,
                    ))
                    
                    self._seen_news.add(news_id)
                
                if news_items:
                    break  # Got data from this endpoint
                    
            except Exception as e:
                logger.debug(f"FMP news error for {symbol}: {e}")
        
        return news_items
    
    # ==================== NEWS CLASSIFICATION & SCORING ====================
    
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
    
    def _sentiment_score(self, headline: str) -> float:
        """
        Compute numeric sentiment score from -1.0 (very negative) to 1.0 (very positive).
        Uses weighted keyword matching with intensity modifiers.
        """
        headline_lower = headline.lower()
        
        # Weighted positive terms
        strong_pos = ["beats", "exceeds", "soars", "surges", "record", "breakthrough", 
                      "approval", "upgraded", "skyrockets", "blowout"]
        mild_pos = ["raises", "wins", "awarded", "rallies", "partnership",
                    "innovation", "outperform", "dividend", "buyback", "growth"]
        
        # Weighted negative terms  
        strong_neg = ["crashes", "plunges", "fraud", "bankruptcy", "tumbles",
                      "rejected", "probe", "investigation", "recall", "warning"]
        mild_neg = ["misses", "disappoints", "lowers", "downgraded", "lawsuit",
                    "layoffs", "cuts", "loss", "decline", "weak", "underperform"]
        
        score = 0.0
        for kw in strong_pos:
            if kw in headline_lower:
                score += 0.4
        for kw in mild_pos:
            if kw in headline_lower:
                score += 0.2
        for kw in strong_neg:
            if kw in headline_lower:
                score -= 0.4
        for kw in mild_neg:
            if kw in headline_lower:
                score -= 0.2
        
        # Clamp to [-1.0, 1.0]
        return max(-1.0, min(1.0, score))
    
    def _interpret_headline(self, headline: str, symbol: str) -> str:
        """
        Generate a brief interpretation of what the headline means for trading.
        Rule-based interpretation (no LLM needed).
        """
        hl = headline.lower()
        
        # Earnings related
        if any(w in hl for w in ["beats", "exceeds", "tops estimates"]):
            return f"{symbol} reported better-than-expected results. Bullish signal."
        if any(w in hl for w in ["misses", "disappoints", "falls short"]):
            return f"{symbol} missed expectations. Watch for post-earnings drift lower."
        if any(w in hl for w in ["raises guidance", "raises outlook"]):
            return f"{symbol} raised forward guidance. Strong bullish catalyst."
        if any(w in hl for w in ["lowers guidance", "cuts outlook", "warns"]):
            return f"{symbol} lowered guidance. Bearish — expect selling pressure."
        
        # Analyst actions
        if "upgraded" in hl or "upgrade" in hl:
            return f"Analyst upgrade for {symbol}. Positive catalyst for price."
        if "downgraded" in hl or "downgrade" in hl:
            return f"Analyst downgrade for {symbol}. May trigger selling."
        if "price target" in hl and ("raises" in hl or "increased" in hl):
            return f"Raised price target for {symbol}. Bullish signal."
        
        # Corporate actions
        if any(w in hl for w in ["acquisition", "acquires", "merger", "buyout"]):
            return f"M&A activity involving {symbol}. High volatility expected."
        if any(w in hl for w in ["dividend", "buyback", "repurchase"]):
            return f"Shareholder-friendly action by {symbol}. Generally positive."
        if any(w in hl for w in ["layoffs", "restructuring", "cost cutting"]):
            return f"{symbol} restructuring. Short-term negative, may be long-term positive."
        
        # Regulatory
        if any(w in hl for w in ["fda", "approval", "approved"]):
            return f"Regulatory approval for {symbol}. Major positive catalyst."
        if any(w in hl for w in ["sec", "investigation", "probe", "lawsuit"]):
            return f"Legal/regulatory risk for {symbol}. Monitor closely."
        
        # Market sentiment
        if any(w in hl for w in ["record", "all-time high", "new high"]):
            return f"{symbol} hitting new highs. Momentum continues."
        if any(w in hl for w in ["crash", "plunge", "sell-off"]):
            return f"Sharp decline in {symbol}. Assess if dip-buy or avoid."
        
        return f"General news for {symbol}. Monitor for follow-up developments."
    
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
        if news.keywords:
            return True
        if news.impact in [NewsImpact.POSITIVE, NewsImpact.NEGATIVE]:
            return True
        if abs(news.sentiment_score) >= 0.4:
            return True
        return False
    
    # ==================== NEWS STORAGE ====================
    
    def _store_news(self, symbol: str, news_items: List[NewsItem]):
        """Store news to JSON and MongoDB (if available)."""
        import json
        from core.utils import NumpySafeEncoder
        
        records = []
        for n in news_items:
            records.append({
                "symbol": n.symbol,
                "headline": n.headline,
                "source": n.source,
                "timestamp": n.timestamp.isoformat(),
                "url": n.url,
                "impact": n.impact.value,
                "sentiment_score": n.sentiment_score,
                "keywords": n.keywords,
                "summary": n.summary,
                "stored_at": datetime.now().isoformat(),
            })
        
        # Save to JSON
        try:
            filepath = config.DATA_DIR / f"news_{symbol}_{datetime.now().strftime('%Y%m%d')}.json"
            
            # Append to existing file if present
            existing = []
            if filepath.exists():
                with open(filepath) as f:
                    existing = json.load(f)
            
            # Deduplicate by headline
            existing_headlines = {r["headline"][:50] for r in existing}
            new_records = [r for r in records if r["headline"][:50] not in existing_headlines]
            
            if new_records:
                all_records = existing + new_records
                with open(filepath, 'w') as f:
                    json.dump(all_records, f, indent=2, cls=NumpySafeEncoder, default=str)
                logger.debug(f"Stored {len(new_records)} news items for {symbol}")
        except Exception as e:
            logger.debug(f"News storage error: {e}")
        
        # Store to MongoDB if available
        try:
            from core.storage import Storage
            storage = Storage()
            if storage._has_mongo():
                for r in records:
                    storage.db["news"].update_one(
                        {"symbol": r["symbol"], "headline": r["headline"][:100]},
                        {"$set": r},
                        upsert=True
                    )
        except Exception:
            pass
    
    # ==================== NEWS REPORTS ====================
    
    def get_full_news_report(self, symbol: str) -> Dict:
        """
        Get comprehensive news report for a symbol.
        Returns: headlines, aggregate sentiment, interpretation, and trading signal.
        """
        news = self.check_news(symbol, max_items=20, store=True)
        
        if not news:
            return {
                "symbol": symbol,
                "count": 0,
                "sentiment": 0.0,
                "signal": "NO_DATA",
                "headlines": [],
                "interpretation": f"No recent news found for {symbol}.",
            }
        
        # Aggregate sentiment
        scores = [n.sentiment_score for n in news]
        avg_sentiment = sum(scores) / len(scores) if scores else 0
        
        pos_count = sum(1 for n in news if n.impact == NewsImpact.POSITIVE)
        neg_count = sum(1 for n in news if n.impact == NewsImpact.NEGATIVE)
        
        # Determine signal
        if avg_sentiment > 0.3 and pos_count > neg_count * 2:
            signal = "BULLISH"
        elif avg_sentiment < -0.3 and neg_count > pos_count * 2:
            signal = "BEARISH"
        elif abs(avg_sentiment) < 0.1:
            signal = "NEUTRAL"
        else:
            signal = "MIXED"
        
        # Build interpretation
        lines = []
        lines.append(f"📊 {len(news)} headlines analyzed for {symbol}")
        lines.append(f"Sentiment: {avg_sentiment:+.2f} ({signal})")
        lines.append(f"Positive: {pos_count} | Negative: {neg_count} | Neutral: {len(news) - pos_count - neg_count}")
        
        # Top 3 most impactful
        material = [n for n in news if self.is_material_news(n)]
        if material:
            lines.append("\nKey headlines:")
            for n in material[:3]:
                lines.append(f"• {n.summary}")
        
        return {
            "symbol": symbol,
            "count": len(news),
            "sentiment": round(avg_sentiment, 3),
            "signal": signal,
            "positive": pos_count,
            "negative": neg_count,
            "headlines": [
                {
                    "title": n.headline,
                    "source": n.source,
                    "score": n.sentiment_score,
                    "impact": n.impact.value,
                    "summary": n.summary,
                    "time": n.timestamp.strftime("%Y-%m-%d %H:%M"),
                }
                for n in news
            ],
            "interpretation": "\n".join(lines),
        }
    
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
