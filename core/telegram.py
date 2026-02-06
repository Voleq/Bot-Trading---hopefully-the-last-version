"""
core/telegram.py - Telegram Notifications

Sends structured alerts for:
- Weekly universe updates
- Earnings candidates
- Analysis results
- Trade entries/exits
- Errors
"""

import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime

import config

logger = logging.getLogger(__name__)


class Telegram:
    """Telegram notification system."""
    
    def __init__(self):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        
        if not self.enabled:
            logger.warning("Telegram not configured")
    
    def send(self, message: str, silent: bool = False) -> bool:
        """Send message."""
        if not self.enabled:
            return False
        
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_notification": silent
                },
                timeout=10
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False
    
    # === Structured Messages ===
    
    def universe_update(self, count: int, week_start: str):
        """Weekly universe scan complete."""
        msg = (
            f"📊 <b>Weekly Universe Updated</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Week: {week_start}\n"
            f"Instruments: {count:,}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.send(msg)
    
    def earnings_candidates(self, candidates: List[Dict], week_start: str):
        """Earnings candidates for the week."""
        msg = (
            f"📅 <b>Earnings Candidates</b>\n"
            f"Week: {week_start}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        if not candidates:
            msg += "No candidates this week.\n"
        else:
            # Group by day
            by_day = {}
            for c in candidates:
                day = c.get("date", "Unknown")
                if day not in by_day:
                    by_day[day] = []
                by_day[day].append(c)
            
            for day, items in sorted(by_day.items()):
                msg += f"\n<b>{day}</b>\n"
                for item in items[:10]:  # Max 10 per day
                    symbol = item.get("symbol", "?")
                    time_str = item.get("time", "")
                    time_emoji = "🌅" if time_str == "bmo" else "🌙" if time_str == "amc" else "❓"
                    msg += f"  {time_emoji} {symbol}\n"
        
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\nTotal: {len(candidates)}"
        self.send(msg)
    
    def analysis_results(self, results: List[Dict], week_start: str):
        """Analysis results for earnings candidates."""
        msg = (
            f"🔬 <b>Analysis Complete</b>\n"
            f"Week: {week_start}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        # Sort by score descending
        sorted_results = sorted(results, key=lambda x: x.get("final_score", 0), reverse=True)
        
        for r in sorted_results[:15]:  # Top 15
            symbol = r.get("symbol", "?")
            score = r.get("final_score", 0)
            behavior = r.get("gap_behavior", "?")
            
            # Score emoji
            if score >= 4:
                emoji = "🟢"
            elif score >= 3:
                emoji = "🟡"
            else:
                emoji = "🔴"
            
            msg += f"{emoji} <b>{symbol}</b>: {score}/5 ({behavior})\n"
        
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\nAnalyzed: {len(results)}"
        self.send(msg)
    
    def trade_entry(self, symbol: str, price: float, quantity: float, 
                    score: int, reason: str):
        """Trade entry alert."""
        msg = (
            f"🟢 <b>BUY {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Price: ${price:.2f}\n"
            f"Qty: {quantity:.4f}\n"
            f"Score: {score}/5\n"
            f"Reason: {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send(msg)
    
    def trade_exit(self, symbol: str, entry: float, exit_price: float,
                   pnl: float, pnl_pct: float, reason: str):
        """Trade exit alert."""
        emoji = "📈" if pnl >= 0 else "📉"
        pnl_color = "🟢" if pnl >= 0 else "🔴"
        
        msg = (
            f"🔴 <b>SELL {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Entry: ${entry:.2f}\n"
            f"Exit: ${exit_price:.2f}\n"
            f"{pnl_color} P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            f"Reason: {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        self.send(msg)
    
    def no_trade(self, symbol: str, reason: str):
        """Trade skipped alert."""
        msg = f"⏭️ <b>SKIP {symbol}</b>\nReason: {reason}"
        self.send(msg, silent=True)
    
    def error(self, context: str, message: str):
        """Error alert."""
        msg = f"⚠️ <b>ERROR</b>\nContext: {context}\nMessage: {message[:200]}"
        self.send(msg)
    
    def daily_summary(self, pnl: float, trades: int, positions: int):
        """Daily summary."""
        emoji = "📈" if pnl >= 0 else "📉"
        msg = (
            f"{emoji} <b>Daily Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"P&L: ${pnl:+,.2f}\n"
            f"Trades: {trades}\n"
            f"Positions: {positions}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.send(msg)
