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
from typing import Callable, Dict, Optional
import requests

import config
from core.t212_client import T212Client, clean_symbol
from core.storage import Storage
from core import market_data

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Telegram bot that listens for commands.
    """
    
    def __init__(self, t212_client: T212Client = None, trading_bot = None):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
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

<b>📈 Trading</b>
/buy SYMBOL [AMOUNT] - Buy stock
/sell SYMBOL [QTY] - Sell stock
/close SYMBOL - Close position
/closeall - Close all positions

<b>🔍 Analysis</b>
/analyze SYMBOL - Analyze stock
/news SYMBOL - Recent news
/signals - Current signals
/universe - T212 universe stats

<b>⚙️ Control</b>
/pause - Pause auto-trading
/resume - Resume auto-trading
/help - This message

<b>Examples:</b>
<code>/buy AAPL 100</code> - Buy $100 of AAPL
<code>/sell AAPL 0.5</code> - Sell 0.5 shares
<code>/analyze TSLA</code> - Analyze Tesla
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
        
        symbol = clean_symbol(args[0])
        amount = float(args[1]) if len(args) > 1 else 50  # Default $50
        
        if not symbol:
            self.send("❌ Invalid symbol")
            return
        
        try:
            # Get price
            price = market_data.get_current_price(symbol)
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
        
        symbol = clean_symbol(args[0])
        
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
        
        symbol = clean_symbol(args[0])
        
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
        
        symbol = clean_symbol(args[0])
        
        try:
            self.send(f"🔍 Analyzing {symbol}...")
            
            # Get data
            info = market_data.get_info(symbol)
            hist = market_data.get_history(symbol, period="1mo")
            
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
        """Get recent news."""
        if not args:
            self.send("❌ Usage: /news SYMBOL")
            return
        
        symbol = clean_symbol(args[0])
        
        try:
            news = market_data.get_news(symbol, max_items=5)
            
            if not news:
                self.send(f"📭 No recent news for {symbol}")
                return
            
            msg = f"📰 <b>{symbol} News</b>\n\n"
            
            for item in news:
                title = item.get("title", "")[:100]
                publisher = item.get("publisher", "Unknown")
                msg += f"• {title}\n  <i>{publisher}</i>\n\n"
            
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
