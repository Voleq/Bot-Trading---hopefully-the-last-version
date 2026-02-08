"""
analysis/weekend_pipeline.py - Weekend Analysis Pipeline

Runs on Saturday/Sunday ONLY.

Steps:
1. Refresh weekly universe from Trading212
2. Get earnings calendar from FMP
3. Cross-check against universe
4. Run historical analysis on each candidate
5. Compute explainable scores
6. Store results and notify via Telegram

After Sunday night, this data is FROZEN for the week.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import requests

import pandas as pd
import numpy as np

import config
from core.t212_client import T212Client, clean_symbol
from core.storage import Storage, get_week_id, get_week_start
from core.telegram import Telegram
from core import market_data

logger = logging.getLogger(__name__)


class WeekendAnalysisPipeline:
    """
    Weekend analysis pipeline.
    
    This is the ONLY time new data is computed.
    During the week, we use precomputed results only.
    """
    
    def __init__(self):
        self.t212 = T212Client(paper=config.PAPER_MODE)
        self.storage = Storage()
        self.telegram = Telegram()
    
    # ==================== STEP 1: UNIVERSE REFRESH ====================
    
    def refresh_universe(self) -> List[Dict]:
        """
        Step 1: Fetch ALL tradeable instruments from Trading212.
        
        This becomes the SINGLE SOURCE OF TRUTH for the week.
        """
        logger.info("=" * 60)
        logger.info("STEP 1: Refreshing Weekly Universe")
        logger.info("=" * 60)
        
        instruments = self.t212.get_all_instruments(refresh=True)
        
        # Convert to storable format
        universe = []
        for inst in instruments:
            universe.append({
                "ticker": inst.ticker,
                "symbol": inst.symbol,
                "name": inst.name,
                "type": inst.type,
                "currency": inst.currency
            })
        
        # Save to storage
        week_id = get_week_id()
        self.storage.save_universe(universe, week_id)
        
        # Notify
        week_start = get_week_start().strftime("%d %b")
        self.telegram.universe_update(len(universe), week_start)
        
        logger.info(f"Universe refreshed: {len(universe)} instruments")
        return universe
    
    # ==================== STEP 2: EARNINGS CANDIDATES ====================
    
    def get_earnings_candidates(self) -> List[Dict]:
        """
        Step 2: Get earnings for next week.
        
        Sources (tried in order):
        1. FMP /stable/earnings-calendar (new endpoint)
        2. FMP /api/v3/earning_calendar (legacy endpoint)
        3. Yahoo Finance earnings dates (fallback)
        
        Cross-check against Trading212 universe.
        Only keep stocks that are tradeable.
        """
        logger.info("=" * 60)
        logger.info("STEP 2: Getting Earnings Candidates")
        logger.info("=" * 60)
        
        # Get next week's dates
        today = datetime.now()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        
        next_monday = today + timedelta(days=days_until_monday)
        next_friday = next_monday + timedelta(days=4)
        
        from_date = next_monday.strftime("%Y-%m-%d")
        to_date = next_friday.strftime("%Y-%m-%d")
        
        logger.info(f"Fetching earnings for {from_date} to {to_date}")
        
        # Try FMP first
        earnings_data = []
        if config.FMP_API_KEY:
            earnings_data = self._fetch_fmp_earnings(from_date, to_date)
        
        # Fallback to Yahoo Finance for top universe symbols
        if not earnings_data:
            logger.info("FMP unavailable, falling back to Yahoo Finance earnings")
            earnings_data = self._fetch_yahoo_earnings(from_date, to_date)
        
        if not earnings_data:
            logger.warning("No earnings data from any source")
            return []
        
        logger.info(f"Raw earnings data: {len(earnings_data)} entries")
        
        # Get universe symbols
        universe_symbols = set(s.upper() for s in self.storage.get_universe_symbols())
        
        if not universe_symbols:
            logger.error("No universe loaded, run refresh_universe first")
            return []
        
        # Filter to tradeable only
        candidates = []
        skipped = {"invalid": 0, "not_tradeable": 0}
        
        for item in earnings_data:
            raw_symbol = item.get("symbol", "")
            symbol = clean_symbol(raw_symbol)
            
            if not symbol:
                skipped["invalid"] += 1
                continue
            
            if symbol.upper() not in universe_symbols:
                skipped["not_tradeable"] += 1
                continue
            
            candidates.append({
                "symbol": symbol,
                "date": item.get("date"),
                "time": item.get("time", "unknown"),
                "eps_estimate": item.get("epsEstimated"),
                "revenue_estimate": item.get("revenueEstimated"),
                "source": item.get("source", "fmp"),
            })
        
        logger.info(f"Filtered to {len(candidates)} tradeable candidates")
        logger.info(f"Skipped: {skipped['invalid']} invalid, {skipped['not_tradeable']} not on T212")
        
        # Save
        week_id = get_week_id()
        self.storage.save_earnings_candidates(candidates, week_id)
        
        # Notify
        week_start = get_week_start().strftime("%d %b")
        self.telegram.earnings_candidates(candidates, week_start)
        
        return candidates
    
    def _fetch_fmp_earnings(self, from_date: str, to_date: str) -> List[Dict]:
        """Fetch earnings from FMP. Tries stable endpoint, then v3 legacy."""
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # Try 1: New stable endpoint
        endpoints = [
            ("https://financialmodelingprep.com/stable/earnings-calendar", {
                "from": from_date,
                "to": to_date,
                "apikey": config.FMP_API_KEY,
            }),
            # Try 2: Legacy v3 endpoint
            ("https://financialmodelingprep.com/api/v3/earning_calendar", {
                "from": from_date,
                "to": to_date,
                "apikey": config.FMP_API_KEY,
            }),
        ]
        
        for url, params in endpoints:
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        logger.info(f"FMP returned {len(data)} earnings from {url.split('/')[-1]}")
                        return data
                    elif isinstance(data, dict) and "Error Message" in data:
                        logger.warning(f"FMP error: {data['Error Message']}")
                        continue
                elif resp.status_code == 403:
                    logger.warning(f"FMP 403 (may need paid plan) for {url.split('/')[-1]}")
                    continue
                else:
                    logger.warning(f"FMP {resp.status_code} for {url.split('/')[-1]}")
            except Exception as e:
                logger.debug(f"FMP request failed: {e}")
        
        logger.warning("All FMP endpoints failed")
        return []
    
    def _fetch_yahoo_earnings(self, from_date: str, to_date: str) -> List[Dict]:
        """
        Fallback: fetch ALL earnings for a date range from Yahoo Finance.
        
        Uses Yahoo's bulk earnings calendar endpoint which returns
        all companies reporting on each day — no per-symbol limit.
        """
        import time as _time
        
        try:
            from datetime import datetime as dt
            target_start = dt.strptime(from_date, "%Y-%m-%d")
            target_end = dt.strptime(to_date, "%Y-%m-%d")
        except Exception:
            return []
        
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        })
        
        all_earnings = []
        
        # Method 1: Yahoo Finance screener API (bulk earnings by date)
        # This endpoint returns up to 250 results per request, paginated
        current_date = target_start
        while current_date <= target_end:
            date_str = current_date.strftime("%Y-%m-%d")
            day_earnings = self._yahoo_earnings_for_date(session, date_str)
            
            if day_earnings:
                all_earnings.extend(day_earnings)
                logger.info(f"Yahoo earnings calendar: {len(day_earnings)} companies for {date_str}")
            else:
                logger.debug(f"Yahoo earnings calendar: 0 companies for {date_str}")
            
            current_date += timedelta(days=1)
            _time.sleep(0.5)  # Be nice to Yahoo
        
        # Method 2 fallback: if screener returned nothing, try the finance/calendar endpoint
        if not all_earnings:
            logger.info("Yahoo screener returned nothing, trying calendar endpoint...")
            all_earnings = self._yahoo_calendar_fallback(session, from_date, to_date)
        
        logger.info(f"Yahoo Finance found {len(all_earnings)} total earnings for {from_date} to {to_date}")
        return all_earnings
    
    def _yahoo_earnings_for_date(self, session, date_str: str) -> List[Dict]:
        """Fetch earnings for a single date using Yahoo's screener/calendar API."""
        results = []
        offset = 0
        page_size = 250
        
        while True:
            try:
                # Yahoo Finance earnings calendar API
                url = "https://finance.yahoo.com/calendar/earnings"
                resp = session.get(url, params={
                    "day": date_str,
                    "offset": offset,
                    "size": page_size,
                }, timeout=15)
                
                if resp.status_code != 200:
                    break
                
                # Try to extract JSON data from the page
                text = resp.text
                
                # Look for the embedded JSON data in the page
                import json
                import re
                
                # Pattern 1: Look for stores data
                match = re.search(r'"rows"\s*:\s*(\[.*?\])\s*,\s*"total"', text, re.DOTALL)
                if match:
                    try:
                        rows = json.loads(match.group(1))
                        for row in rows:
                            ticker = row.get("ticker", "")
                            if not ticker:
                                # Try alternative field names
                                ticker = row.get("symbol", "")
                            
                            if ticker:
                                results.append({
                                    "symbol": ticker,
                                    "date": date_str,
                                    "time": row.get("startdatetimetype", "unknown"),
                                    "epsEstimated": row.get("epsestimate"),
                                    "revenueEstimated": None,
                                    "source": "yahoo_calendar",
                                })
                        
                        # Check if there are more pages
                        total_match = re.search(r'"total"\s*:\s*(\d+)', text)
                        if total_match:
                            total = int(total_match.group(1))
                            if offset + page_size >= total:
                                break
                            offset += page_size
                            continue
                    except json.JSONDecodeError:
                        pass
                
                # Pattern 2: Try to find earnings data in script tags
                pattern = r'<script[^>]*>.*?\"earningsCalendarData\".*?\"rows\":\s*(\[.*?\])'
                match2 = re.search(pattern, text, re.DOTALL)
                if match2:
                    try:
                        rows = json.loads(match2.group(1))
                        for row in rows:
                            ticker = row.get("ticker") or row.get("symbol", "")
                            if ticker:
                                results.append({
                                    "symbol": ticker,
                                    "date": date_str,
                                    "time": row.get("startdatetimetype", "unknown"),
                                    "epsEstimated": row.get("epsestimate"),
                                    "revenueEstimated": None,
                                    "source": "yahoo_calendar",
                                })
                    except json.JSONDecodeError:
                        pass
                
                break  # No more pagination data found
                
            except Exception as e:
                logger.debug(f"Yahoo calendar fetch error for {date_str}: {e}")
                break
        
        return results
    
    def _yahoo_calendar_fallback(self, session, from_date: str, to_date: str) -> List[Dict]:
        """
        Last resort: use Yahoo's v1 finance screener API to get earnings.
        This endpoint accepts date range and returns bulk results.
        """
        import json
        results = []
        
        try:
            # Try Yahoo screener with earnings filter
            url = "https://query2.finance.yahoo.com/v1/finance/screener"
            
            payload = {
                "size": 250,
                "offset": 0,
                "sortField": "intradaymarketcap",
                "sortType": "DESC",
                "quoteType": "EQUITY",
                "query": {
                    "operator": "AND",
                    "operands": [
                        {
                            "operator": "eq",
                            "operands": ["region", "us"]
                        },
                        {
                            "operator": "BTWN",
                            "operands": [
                                "earnings_date",
                                from_date,
                                to_date,
                            ]
                        }
                    ]
                },
            }
            
            resp = session.post(url, json=payload, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
                
                for q in quotes:
                    symbol = q.get("symbol", "")
                    if symbol:
                        # Extract earnings date from the quote
                        earn_ts = q.get("earningsTimestamp")
                        if earn_ts:
                            from datetime import datetime as dt
                            earn_date = dt.fromtimestamp(earn_ts).strftime("%Y-%m-%d")
                        else:
                            earn_date = from_date
                        
                        results.append({
                            "symbol": symbol,
                            "date": earn_date,
                            "time": q.get("earningsTimestampStart", "unknown"),
                            "epsEstimated": q.get("epsForward") or q.get("epsTrailingTwelveMonths"),
                            "revenueEstimated": q.get("revenueEstimate"),
                            "source": "yahoo_screener",
                        })
                
                logger.info(f"Yahoo screener returned {len(results)} earnings results")
            else:
                logger.debug(f"Yahoo screener returned {resp.status_code}")
                
        except Exception as e:
            logger.debug(f"Yahoo screener fallback error: {e}")
        
        return results

    # ==================== STEP 3: HISTORICAL ANALYSIS ====================
    
    def analyze_candidates(self, candidates: List[Dict] = None) -> List[Dict]:
        """
        Step 3: Run historical analysis on each candidate.
        
        For each stock:
        1. Find historical quarters with >5% earnings gap
        2. Simulate Day 1-10 price action
        3. Identify patterns (gap fade vs continuation)
        4. Compute explainable score vector
        5. Calculate final 1-5 score
        """
        logger.info("=" * 60)
        logger.info("STEP 3: Analyzing Candidates")
        logger.info("=" * 60)
        
        if candidates is None:
            candidates = self.storage.get_earnings_candidates()
        
        if not candidates:
            logger.warning("No candidates to analyze")
            return []
        
        results = []
        
        for i, candidate in enumerate(candidates):
            symbol = candidate.get("symbol")
            logger.info(f"[{i+1}/{len(candidates)}] Analyzing {symbol}...")
            
            try:
                analysis = self._analyze_single(symbol, candidate)
                if analysis:
                    results.append(analysis)
                    
            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")
        
        # Save results
        week_id = get_week_id()
        self.storage.save_analysis_results(results, week_id)
        
        # Notify
        week_start = get_week_start().strftime("%d %b")
        self.telegram.analysis_results(results, week_start)
        
        logger.info(f"Analysis complete: {len(results)} results")
        return results
    
    def _analyze_single(self, symbol: str, candidate: Dict) -> Optional[Dict]:
        """Analyze a single stock."""
        
        # Validate symbol first
        symbol = clean_symbol(symbol)
        if not symbol:
            logger.debug(f"Invalid symbol format: {candidate.get('symbol')}")
            return None
        
        # Get historical data (2 years) using safe fetcher
        hist = market_data.get_history(symbol, period="2y", validate=True)
        
        if hist is None or len(hist) < 200:
            logger.debug(f"{symbol}: Insufficient history or invalid symbol")
            return None
        
        # Get earnings history
        earnings = market_data.get_earnings_dates(symbol)
        
        if earnings is None or earnings.empty:
            logger.debug(f"{symbol}: No earnings history")
            # Continue anyway - we can still analyze price patterns
        
        # Analyze historical gaps
        gap_analysis = self._analyze_earnings_gaps(symbol, hist, earnings)
        
        # Get analyst estimates using safe fetcher
        info = market_data.get_info(symbol)
        estimates = self._get_analyst_estimates_from_info(info)
        
        # Compute score components
        scores = self._compute_score_components(symbol, hist, gap_analysis, estimates)
        
        # Calculate final score (1-5)
        final_score = self._calculate_final_score(scores)
        
        return {
            "symbol": symbol,
            "date": candidate.get("date"),
            "time": candidate.get("time"),
            "eps_estimate": candidate.get("eps_estimate"),
            
            # Score components (explainable)
            "gap_behavior": gap_analysis.get("behavior", "unknown"),
            "gap_behavior_score": scores.get("gap_behavior", 0),
            "trend_consistency_score": scores.get("trend_consistency", 0),
            "analyst_sensitivity_score": scores.get("analyst_sensitivity", 0),
            "volatility_alignment_score": scores.get("volatility_alignment", 0),
            "sentiment_bias_score": scores.get("sentiment_bias", 0),
            
            # Historical stats
            "avg_gap_pct": gap_analysis.get("avg_gap_pct", 0),
            "fade_rate": gap_analysis.get("fade_rate", 0),
            "continuation_rate": gap_analysis.get("continuation_rate", 0),
            "avg_day10_return": gap_analysis.get("avg_day10_return", 0),
            
            # Final score
            "final_score": final_score,
            
            # Metadata
            "analyzed_at": datetime.now().isoformat(),
            "quarters_analyzed": gap_analysis.get("quarters_analyzed", 0),
        }
    
    def _analyze_earnings_gaps(self, symbol: str, hist: pd.DataFrame, earnings) -> Dict:
        """
        Analyze historical earnings gaps.
        
        Find quarters with >5% gap and track Day 1-10 behavior.
        """
        result = {
            "behavior": "unknown",
            "avg_gap_pct": 0,
            "fade_rate": 0,
            "continuation_rate": 0,
            "avg_day10_return": 0,
            "quarters_analyzed": 0
        }
        
        if earnings is None or earnings.empty:
            return result
        
        gaps = []
        fades = 0
        continuations = 0
        day10_returns = []
        
        # Look at each earnings date
        for earn_date in earnings.index[:12]:  # Last 12 quarters max
            try:
                earn_date = pd.Timestamp(earn_date).tz_localize(None)
                
                # Find the date in our history
                mask = hist.index >= earn_date
                if not mask.any():
                    continue
                
                post_idx = hist.index[mask][0]
                post_loc = hist.index.get_loc(post_idx)
                
                if post_loc < 1 or post_loc + 10 >= len(hist):
                    continue
                
                # Calculate gap
                pre_close = hist['Close'].iloc[post_loc - 1]
                post_open = hist['Open'].iloc[post_loc]
                gap_pct = ((post_open - pre_close) / pre_close) * 100
                
                # Only analyze significant gaps
                if abs(gap_pct) < config.MIN_EARNINGS_GAP_PCT:
                    continue
                
                gaps.append(gap_pct)
                
                # Track Day 1-10 behavior
                day1_close = hist['Close'].iloc[post_loc]
                day10_close = hist['Close'].iloc[post_loc + 10]
                
                day10_return = ((day10_close - post_open) / post_open) * 100
                day10_returns.append(day10_return)
                
                # Classify: fade or continuation
                if gap_pct > 0:
                    # Gap up
                    if day10_close < post_open:
                        fades += 1
                    else:
                        continuations += 1
                else:
                    # Gap down
                    if day10_close > post_open:
                        fades += 1  # Faded the gap down (bounced)
                    else:
                        continuations += 1
                        
            except Exception:
                continue
        
        if gaps:
            total = fades + continuations
            result["avg_gap_pct"] = np.mean(gaps)
            result["fade_rate"] = fades / total if total > 0 else 0
            result["continuation_rate"] = continuations / total if total > 0 else 0
            result["avg_day10_return"] = np.mean(day10_returns) if day10_returns else 0
            result["quarters_analyzed"] = len(gaps)
            
            # Determine dominant behavior
            if result["fade_rate"] > 0.6:
                result["behavior"] = "fade"
            elif result["continuation_rate"] > 0.6:
                result["behavior"] = "continuation"
            else:
                result["behavior"] = "mixed"
        
        return result
    
    def _get_analyst_estimates(self, ticker) -> Dict:
        """Get analyst estimates - legacy method."""
        return self._get_analyst_estimates_from_info(market_data.get_info(ticker.ticker if hasattr(ticker, 'ticker') else str(ticker)))
    
    def _get_analyst_estimates_from_info(self, info: Optional[Dict]) -> Dict:
        """Get analyst estimates from info dict."""
        if not info:
            return {}
        
        return {
            "recommendation": info.get("recommendationKey", "none"),
            "target_price": info.get("targetMeanPrice"),
            "current_price": info.get("currentPrice"),
            "num_analysts": info.get("numberOfAnalystOpinions", 0),
        }
    
    def _compute_score_components(self, symbol: str, hist: pd.DataFrame,
                                   gap_analysis: Dict, estimates: Dict) -> Dict:
        """
        Compute explainable score components (0-1 each).
        """
        scores = {}
        
        # 1. Gap behavior score
        # Higher if we can predict behavior (fade or continuation)
        fade_rate = gap_analysis.get("fade_rate", 0.5)
        cont_rate = gap_analysis.get("continuation_rate", 0.5)
        predictability = max(fade_rate, cont_rate)
        scores["gap_behavior"] = predictability
        
        # 2. Trend consistency score
        # How consistent is the pattern across quarters
        quarters = gap_analysis.get("quarters_analyzed", 0)
        if quarters >= 4:
            scores["trend_consistency"] = predictability * 0.8 + 0.2
        elif quarters >= 2:
            scores["trend_consistency"] = predictability * 0.5
        else:
            scores["trend_consistency"] = 0.3
        
        # 3. Analyst sensitivity score
        # Based on analyst coverage and recommendations
        num_analysts = estimates.get("num_analysts", 0)
        recommendation = estimates.get("recommendation", "none")
        
        if num_analysts >= 10:
            analyst_base = 0.7
        elif num_analysts >= 5:
            analyst_base = 0.5
        else:
            analyst_base = 0.3
        
        if recommendation in ["buy", "strongBuy"]:
            analyst_base += 0.2
        elif recommendation in ["hold"]:
            analyst_base += 0.1
        
        scores["analyst_sensitivity"] = min(1.0, analyst_base)
        
        # 4. Volatility alignment score
        # Current volatility vs historical
        try:
            current_vol = hist['Close'].pct_change().tail(20).std() * np.sqrt(252) * 100
            hist_vol = hist['Close'].pct_change().std() * np.sqrt(252) * 100
            
            vol_ratio = current_vol / hist_vol if hist_vol > 0 else 1
            
            # Score higher if volatility is "normal" (0.8-1.2 ratio)
            if 0.8 <= vol_ratio <= 1.2:
                scores["volatility_alignment"] = 0.8
            elif 0.5 <= vol_ratio <= 1.5:
                scores["volatility_alignment"] = 0.6
            else:
                scores["volatility_alignment"] = 0.4
        except:
            scores["volatility_alignment"] = 0.5
        
        # 5. Sentiment bias score (simplified - would use news API in production)
        # For now, use recent price momentum as proxy
        try:
            monthly_return = (hist['Close'].iloc[-1] / hist['Close'].iloc[-20] - 1) * 100
            
            if monthly_return > 5:
                scores["sentiment_bias"] = 0.7
            elif monthly_return > 0:
                scores["sentiment_bias"] = 0.6
            elif monthly_return > -5:
                scores["sentiment_bias"] = 0.5
            else:
                scores["sentiment_bias"] = 0.3
        except:
            scores["sentiment_bias"] = 0.5
        
        return scores
    
    def _calculate_final_score(self, scores: Dict) -> int:
        """
        Calculate final score (1-5) from components.
        
        Uses weighted average then maps to 1-5 scale.
        """
        weighted_sum = 0
        total_weight = 0
        
        for component, weight in config.SCORE_WEIGHTS.items():
            if component in scores:
                weighted_sum += scores[component] * weight
                total_weight += weight
        
        if total_weight == 0:
            return 2
        
        avg_score = weighted_sum / total_weight
        
        # Map to 1-5
        if avg_score >= 0.8:
            return 5
        elif avg_score >= 0.65:
            return 4
        elif avg_score >= 0.5:
            return 3
        elif avg_score >= 0.35:
            return 2
        else:
            return 1
    
    # ==================== FULL PIPELINE ====================
    
    def run_full_pipeline(self):
        """
        Run the complete weekend analysis pipeline.
        
        Should be called on Saturday or Sunday.
        """
        logger.info("=" * 60)
        logger.info("WEEKEND ANALYSIS PIPELINE")
        logger.info(f"Time: {datetime.now()}")
        logger.info("=" * 60)
        
        # Step 1: Refresh universe
        self.refresh_universe()
        
        # Step 2: Get earnings candidates
        candidates = self.get_earnings_candidates()
        
        # Step 3: Analyze candidates
        if candidates:
            self.analyze_candidates(candidates)
        
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 60)


# ==================== CLI ====================
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format=config.LOG_FORMAT
    )
    
    pipeline = WeekendAnalysisPipeline()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "universe":
            pipeline.refresh_universe()
        elif cmd == "earnings":
            pipeline.get_earnings_candidates()
        elif cmd == "analyze":
            pipeline.analyze_candidates()
        elif cmd == "full":
            pipeline.run_full_pipeline()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python weekend_pipeline.py [universe|earnings|analyze|full]")
    else:
        # Default: run full pipeline
        pipeline.run_full_pipeline()
