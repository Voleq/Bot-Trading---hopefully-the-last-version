"""
core/telegram_bot.py - Telegram Bot Command Handler

Listens for commands from Telegram and executes them.

Commands:
  /status     - Show bot status, positions, P&L
  /positions  - List all open positions
  /balance    - Show account balance
  /trades     - Show today's trades
  /signals    - Show current signals
  /buy SYMBOL - Manual buy (e.g., /buy AAPL)
  /sell SYMBOL - Manual sell (e.g., /sell AAPL)
  /close SYMBOL - Close position
  /closeall   - Close all positions
  /pause      - Pause trading
  /resume     - Resume trading
  /analyze SYMBOL - Analyze a stock
  /news SYMBOL - Get recent news
  /help       - Show help

Usage:
    bot = TelegramBot()
    bot.start()  # Start listening in background
    bot.stop()   # Stop listening
"""

import logging
import time
import threading
from datetime import datetime
from typing import Callable, Dict, Optional, Any
import requests

import config

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies
_t212_client = None
_storage = None
_market_data = None

def _get_t212_client():
    global _t212_client
    if _t212_client is None:
        from core.t212_client import T212Client, clean_symbol
        _t212_client = (T212Client, clean_symbol)
    return _t212_client

def _get_storage():
    global _storage
    if _storage is None:
        from core.storage import Storage
        _storage = Storage
    return _storage

def _get_market_data():
    global _market_data
    if _market_data is None:
        from core import market_data
        _market_data = market_data
    return _market_data

def _clean_symbol(symbol: str) -> str:
    """Helper to clean symbol using t212_client."""
    _, clean_fn = _get_t212_client()
    return clean_fn(symbol)


class TelegramBot:
    """
    Telegram bot that listens for commands.
    """
    
    def __init__(self, t212_client=None, trading_bot=None):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        T212Client, _ = _get_t212_client()
        Storage = _get_storage()
        
        # Can pass either t212_client directly or get it from trading_bot
        if trading_bot:
            self.t212 = trading_bot.t212
            self.trading_bot = trading_bot
        else:
            self.t212 = t212_client or T212Client(paper=config.PAPER_MODE)
            self.trading_bot = None
        
        self.storage = Storage()
        
        # State
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        
        # Command handlers
        self._commands: Dict[str, Callable] = {
            "start": self._cmd_start,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "positions": self._cmd_positions,
            "balance": self._cmd_balance,
            "trades": self._cmd_trades,
            "signals": self._cmd_signals,
            "buy": self._cmd_buy,
            "sell": self._cmd_sell,
            "close": self._cmd_close,
            "closeall": self._cmd_closeall,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "analyze": self._cmd_analyze,
            "news": self._cmd_news,
            "universe": self._cmd_universe,
            # New commands
            "price": self._cmd_price,
            "scan": self._cmd_scan,
            "weeklyrun": self._cmd_weeklyrun,
            "earnings": self._cmd_earnings,
            "performance": self._cmd_performance,
            "watchlist": self._cmd_watchlist,
            "top": self._cmd_top,
            "sectors": self._cmd_sectors,
        }
        
        logger.info("Telegram bot initialized")
    
    @property
    def is_paused(self) -> bool:
        return self._paused
    
    # ==================== SEND MESSAGES ====================
    
    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message."""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            resp = requests.post(url, data=data, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
    
    # ==================== RECEIVE MESSAGES ====================
    
    def _get_updates(self) -> list:
        """Get new messages from Telegram."""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self._last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message"]
            }
            resp = requests.get(url, params=params, timeout=35)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result", [])
            return []
        except Exception as e:
            logger.debug(f"Get updates error: {e}")
            return []
    
    def _process_update(self, update: dict):
        """Process a single update."""
        self._last_update_id = update.get("update_id", self._last_update_id)
        
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        
        # Only process messages from authorized chat
        if str(chat_id) != str(self.chat_id):
            logger.warning(f"Unauthorized message from chat_id: {chat_id}")
            return
        
        # Check if it's a command
        if text.startswith("/"):
            self._handle_command(text)
    
    def _handle_command(self, text: str):
        """Handle a command."""
        parts = text.split()
        command = parts[0].lower().replace("/", "").replace("@", "").split("@")[0]
        args = parts[1:] if len(parts) > 1 else []
        
        logger.info(f"Command received: /{command} {' '.join(args)}")
        
        handler = self._commands.get(command)
        if handler:
            try:
                handler(args)
            except Exception as e:
                logger.error(f"Command error: {e}")
                self.send(f"❌ Error: {str(e)[:100]}")
        else:
            self.send(f"❓ Unknown command: /{command}\nUse /help for available commands.")
    
    # ==================== COMMAND HANDLERS ====================
    
    def _cmd_start(self, args):
        """Start command."""
        self.send(
            "🤖 <b>Trading Bot Active</b>\n\n"
            "I'm ready to help you trade!\n"
            "Use /help to see available commands."
        )
    
    def _cmd_help(self, args):
        """Show help."""
        help_text = """
🤖 <b>Trading Bot Commands</b>

<b>📊 Status</b>
/status - Bot status & summary
/positions - Open positions
/balance - Account balance
/trades - Today's trades
/performance - Portfolio P&L summary

<b>📈 Trading</b>
/buy SYMBOL [AMOUNT] - Buy stock
/sell SYMBOL [QTY] - Sell stock
/close SYMBOL - Close position
/closeall - Close all positions

<b>🔍 Analysis</b>
/analyze SYMBOL - Full stock analysis
/news SYMBOL - News report with sentiment
/price SYMBOL - Quick price check
/signals - Current signals
/earnings - Upcoming earnings this week
/sectors - Sector momentum rankings
/top - Top signals from last scan

<b>🔄 Scans</b>
/scan - Run daily strategy scans
/weeklyrun - Run full weekend analysis

<b>📡 Watchlist</b>
/watchlist - Show watchlist
/watchlist add SYMBOL - Add to watchlist
/watchlist remove SYMBOL - Remove from watchlist

<b>⚙️ Control</b>
/pause - Pause auto-trading
/resume - Resume auto-trading
/universe - T212 universe stats
/help - This message

<b>Examples:</b>
<code>/buy AAPL 100</code> - Buy $100 of AAPL
<code>/news TSLA</code> - Full news report
<code>/price NVDA</code> - Quick price
<code>/watchlist add MSFT</code> - Watch MSFT
"""
        self.send(help_text)
    
    def _cmd_status(self, args):
        """Show bot status."""
        try:
            account = self.t212.get_account()
            positions = self.t212.get_positions()
            trades = self.storage.get_trades()
            
            # Calculate P&L
            total_pnl = sum(p.pnl for p in positions) if positions else 0
            today_trades = len([t for t in trades if t.get("action") == "BUY"])
            
            status = "⏸️ PAUSED" if self._paused else "🟢 RUNNING"
            mode = "📝 PAPER" if config.PAPER_MODE else "💰 LIVE"
            
            msg = f"""
📊 <b>Bot Status</b>

{status} | {mode}

💰 <b>Account</b>
Cash: {account.currency} {account.free_cash:,.2f}
Invested: {account.currency} {account.invested:,.2f}
Total: {account.currency} {account.total_value:,.2f}

📈 <b>Positions</b>
Open: {len(positions)}
P&L: {account.currency} {total_pnl:+,.2f}

📅 <b>Today</b>
Trades: {today_trades}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error getting status: {e}")
    
    def _cmd_positions(self, args):
        """List positions."""
        try:
            positions = self.t212.get_positions()
            
            if not positions:
                self.send("📭 No open positions")
                return
            
            msg = f"📈 <b>Open Positions ({len(positions)})</b>\n\n"
            
            total_pnl = 0
            for p in positions:
                emoji = "🟢" if p.pnl >= 0 else "🔴"
                msg += f"{emoji} <b>{p.symbol}</b>\n"
                msg += f"   Qty: {p.quantity:.4f} @ ${p.avg_price:.2f}\n"
                msg += f"   Now: ${p.current_price:.2f}\n"
                msg += f"   P&L: ${p.pnl:+.2f} ({p.pnl_pct:+.1f}%)\n\n"
                total_pnl += p.pnl
            
            msg += f"<b>Total P&L: ${total_pnl:+,.2f}</b>"
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_balance(self, args):
        """Show balance."""
        try:
            account = self.t212.get_account()
            
            msg = f"""
💰 <b>Account Balance</b>

Free Cash: {account.currency} {account.free_cash:,.2f}
Invested: {account.currency} {account.invested:,.2f}
━━━━━━━━━━━━━━━━
Total: {account.currency} {account.total_value:,.2f}
"""
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_trades(self, args):
        """Show today's trades."""
        try:
            trades = self.storage.get_trades()
            
            if not trades:
                self.send("📭 No trades today")
                return
            
            msg = f"📋 <b>Today's Trades ({len(trades)})</b>\n\n"
            
            for t in trades[-10:]:  # Last 10
                action = t.get("action", "?")
                emoji = "🟢" if action == "BUY" else "🔴"
                symbol = t.get("symbol", "?")
                price = t.get("price", 0)
                qty = t.get("quantity", 0)
                
                msg += f"{emoji} {action} {symbol}\n"
                msg += f"   {qty:.4f} @ ${price:.2f}\n"
                
                if action == "SELL" and "pnl" in t:
                    pnl = t.get("pnl", 0)
                    msg += f"   P&L: ${pnl:+.2f}\n"
                msg += "\n"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_signals(self, args):
        """Show current signals."""
        try:
            # Load analysis
            analysis = self.storage.get_analysis_results()
            
            if not analysis:
                self.send("📭 No signals available. Run weekend analysis first.")
                return
            
            # Top signals
            top = sorted(analysis, key=lambda x: x.get("final_score", 0), reverse=True)[:10]
            
            msg = "📊 <b>Top Signals</b>\n\n"
            
            for a in top:
                symbol = a.get("symbol", "?")
                score = a.get("final_score", 0)
                emoji = "🟢" if score >= 4 else "🟡" if score >= 3 else "⚪"
                
                msg += f"{emoji} <b>{symbol}</b>: Score {score}/5\n"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_buy(self, args):
        """Manual buy command."""
        if not args:
            self.send("❌ Usage: /buy SYMBOL [AMOUNT]\nExample: /buy AAPL 100")
            return
        
        symbol = _clean_symbol(args[0])
        amount = float(args[1]) if len(args) > 1 else 50  # Default $50
        
        if not symbol:
            self.send("❌ Invalid symbol")
            return
        
        try:
            # Get price
            price = _get_market_data().get_current_price(symbol)
            if not price:
                self.send(f"❌ Cannot get price for {symbol}")
                return
            
            quantity = round(amount / price, 2)
            
            # Confirm
            self.send(
                f"🛒 <b>Buy Order</b>\n\n"
                f"Symbol: {symbol}\n"
                f"Price: ${price:.2f}\n"
                f"Quantity: {quantity}\n"
                f"Value: ${amount:.2f}\n\n"
                f"Executing..."
            )
            
            # Execute
            result = self.t212.buy(symbol, quantity)
            
            if result:
                self.send(f"✅ Bought {quantity} {symbol} @ ${price:.2f}")
                
                # Log trade
                self.storage.log_trade({
                    "action": "BUY",
                    "symbol": symbol,
                    "price": price,
                    "quantity": quantity,
                    "value": amount,
                    "source": "telegram"
                })
            else:
                self.send(f"❌ Order failed")
                
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_sell(self, args):
        """Manual sell command."""
        if not args:
            self.send("❌ Usage: /sell SYMBOL [QUANTITY]\nExample: /sell AAPL 0.5")
            return
        
        symbol = _clean_symbol(args[0])
        
        if not symbol:
            self.send("❌ Invalid symbol")
            return
        
        try:
            # Get position
            position = self.t212.get_position(symbol)
            
            if not position:
                self.send(f"❌ No position in {symbol}")
                return
            
            # Quantity (default: all)
            if len(args) > 1:
                quantity = min(float(args[1]), position.quantity)
            else:
                quantity = position.quantity
            
            quantity = round(quantity, 2)
            
            # Execute
            self.send(f"📤 Selling {quantity} {symbol}...")
            
            result = self.t212.sell(symbol, quantity)
            
            if result:
                pnl = position.pnl * (quantity / position.quantity)
                self.send(f"✅ Sold {quantity} {symbol}\nP&L: ${pnl:+.2f}")
            else:
                self.send(f"❌ Sell failed")
                
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_close(self, args):
        """Close a position."""
        if not args:
            self.send("❌ Usage: /close SYMBOL")
            return
        
        symbol = _clean_symbol(args[0])
        
        try:
            position = self.t212.get_position(symbol)
            
            if not position:
                self.send(f"❌ No position in {symbol}")
                return
            
            self.send(f"📤 Closing {symbol}...")
            
            result = self.t212.close_position(symbol)
            
            if result:
                self.send(f"✅ Closed {symbol}\nP&L: ${position.pnl:+.2f}")
            else:
                self.send(f"❌ Close failed")
                
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_closeall(self, args):
        """Close all positions."""
        try:
            positions = self.t212.get_positions()
            
            if not positions:
                self.send("📭 No positions to close")
                return
            
            self.send(f"⚠️ Closing {len(positions)} positions...")
            
            closed = 0
            total_pnl = 0
            
            for p in positions:
                result = self.t212.close_position(p.symbol)
                if result:
                    closed += 1
                    total_pnl += p.pnl
            
            self.send(f"✅ Closed {closed}/{len(positions)} positions\nTotal P&L: ${total_pnl:+.2f}")
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_pause(self, args):
        """Pause auto-trading."""
        self._paused = True
        self.send("⏸️ Auto-trading PAUSED\n\nManual trading still available.\nUse /resume to continue.")
    
    def _cmd_resume(self, args):
        """Resume auto-trading."""
        self._paused = False
        self.send("▶️ Auto-trading RESUMED")
    
    def _cmd_analyze(self, args):
        """Analyze a stock."""
        if not args:
            self.send("❌ Usage: /analyze SYMBOL")
            return
        
        symbol = _clean_symbol(args[0])
        
        try:
            self.send(f"🔍 Analyzing {symbol}...")
            
            # Get data
            info = _get_market_data().get_info(symbol)
            hist = _get_market_data().get_history(symbol, period="1mo")
            
            if not info or hist is None:
                self.send(f"❌ Cannot get data for {symbol}")
                return
            
            price = hist['Close'].iloc[-1]
            change = (price / hist['Close'].iloc[0] - 1) * 100
            vol = hist['Close'].pct_change().std() * (252 ** 0.5) * 100
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs.iloc[-1]))
            
            # 50 SMA
            sma50 = hist['Close'].rolling(min(50, len(hist))).mean().iloc[-1]
            above_sma = "✅" if price > sma50 else "❌"
            
            msg = f"""
🔍 <b>{symbol} Analysis</b>

💰 Price: ${price:.2f}
📈 1M Change: {change:+.1f}%
📊 Volatility: {vol:.1f}%
📉 RSI(14): {rsi:.0f}
{above_sma} vs 50 SMA: ${sma50:.2f}

📋 Info:
Market Cap: ${info.get('marketCap', 0)/1e9:.1f}B
Avg Volume: {info.get('averageVolume', 0):,.0f}
"""
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_news(self, args):
        """Get comprehensive news report with sentiment analysis."""
        if not args:
            self.send("❌ Usage: /news SYMBOL")
            return
        
        symbol = _clean_symbol(args[0])
        self.send(f"🔍 Fetching news for {symbol}...")
        
        try:
            from core.news_monitor import NewsMonitor
            monitor = NewsMonitor()
            report = monitor.get_full_news_report(symbol)
            
            if report["count"] == 0:
                self.send(f"📭 No recent news for {symbol}")
                return
            
            # Build message
            signal_emoji = {
                "BULLISH": "🟢", "BEARISH": "🔴",
                "NEUTRAL": "🟡", "MIXED": "🔵", "NO_DATA": "⚪"
            }
            
            emoji = signal_emoji.get(report["signal"], "⚪")
            
            msg = f"📰 <b>{symbol} News Report</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"{emoji} Signal: <b>{report['signal']}</b>\n"
            msg += f"📊 Sentiment: {report['sentiment']:+.2f}\n"
            msg += f"✅ Positive: {report['positive']} | ❌ Negative: {report['negative']}\n"
            msg += f"📄 Total: {report['count']} headlines\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            # Show top headlines with sentiment
            for item in report["headlines"][:10]:
                score = item["score"]
                if score > 0.2:
                    icon = "🟢"
                elif score < -0.2:
                    icon = "🔴"
                else:
                    icon = "⚪"
                
                title = item["title"][:90]
                msg += f"{icon} {title}\n"
                msg += f"   <i>{item['source']} • {item['time']}</i>\n"
                if item["summary"] and score != 0:
                    msg += f"   💡 {item['summary'][:80]}\n"
                msg += "\n"
            
            # Trim if too long for Telegram
            if len(msg) > 4000:
                msg = msg[:3950] + "\n\n... (truncated)"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_universe(self, args):
        """Show universe stats."""
        try:
            instruments = self.t212.get_all_instruments()
            
            msg = f"""
🌐 <b>Trading Universe</b>

Total Instruments: {len(instruments)}

Use /analyze SYMBOL to check a stock.
"""
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    # ==================== NEW COMMANDS ====================
    
    def _cmd_price(self, args):
        """Quick price check for a symbol."""
        if not args:
            self.send("❌ Usage: /price SYMBOL")
            return
        
        symbol = _clean_symbol(args[0])
        
        try:
            md = _get_market_data()
            price = md.get_current_price(symbol)
            
            if price is None:
                self.send(f"❌ No price data for {symbol}")
                return
            
            # Try to get change info
            info = md.get_info(symbol)
            
            msg = f"💰 <b>{symbol}</b>: ${price:.2f}"
            
            if info:
                change = info.get("regularMarketChange")
                change_pct = info.get("regularMarketChangePercent")
                name = info.get("shortName", "")
                
                if name:
                    msg = f"💰 <b>{symbol}</b> ({name})\n"
                    msg += f"Price: <b>${price:.2f}</b>"
                
                if change is not None and change_pct is not None:
                    emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
                    msg += f"\n{emoji} {change:+.2f} ({change_pct:+.2f}%)"
                
                vol = info.get("volume")
                avg_vol = info.get("averageVolume")
                if vol:
                    msg += f"\n📊 Volume: {vol:,.0f}"
                    if avg_vol and avg_vol > 0:
                        vol_ratio = vol / avg_vol
                        if vol_ratio > 1.5:
                            msg += f" ⚡ ({vol_ratio:.1f}x avg)"
                
                high52 = info.get("fiftyTwoWeekHigh")
                low52 = info.get("fiftyTwoWeekLow")
                if high52 and low52:
                    pct_from_high = (price / high52 - 1) * 100
                    msg += f"\n52W: ${low52:.2f} - ${high52:.2f} ({pct_from_high:+.1f}% from high)"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_scan(self, args):
        """Run daily strategy scans."""
        self.send("🔄 Running daily scans...")
        
        try:
            from strategies.manager import StrategyManager
            manager = StrategyManager(t212_client=self.t212)
            signals = manager.run_daily_scans()
            
            if not signals:
                self.send("📭 No signals generated from daily scan.")
                return
            
            msg = f"📡 <b>Daily Scan Results</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"Total signals: {len(signals)}\n\n"
            
            for sig in signals[:15]:
                emoji = "🟢" if sig.signal_type.value == "BUY" else "🔴"
                msg += f"{emoji} <b>{sig.symbol}</b> ({sig.strategy})\n"
                msg += f"   Score: {sig.score:.1f} | {sig.reason[:60]}\n"
            
            if len(signals) > 15:
                msg += f"\n... and {len(signals) - 15} more"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Scan failed: {e}")
    
    def _cmd_weeklyrun(self, args):
        """Trigger full weekend analysis pipeline."""
        self.send("🔬 Starting weekend analysis pipeline...\nThis may take several minutes.")
        
        try:
            import threading
            
            def _run():
                try:
                    from analysis.weekend_pipeline import WeekendAnalysisPipeline
                    from strategies.manager import StrategyManager
                    
                    # Run earnings pipeline
                    pipeline = WeekendAnalysisPipeline()
                    pipeline.run()
                    
                    # Run strategy weekend analysis
                    manager = StrategyManager(t212_client=self.t212)
                    manager.run_weekend_analysis()
                    
                    self.send("✅ Weekend analysis complete! Check /signals and /earnings for results.")
                except Exception as e:
                    self.send(f"❌ Weekend analysis failed: {e}")
            
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_earnings(self, args):
        """Show upcoming earnings this week."""
        try:
            Storage = _get_storage()
            storage = Storage()
            
            candidates = storage.get_earnings_candidates()
            
            if not candidates:
                self.send("📭 No earnings candidates loaded. Run /weeklyrun first.")
                return
            
            msg = f"📅 <b>Upcoming Earnings</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"Total: {len(candidates)} stocks\n\n"
            
            # Group by date
            by_date = {}
            for c in candidates:
                date = c.get("date", "unknown")
                by_date.setdefault(date, []).append(c)
            
            for date in sorted(by_date.keys()):
                msg += f"📆 <b>{date}</b>\n"
                for c in by_date[date][:10]:
                    time_str = c.get("time", "?")
                    eps = c.get("eps_estimate")
                    eps_str = f"EPS est: {eps}" if eps else ""
                    msg += f"  • {c['symbol']} ({time_str}) {eps_str}\n"
                if len(by_date[date]) > 10:
                    msg += f"  ... and {len(by_date[date]) - 10} more\n"
                msg += "\n"
            
            if len(msg) > 4000:
                msg = msg[:3950] + "\n... (truncated)"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_performance(self, args):
        """Show portfolio performance summary."""
        try:
            positions = self.t212.get_positions()
            account = self.t212.get_account()
            
            if not positions:
                cash = account.get("cash", 0) if isinstance(account, dict) else 0
                self.send(f"📊 No open positions.\n💵 Cash: ${cash:,.2f}")
                return
            
            total_value = 0
            total_pnl = 0
            winners = 0
            losers = 0
            
            msg = f"📊 <b>Portfolio Performance</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for pos in positions:
                pnl = pos.pnl if hasattr(pos, 'pnl') else 0
                pnl_pct = pos.pnl_pct if hasattr(pos, 'pnl_pct') else 0
                value = pos.current_value if hasattr(pos, 'current_value') else 0
                
                total_value += value
                total_pnl += pnl
                
                if pnl > 0:
                    winners += 1
                    emoji = "🟢"
                elif pnl < 0:
                    losers += 1
                    emoji = "🔴"
                else:
                    emoji = "⚪"
                
                msg += f"{emoji} <b>{pos.ticker}</b>: {pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            
            msg += f"\n━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"💰 Total Value: ${total_value:,.2f}\n"
            
            pnl_emoji = "📈" if total_pnl > 0 else "📉"
            msg += f"{pnl_emoji} Total P&L: {total_pnl:+.2f}\n"
            msg += f"✅ Winners: {winners} | ❌ Losers: {losers}\n"
            
            if winners + losers > 0:
                win_rate = winners / (winners + losers) * 100
                msg += f"📊 Win Rate: {win_rate:.0f}%"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_watchlist(self, args):
        """Manage news watchlist."""
        from core.news_monitor import NewsMonitor
        
        # Persist watchlist in storage
        Storage = _get_storage()
        storage = Storage()
        
        if not args:
            # Show current watchlist
            try:
                wl = storage.get_watchlist()
                if not wl:
                    self.send("📡 Watchlist is empty.\nUse /watchlist add SYMBOL to add stocks.")
                    return
                msg = f"📡 <b>Watchlist</b> ({len(wl)} symbols)\n\n"
                for s in sorted(wl):
                    price = _get_market_data().get_current_price(s)
                    price_str = f"${price:.2f}" if price else "N/A"
                    msg += f"• <b>{s}</b>: {price_str}\n"
                self.send(msg)
            except Exception as e:
                self.send(f"❌ Error: {e}")
            return
        
        action = args[0].lower()
        
        if action == "add" and len(args) > 1:
            symbol = _clean_symbol(args[1])
            storage.add_to_watchlist(symbol)
            self.send(f"✅ Added {symbol} to watchlist")
        elif action == "remove" and len(args) > 1:
            symbol = _clean_symbol(args[1])
            storage.remove_from_watchlist(symbol)
            self.send(f"🗑️ Removed {symbol} from watchlist")
        else:
            self.send("Usage: /watchlist [add|remove] SYMBOL")
    
    def _cmd_top(self, args):
        """Show top signals from latest analysis."""
        try:
            Storage = _get_storage()
            storage = Storage()
            
            from core.storage import get_week_id
            week_id = get_week_id()
            
            results = storage.get_analysis_results(week_id)
            
            if not results:
                self.send("📭 No analysis results. Run /weeklyrun first.")
                return
            
            # Sort by score
            scored = [r for r in results if r.get("score", 0) > 0]
            scored.sort(key=lambda x: x.get("score", 0), reverse=True)
            
            msg = f"🏆 <b>Top Signals (Week {week_id})</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for r in scored[:10]:
                score = r.get("score", 0)
                symbol = r.get("symbol", "?")
                strategy = r.get("strategy", "")
                
                if score >= 4:
                    emoji = "🔥"
                elif score >= 3:
                    emoji = "⭐"
                else:
                    emoji = "📊"
                
                msg += f"{emoji} <b>{symbol}</b> Score: {score}/5"
                if strategy:
                    msg += f" ({strategy})"
                msg += "\n"
            
            if not scored:
                msg += "No high-confidence signals this week."
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    def _cmd_sectors(self, args):
        """Show sector momentum rankings."""
        try:
            import json
            from core.storage import get_week_id
            
            week_id = get_week_id()
            filepath = config.DATA_DIR / f"sector_momentum_{week_id}.json"
            
            if not filepath.exists():
                self.send("📭 No sector data. Run /weeklyrun first.")
                return
            
            with open(filepath) as f:
                data = json.load(f)
            
            results = data.get("results", [])
            if not results:
                self.send("📭 No sector momentum data available.")
                return
            
            msg = f"📊 <b>Sector Momentum</b>\n"
            msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for r in results:
                rank = r.get("momentum_rank", 0)
                name = r.get("sector_name", r.get("symbol", "?"))
                ret = r.get("return_1m", 0)
                score = r.get("score", 0)
                
                if rank <= 3:
                    emoji = "🟢"
                elif rank >= len(results) - 2:
                    emoji = "🔴"
                else:
                    emoji = "🟡"
                
                msg += f"{emoji} #{rank} <b>{name}</b>\n"
                msg += f"   1M Return: {ret:+.1f}% | Score: {score}\n"
            
            self.send(msg)
            
        except Exception as e:
            self.send(f"❌ Error: {e}")
    
    # ==================== START/STOP ====================
    
    def start(self):
        """Start listening for commands in background."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        
        logger.info("Telegram bot started listening")
        self.send("🤖 Bot started! Use /help for commands.")
    
    def stop(self):
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Telegram bot stopped")
    
    def _listen_loop(self):
        """Main listening loop."""
        while self._running:
            try:
                updates = self._get_updates()
                
                for update in updates:
                    self._process_update(update)
                    
            except Exception as e:
                logger.error(f"Listen loop error: {e}")
                time.sleep(5)


# ==================== CLI TEST ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    print("Starting Telegram bot...")
    print("Send /help in Telegram to see commands")
    print("Press Ctrl+C to stop\n")
    
    bot = TelegramBot()
    bot.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        bot.stop()
