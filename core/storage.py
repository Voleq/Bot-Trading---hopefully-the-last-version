"""
core/storage.py - Data Storage Manager

Handles:
- Weekly universe snapshots (MongoDB)
- Earnings candidates (JSON for lightweight)
- Analysis results
- Trade logs

Principle: MongoDB for versioned weekly data, JSON for ephemeral data.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import config

logger = logging.getLogger(__name__)

# MongoDB (optional)
try:
    from pymongo import MongoClient
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    logger.info("pymongo not installed, using file storage only")


def get_week_id(date: datetime = None) -> str:
    """Get week identifier (e.g., '2026-W05')."""
    date = date or datetime.now()
    return date.strftime("%Y-W%W")


def get_week_start(date: datetime = None) -> datetime:
    """Get Monday of the current week."""
    date = date or datetime.now()
    days_since_monday = date.weekday()
    return date - timedelta(days=days_since_monday)


class Storage:
    """
    Data storage manager.
    
    Uses MongoDB for weekly snapshots, JSON files for lightweight data.
    """
    
    def __init__(self):
        self.data_dir = config.DATA_DIR
        self.mongo_client = None
        self.db = None
        
        # Connect MongoDB if available
        if MONGO_AVAILABLE and config.MONGO_URI:
            try:
                self.mongo_client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
                self.mongo_client.admin.command('ping')
                self.db = self.mongo_client.trading_bot
                logger.info("✓ MongoDB connected")
            except Exception as e:
                logger.warning(f"MongoDB connection failed: {e}")
                self.mongo_client = None
    
    # ==================== WEEKLY UNIVERSE ====================
    
    def save_universe(self, instruments: List[Dict], week_id: str = None) -> bool:
        """
        Save weekly universe snapshot.
        
        This is the SINGLE SOURCE OF TRUTH for the week.
        Stored in MongoDB with version.
        """
        week_id = week_id or get_week_id()
        
        data = {
            "week_id": week_id,
            "created_at": datetime.now().isoformat(),
            "count": len(instruments),
            "instruments": instruments
        }
        
        # Save to MongoDB
        if self.db:
            try:
                self.db.universe.replace_one(
                    {"week_id": week_id},
                    data,
                    upsert=True
                )
                logger.info(f"Universe saved to MongoDB: {week_id} ({len(instruments)} instruments)")
            except Exception as e:
                logger.error(f"MongoDB save failed: {e}")
        
        # Also save to JSON as backup
        filepath = self.data_dir / f"universe_{week_id}.json"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return True
    
    def get_universe(self, week_id: str = None) -> Optional[Dict]:
        """Get universe for a specific week."""
        week_id = week_id or get_week_id()
        
        # Try MongoDB first
        if self.db:
            try:
                data = self.db.universe.find_one({"week_id": week_id})
                if data:
                    data.pop('_id', None)
                    return data
            except Exception as e:
                logger.error(f"MongoDB read failed: {e}")
        
        # Fall back to JSON
        filepath = self.data_dir / f"universe_{week_id}.json"
        if filepath.exists():
            with open(filepath) as f:
                return json.load(f)
        
        return None
    
    def get_universe_symbols(self, week_id: str = None) -> List[str]:
        """Get list of symbols from universe."""
        data = self.get_universe(week_id)
        if not data:
            return []
        
        return [inst.get("symbol", "") for inst in data.get("instruments", [])]
    
    def is_in_universe(self, symbol: str, week_id: str = None) -> bool:
        """Check if symbol is in current universe."""
        symbols = self.get_universe_symbols(week_id)
        return symbol.upper() in [s.upper() for s in symbols]
    
    # ==================== EARNINGS CANDIDATES ====================
    
    def save_earnings_candidates(self, candidates: List[Dict], week_id: str = None) -> bool:
        """
        Save earnings candidates for the week.
        
        Stored as JSON (lightweight, no need for MongoDB).
        """
        week_id = week_id or get_week_id()
        
        data = {
            "week_id": week_id,
            "created_at": datetime.now().isoformat(),
            "count": len(candidates),
            "candidates": candidates
        }
        
        filepath = self.data_dir / f"earnings_{week_id}.json"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Earnings candidates saved: {week_id} ({len(candidates)})")
        return True
    
    def get_earnings_candidates(self, week_id: str = None) -> List[Dict]:
        """Get earnings candidates for the week."""
        week_id = week_id or get_week_id()
        
        filepath = self.data_dir / f"earnings_{week_id}.json"
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("candidates", [])
        
        return []
    
    # ==================== ANALYSIS RESULTS ====================
    
    def save_analysis_results(self, results: List[Dict], week_id: str = None) -> bool:
        """
        Save analysis results for earnings candidates.
        
        This is the precomputed data used during execution.
        """
        week_id = week_id or get_week_id()
        
        data = {
            "week_id": week_id,
            "created_at": datetime.now().isoformat(),
            "count": len(results),
            "results": results
        }
        
        # Save to MongoDB for persistence
        if self.db:
            try:
                self.db.analysis.replace_one(
                    {"week_id": week_id},
                    data,
                    upsert=True
                )
            except Exception as e:
                logger.error(f"MongoDB save failed: {e}")
        
        # Also save to JSON
        filepath = self.data_dir / f"analysis_{week_id}.json"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Analysis results saved: {week_id} ({len(results)})")
        return True
    
    def get_analysis_results(self, week_id: str = None) -> List[Dict]:
        """Get analysis results for the week."""
        week_id = week_id or get_week_id()
        
        # Try MongoDB first
        if self.db:
            try:
                data = self.db.analysis.find_one({"week_id": week_id})
                if data:
                    return data.get("results", [])
            except:
                pass
        
        # Fall back to JSON
        filepath = self.data_dir / f"analysis_{week_id}.json"
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("results", [])
        
        return []
    
    def get_analysis_for_symbol(self, symbol: str, week_id: str = None) -> Optional[Dict]:
        """Get precomputed analysis for a specific symbol."""
        results = self.get_analysis_results(week_id)
        for r in results:
            if r.get("symbol", "").upper() == symbol.upper():
                return r
        return None
    
    # ==================== TRADES ====================
    
    def log_trade(self, trade: Dict) -> bool:
        """Log a trade."""
        trade["timestamp"] = datetime.now().isoformat()
        
        # Append to daily log file
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / f"trades_{today}.json"
        
        trades = []
        if filepath.exists():
            with open(filepath) as f:
                trades = json.load(f)
        
        trades.append(trade)
        
        with open(filepath, 'w') as f:
            json.dump(trades, f, indent=2)
        
        # Also save to MongoDB
        if self.db:
            try:
                self.db.trades.insert_one(trade.copy())
            except:
                pass
        
        return True
    
    def get_trades(self, date: str = None) -> List[Dict]:
        """Get trades for a specific date."""
        date = date or datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / f"trades_{date}.json"
        
        if filepath.exists():
            with open(filepath) as f:
                return json.load(f)
        return []
    
    # ==================== POSITIONS ====================
    
    def save_tracked_positions(self, positions: Dict) -> bool:
        """Save tracked positions with metadata."""
        filepath = self.data_dir / "positions.json"
        
        data = {
            "updated_at": datetime.now().isoformat(),
            "positions": positions
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return True
    
    def get_tracked_positions(self) -> Dict:
        """Get tracked positions."""
        filepath = self.data_dir / "positions.json"
        
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
                return data.get("positions", {})
        return {}
    
    # ==================== EXECUTION LOGS ====================
    
    def log_execution(self, event: str, details: Dict):
        """Log execution event for audit."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "details": details
        }
        
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = self.data_dir / f"execution_log_{today}.json"
        
        logs = []
        if filepath.exists():
            with open(filepath) as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        with open(filepath, 'w') as f:
            json.dump(logs, f, indent=2)
