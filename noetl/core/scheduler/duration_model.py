import json
import os
from typing import Dict

# Very simple duration estimator with static defaults and optional JSON cache override

_DEFAULTS_MS: Dict[str, int] = {
    "http": 1200,
    "postgres": 800,
    "duckdb": 8000,
    "iterator": 0,
}

_CACHE_PATH = os.environ.get("NOETL_DURATION_CACHE", os.path.join(os.path.dirname(__file__), "duration_cache.json"))

_cache: Dict[str, int] = {}


def _load_cache():
    global _cache
    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # keys can be either step_id or step_type
                    _cache = {str(k): int(v) for k, v in data.items()}
        except Exception:
            # ignore cache errors
            _cache = {}


_load_cache()


def estimate_duration_ms(step_id: str, step_type: str) -> int:
    # Prefer explicit step_id overrides, then type, then defaults
    if step_id in _cache:
        return int(_cache[step_id])
    if step_type in _cache:
        return int(_cache[step_type])
    return int(_DEFAULTS_MS.get(step_type, 1000))
