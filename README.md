# Trading212 Automated Trading Bot

A disciplined, multi-strategy trading system for Trading212 with real-time news monitoring.

## 🎯 Features

- **6 Trading Strategies** - Earnings, Sector Rotation, Mean Reversion, Breakout, Gap Fade, VWAP, ORB
- **Real-Time News Monitoring** - Automatic news classification and position impact alerts
- **Pre-Market Scanning** - Strategies scan at 9:00 AM before market open
- **Explainable Scoring** - All trades scored 1-5 with component breakdown
- **NO-TRADE Conditions** - Explicit skip logic with logging
- **Invalidation-Based Exits** - Rule-based position management
- **Weekend Analysis** - Frozen data for weekday execution

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Core Principles](#core-principles)
3. [Strategies](#strategies)
4. [System Architecture](#system-architecture)
5. [Configuration](#configuration)
6. [Testing](#testing)
7. [Daily Schedule](#daily-schedule)
8. [News Monitoring](#news-monitoring)
9. [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### 1. Install

```bash
cd trading_bot
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
nano .env  # Add your API keys
```

Required API keys:
- `T212_API_KEY` - Trading212 API key
- `T212_API_SECRET` - Trading212 API secret
- `FMP_API_KEY` - Financial Modeling Prep (for earnings)
- `TELEGRAM_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

### 3. Test

```bash
# Test all connections
python main.py --test

# Test trade execution (IMPORTANT - do this first!)
python -m tests.test_trade_execution --status
python -m tests.test_trade_execution --symbol AAPL --amount 10

# Test all strategies
python -m tests.test_strategies --full

# Simulate weekend pipeline
python -m tests.test_weekend_simulation --verbose
```

### 4. Run

```bash
# Paper mode (default, safe)
python main.py

# Live mode (real money!)
python main.py --live
```

---

## 🧠 Core Principles

### 1. Single Source of Truth
Weekly universe from Trading212 is **immutable** during the week. No new tickers added after Sunday.

### 2. Analysis vs Execution Separation
- **Weekend (Sat/Sun)**: All analysis, scoring, candidate selection
- **Weekday (Mon-Fri)**: Only execute based on precomputed data

### 3. No Recomputation
During execution, the bot **never** recalculates historical analysis. It only validates live data against weekend results.

### 4. Explicit NO-TRADE
Skipping a trade is always valid. Every skip is logged with a reason.

### 5. Invalidation-Based Exits
Positions remain open unless an explicit exit rule triggers:
- Stop loss hit
- Target reached
- Max hold period
- News-based invalidation

---

## 📊 Strategies

### Overview

| Strategy | Check Time | Type | Hold Period | Max Positions |
|----------|------------|------|-------------|---------------|
| Earnings Momentum | After release | Event | 1-10 days | 10 |
| Sector Momentum | 9:00 AM | Swing | 1 week | 3 |
| Mean Reversion | 9:00 AM | Swing | 1-5 days | 5 |
| Breakout | 9:00 AM | Swing | Trailing stop | 5 |
| Gap Fade | 9:00 AM | Intraday | Same day | 3 |
| VWAP Reversion | 10:00 AM | Intraday | Same day | 3 |
| ORB | 10:00 AM | Intraday | Same day | 2 |

---

### 1. Earnings Momentum

**When**: After earnings release during earnings week

**Universe**: Stocks reporting earnings, filtered to Trading212 tradeable

**Entry**:
- Earnings released with surprise (beat/miss)
- Historical pattern supports direction
- Score >= 3

**Exit**:
- Stop loss: -8%
- Trailing stop: 5% from high
- Max hold: 10 days

**Scoring Components**:
| Component | Weight |
|-----------|--------|
| Gap behavior (fade/continuation) | 25% |
| Trend consistency | 20% |
| Analyst sensitivity | 20% |
| Volatility alignment | 15% |
| Sentiment bias | 20% |

---

### 2. Sector Momentum

**When**: 9:00 AM pre-market (weekly rebalance)

**Universe**: 11 Sector ETFs
```
XLK (Tech), XLV (Healthcare), XLF (Finance), XLY (Consumer Disc),
XLP (Consumer Staples), XLE (Energy), XLU (Utilities), XLB (Materials),
XLI (Industrials), XLRE (Real Estate), XLC (Communications)
```

**Entry**:
- Buy top 3 sectors by 1-month momentum
- Score >= 3

**Exit**:
- Sector falls to rank #6+
- Stop loss: -8%
- Weekly rebalance

**Scoring Components**:
| Component | Weight |
|-----------|--------|
| Momentum rank | 30% |
| SMA trend (20/50) | 25% |
| Relative strength vs SPY | 25% |
| Volume trend | 20% |

---

### 3. Mean Reversion

**When**: 9:00 AM pre-market

**Universe**: 100+ S&P 500 quality stocks (>$10B market cap)

**Entry**:
- RSI(2) < 10 (extremely oversold)
- Price above 200 SMA (uptrend)
- No earnings within 3 days
- Score >= 3

**Exit**:
- RSI(2) > 70 (target)
- Take profit: +5%
- Stop loss: -5%
- Max hold: 5 days

**Scoring Components**:
| Component | Weight |
|-----------|--------|
| RSI extremity | 30% |
| Trend strength | 25% |
| Drawdown depth | 25% |
| Volume spike | 20% |

---

### 4. Breakout

**When**: 9:00 AM pre-market

**Universe**: 60+ mid/large cap growth stocks

**Entry**:
- Price within 2% of 52-week high
- Volume > 1.5x average
- RSI > 50
- Score >= 3

**Exit**:
- Close below 20 SMA
- Trailing stop: 10% from high
- Initial stop: -5%
- Max hold: 30 days

**Scoring Components**:
| Component | Weight |
|-----------|--------|
| Proximity to high | 30% |
| Volume surge | 25% |
| RSI momentum | 25% |
| Sector strength | 20% |

---

### 5. Gap Fade

**When**: 9:00 AM pre-market

**Universe**: Large cap stocks + Sector ETFs

**Entry**:
- Gap down 3-10%
- Historical gap fill rate > 50%
- Score >= 3

**Exit**:
- Gap fills (50% target)
- End of day (forced exit)
- Stop loss: -3%

**Scoring Components**:
| Component | Weight |
|-----------|--------|
| Gap size | 30% |
| Historical fill rate | 25% |
| Volume | 25% |
| Market direction | 20% |

---

### 6. VWAP Reversion

**When**: 10:00 AM (after opening volatility)

**Universe**: High volume stocks (SPY, QQQ, mega caps)

**Entry**:
- Price 1.5-4% below VWAP
- Score >= 3

**Exit**:
- Price returns to VWAP
- Stop loss: -2%

---

### 7. Opening Range Breakout (ORB)

**When**: 10:00 AM (after 30-minute opening range)

**Universe**: Momentum stocks

**Entry**:
- Price breaks above 30-minute high
- Volume confirmation
- Score >= 3

**Exit**:
- Price falls below opening range low
- Stop loss: -1.5%

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    WEEKEND (Sat/Sun)                        │
│                   ANALYSIS TIME ONLY                        │
├─────────────────────────────────────────────────────────────┤
│  1. Universe Refresh (Trading212 API)                       │
│  2. Earnings Candidates (FMP API)                           │
│  3. Strategy Analysis (All 6 strategies)                    │
│  4. Score Computation (1-5 with components)                 │
│  5. Store Results (MongoDB + JSON backup)                   │
│  6. Telegram Notifications                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ DATA FROZEN
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    WEEKDAY (Mon-Fri)                        │
│                   EXECUTION TIME ONLY                       │
├─────────────────────────────────────────────────────────────┤
│  Priority 1: News Monitoring (continuous)                   │
│  Priority 2: Position Invalidation Checks                   │
│  Priority 3: Pre-market Scans (9:00 AM)                     │
│  Priority 4: Intraday Scans (10:00 AM)                      │
│  Priority 5: Earnings Execution                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Directory Structure

```
trading_bot/
├── main.py                    # Main orchestrator
├── config.py                  # All configuration
├── requirements.txt
├── .env.example
│
├── core/
│   ├── t212_client.py         # Trading212 API client
│   ├── market_data.py         # Safe yfinance wrapper
│   ├── telegram.py            # Telegram notifications
│   ├── storage.py             # MongoDB + JSON storage
│   └── news_monitor.py        # Real-time news monitoring
│
├── analysis/
│   ├── weekend_pipeline.py    # Weekend analysis
│   └── earnings_executor.py   # Earnings execution
│
├── strategies/
│   ├── base_strategy.py       # Strategy interface
│   ├── sector_momentum.py     # Sector rotation
│   ├── mean_reversion.py      # RSI oversold
│   ├── breakout.py            # 52-week highs
│   ├── intraday.py            # Gap, VWAP, ORB
│   └── manager.py             # Strategy orchestrator
│
├── tests/
│   ├── test_runner.py         # Full test suite
│   ├── test_strategies.py     # Strategy tests
│   ├── test_trade_execution.py # Order placement test
│   ├── test_weekend_simulation.py
│   └── test_execution_simulation.py
│
├── data/                      # JSON data files
└── logs/                      # Daily logs
```

---

## ⚙️ Configuration

All settings in `config.py`:

### Risk Management

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_POSITIONS` | 10 | Maximum concurrent positions |
| `MAX_POSITION_PCT` | 10% | Max position size (% of cash) |
| `MAX_DAILY_LOSS_PCT` | 3% | Daily loss limit |

### Position Sizing by Score

| Score | Multiplier | Meaning |
|-------|------------|---------|
| 5 | 100% | Strong conviction |
| 4 | 75% | High confidence |
| 3 | 50% | Moderate confidence |
| 2 | 25% | Low confidence |
| 1 | 0% | Observe only |

### NO-TRADE Rules

| Rule | Threshold |
|------|-----------|
| Min average volume | 500,000 |
| Max pre-market gap | 15% |
| Min market cap | $500M |

### Invalidation Rules

| Rule | Threshold |
|------|-----------|
| Max loss (stop) | -8% |
| Trailing stop | 5% from high |
| Max hold | 10 days |

---

## 🧪 Testing

### 1. Full Test Suite

```bash
python main.py --test
```

Tests all API connections, storage, and configuration.

### 2. Trade Execution Test ⚠️ IMPORTANT

```bash
# Check account status
python -m tests.test_trade_execution --status

# Test actual order (uses $10 by default)
python -m tests.test_trade_execution --symbol AAPL --amount 10
```

This test will:
1. Connect to Trading212
2. Buy a small position
3. Verify position exists
4. Sell the position
5. Verify closed

**Run this before going live to ensure orders work!**

### 3. Strategy Tests

```bash
# All strategies
python -m tests.test_strategies --full

# Specific strategy
python -m tests.test_strategies --strategy sector_momentum
python -m tests.test_strategies --strategy mean_reversion
python -m tests.test_strategies --strategy breakout
```

### 4. Weekend Simulation

```bash
python -m tests.test_weekend_simulation --verbose
```

Simulates exactly what will run on Saturday.

### 5. News Monitor Test

```bash
python -c "
from core.news_monitor import NewsMonitor
m = NewsMonitor()
news = m.check_news('AAPL')
for n in news[:3]:
    print(f'{n.impact.value}: {n.headline[:60]}')
"
```

---

## 📅 Daily Schedule (Eastern Time)

### Weekend (Saturday/Sunday)

| Time | Action |
|------|--------|
| Saturday 10:00 AM | Universe refresh from Trading212 |
| Saturday 11:00 AM | Fetch earnings calendar |
| Sunday All Day | Historical analysis for all strategies |
| Sunday Evening | Telegram: Weekly analysis summary |
| **Sunday Night** | **DATA FROZEN FOR THE WEEK** |

### Weekday (Monday-Friday)

| Time | Action |
|------|--------|
| 9:00 AM | Pre-market scans (Sector, Mean Rev, Breakout, Gap) |
| 9:30 AM | Market open |
| 9:30 AM+ | News monitoring starts |
| 10:00 AM | Intraday scans (VWAP, ORB) |
| All Day | Position invalidation checks |
| All Day | Earnings event handling |
| 3:45 PM | Intraday positions closed |
| 4:00 PM | Market close |
| 4:05 PM | Daily summary via Telegram |

---

## 📰 News Monitoring

The bot monitors news in real-time during market hours.

### Classification

**Positive Keywords**:
```
beats, exceeds, raises, upgraded, buy, approval, wins, surge, breakthrough
```

**Negative Keywords**:
```
misses, disappoints, lowers, downgraded, sell, rejection, lawsuit, plunges
```

**Material Keywords**:
```
earnings, revenue, guidance, fda, sec, ceo, merger, acquisition, bankruptcy
```

### Alerts

When material news affects an open position:

```
⚠️ NEWS ALERT: AAPL
━━━━━━━━━━━━━━━━━━━━
Apple reports Q1 earnings miss, guides lower
Action: Review position immediately
```

---

## 📱 Telegram Notifications

| Alert | Emoji | When |
|-------|-------|------|
| Universe Updated | 📊 | Saturday |
| Earnings Candidates | 📅 | Sat/Sun |
| Analysis Complete | 🔬 | Sunday |
| Strategy Signals | 📊 | Daily scans |
| Trade Entry | 🟢 | Buy executed |
| Trade Exit | 🔴 | Sell executed |
| Trade Skipped | ⏭️ | NO-TRADE condition |
| News Alert | ⚠️ | Material news |
| Daily Summary | 📈/📉 | Market close |
| Error | ⚠️ | On errors |

---

## 🔧 Troubleshooting

### "Connection failed to Trading212"

1. Check `T212_API_KEY` and `T212_API_SECRET` in `.env`
2. Verify keys are for correct account type (Invest, not CFD)
3. Check if using paper or live keys correctly

### "No earnings candidates found"

1. Check `FMP_API_KEY` is set
2. FMP free tier has 250 calls/day limit
3. May be no earnings next week

### "Symbol not tradeable"

1. Symbol may not be available on Trading212
2. Run: `python -m tests.test_trade_execution --status`
3. Check the symbol list in T212 app

### "Order failed"

1. Check available cash in account
2. Market may be closed
3. Symbol may have trading restrictions
4. Run trade execution test first

### "News monitor not working"

1. Check internet connection
2. yfinance may be rate-limited
3. FMP API may be down

### "Telegram not sending"

1. Verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`
2. Start a chat with your bot first
3. Check bot has permission to send messages

---

## 📄 Files Created

### Weekly Files (in `data/`)

| File | Description |
|------|-------------|
| `universe_YYYY-WXX.json` | Weekly T212 universe |
| `earnings_YYYY-WXX.json` | Earnings candidates |
| `analysis_YYYY-WXX.json` | Earnings analysis |
| `sector_momentum_YYYY-WXX.json` | Sector analysis |
| `mean_reversion_YYYY-WXX.json` | Mean rev screening |
| `breakout_YYYY-WXX.json` | Breakout watchlist |
| `gap_fade_YYYY-WXX.json` | Gap history |

### Daily Files

| File | Description |
|------|-------------|
| `trades_YYYY-MM-DD.json` | Trade log |
| `strategy_positions.json` | Current positions |
| `logs/bot_YYYYMMDD.log` | Daily log |

---

## ⚠️ Disclaimer

This software is for educational purposes only. Trading involves substantial risk of loss. Past performance does not guarantee future results. Always test thoroughly with paper trading before using real money.

---

## 📜 License

MIT License - Use at your own risk.
