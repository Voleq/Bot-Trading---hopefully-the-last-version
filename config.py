"""
config.py - Central Configuration

All settings in one place. No magic numbers scattered throughout the code.
"""

import os
from pathlib import Path
from datetime import time
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ============================================================
# API CREDENTIALS
# ============================================================
T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_API_SECRET = os.getenv("T212_API_SECRET", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MONGO_URI = os.getenv("MONGO_URI", "")

# ============================================================
# TRADING MODE
# ============================================================
PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"

# ============================================================
# MARKET HOURS (US Eastern Time)
# ============================================================
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PRE_MARKET_START = time(4, 0)

# ============================================================
# SCHEDULE
# ============================================================
# Analysis runs on weekends only
UNIVERSE_REFRESH_DAY = 5  # Saturday = 5
ANALYSIS_DAYS = [5, 6]    # Saturday, Sunday
EXECUTION_DAYS = [0, 1, 2, 3, 4]  # Monday-Friday

# Check intervals (seconds)
MARKET_CHECK_INTERVAL = 60      # During market hours
OFF_MARKET_CHECK_INTERVAL = 300  # Outside market hours

# ============================================================
# EARNINGS ANALYSIS
# ============================================================
EARNINGS_ENABLED = os.getenv("EARNINGS_ENABLED", "true").lower() == "true"
MIN_EARNINGS_GAP_PCT = 5.0      # Minimum gap to analyze
EARNINGS_TRACKING_DAYS = 10      # Days to track after earnings
MIN_HISTORICAL_QUARTERS = 4      # Minimum quarters for analysis

# ============================================================
# SCORING WEIGHTS (Explainable Scoring)
# ============================================================
SCORE_WEIGHTS = {
    "gap_behavior": 0.25,        # Historical gap fade vs continuation
    "trend_consistency": 0.20,   # Pattern consistency
    "analyst_sensitivity": 0.20, # Reaction to beats/misses
    "volatility_alignment": 0.15,# Current vs historical volatility
    "sentiment_bias": 0.20       # News sentiment
}

# ============================================================
# NO-TRADE CONDITIONS
# ============================================================
NO_TRADE_RULES = {
    "min_avg_volume": 500_000,
    "max_premarket_gap_pct": 15.0,
    "min_market_cap": 500_000_000,
    "max_conflicting_signals": 2,
}

# ============================================================
# RISK MANAGEMENT
# ============================================================
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "10"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))

# Position sizing by confidence score (1-5)
POSITION_SIZE_BY_SCORE = {
    5: 1.0,   # Full size
    4: 0.75,
    3: 0.50,
    2: 0.25,
    1: 0.0,   # Observation only
}

# ============================================================
# INVALIDATION RULES (Exit Triggers)
# ============================================================
INVALIDATION_RULES = {
    "max_loss_pct": -8.0,
    "trailing_stop_pct": 5.0,
    "max_hold_days": 10,
    "sentiment_reversal_threshold": -0.5,
}

# ============================================================
# CONFIDENCE THROTTLING
# ============================================================
CONFIDENCE_THROTTLE = {
    "min_win_rate": 0.50,
    "high_vix_threshold": 30,
    "lookback_trades": 10,
}

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
