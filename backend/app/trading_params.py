"""
Persistent trading parameters: rules, boundaries, and symbols.
Stored in data/trading_params.json so the UI can read/update without code changes.
"""
import json
from pathlib import Path

from app.config import settings

PARAMS_FILE = Path(__file__).resolve().parent.parent / "data" / "trading_params.json"

DEFAULTS = {
    "min_price_drop_pct": -1.5,
    "min_price_rise_pct": 1.0,
    "position_pct_of_balance": 0.15,
    "min_trade_usd": 50.0,
    "max_trade_pct_of_balance": 20.0,
    "max_position_pct_per_coin": 25.0,
    "cooldown_minutes": 0,
    "enabled_symbols": [],  # empty = use config symbols
}


def _ensure_dir():
    PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_params() -> dict:
    _ensure_dir()
    if not PARAMS_FILE.exists():
        return DEFAULTS.copy()
    try:
        with open(PARAMS_FILE, "r") as f:
            data = json.load(f)
        out = DEFAULTS.copy()
        for k, v in data.items():
            if k in out:
                out[k] = v
        return out
    except Exception:
        return DEFAULTS.copy()


def save_params(params: dict) -> None:
    _ensure_dir()
    current = load_params()
    for k, v in params.items():
        if k in current:
            current[k] = v
    with open(PARAMS_FILE, "w") as f:
        json.dump(current, f, indent=2)


def get_enabled_symbols() -> list[str]:
    p = load_params()
    syms = p.get("enabled_symbols") or []
    return syms if syms else list(settings.symbols)
