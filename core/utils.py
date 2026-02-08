"""
core/utils.py - Shared Utilities

- NumpySafeEncoder: JSON encoder that handles numpy/pandas types
- sanitize_for_json(): recursively convert numpy types to Python natives
- safe_json_dump(): drop-in replacement for json.dump with numpy safety
"""

import json
import logging
from typing import Any
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)


class NumpySafeEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy/pandas types."""
    
    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.bool_,)):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        
        try:
            import pandas as pd
            if isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            if isinstance(obj, pd.Series):
                return obj.tolist()
            if pd.isna(obj):
                return None
        except (ImportError, TypeError, ValueError):
            pass
        
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, set):
            return list(obj)
        
        return super().default(obj)


def sanitize_for_json(obj: Any) -> Any:
    """Recursively convert numpy/pandas types to Python natives."""
    try:
        import numpy as np
        
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            if np.isnan(v) or np.isinf(v):
                return None
            return v
        if isinstance(obj, np.ndarray):
            return [sanitize_for_json(x) for x in obj.tolist()]
    except ImportError:
        pass
    
    try:
        import pandas as pd
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        if pd.isna(obj):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, float):
        if obj != obj or obj == float('inf') or obj == float('-inf'):
            return None
    
    return obj


def safe_json_dump(data: Any, filepath, **kwargs):
    """
    Drop-in replacement for json.dump that handles numpy types.
    
    Usage:
        from core.utils import safe_json_dump
        safe_json_dump(data, filepath)        # writes to file path
        safe_json_dump(data, file_handle)     # writes to open file
    """
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("cls", NumpySafeEncoder)
    kwargs.setdefault("default", str)
    
    clean = sanitize_for_json(data)
    
    if isinstance(filepath, (str, Path)):
        with open(filepath, 'w') as f:
            json.dump(clean, f, **kwargs)
    else:
        # It's a file handle
        json.dump(clean, filepath, **kwargs)


def safe_json_dumps(data: Any, **kwargs) -> str:
    """Drop-in replacement for json.dumps that handles numpy types."""
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("cls", NumpySafeEncoder)
    kwargs.setdefault("default", str)
    
    clean = sanitize_for_json(data)
    return json.dumps(clean, **kwargs)
