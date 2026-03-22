"""
Strategy lab settings: one source of truth for paper trading defaults,
per-generation overrides, and API keys. Stored in data/lab_settings.json.
All values are configurable from the Settings UI; nothing hardcoded for strategy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "lab_settings.json"

# Defaults for the whole lab (can be overridden per generation)
GLOBAL_DEFAULTS = {
    "starting_balance": 10_000.0,
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "position_size_pct": 10.0,
    "max_exposure_per_coin_pct": 25.0,
    "max_total_exposure_pct": 80.0,
    "max_open_positions": 5,
    "cooldown_minutes": 5.0,
    "max_entries_per_coin": 3,
    "take_profit_pct": 1.0,
    "stop_loss_pct": -3.0,
    "slippage_pct": 0.1,
    "trading_fee_pct": 0.1,
    "price_update_interval_seconds": 90,
    "logging_level": "basic",
    "shared_wallet": False,
    # Strategy thresholds (used by Gen 1–3; Gen 4 uses AI)
    "min_price_drop_pct": -1.5,
    "min_price_rise_pct": 1.0,
    "min_trade_usd": 50.0,
    "max_trade_pct_of_balance": 20.0,
}

# Per-generation defaults (overrides on top of global)
GEN_DEFAULTS = {
    "1": {"enabled": True, "label": "Baseline Bot", "overrides": {}},
    "2": {"enabled": True, "label": "Optimized Bot", "overrides": {"position_size_pct": 8.0, "cooldown_minutes": 10.0, "max_entries_per_coin": 2}},
    "3": {"enabled": True, "label": "Adaptive Bot", "overrides": {"position_size_pct": 7.0, "cooldown_minutes": 15.0}},
    "4": {"enabled": True, "label": "AI Supervisor Bot", "overrides": {"position_size_pct": 5.0, "cooldown_minutes": 30.0}},
    "5": {
        "enabled": True,
        "label": "Aggressive Scalper Bot",
        "overrides": {
            "position_size_pct": 3.0,
            "cooldown_minutes": 5.0,
            "max_open_positions": 4,
            "max_exposure_per_coin_pct": 12.0,
            "max_total_exposure_pct": 50.0,
            "take_profit_pct": 0.4,
            "stop_loss_pct": -0.6,
            "min_price_drop_pct": -0.5,
            "min_price_rise_pct": 0.3,
            "max_trade_pct_of_balance": 8.0,
            "min_trade_usd": 25.0,
            "max_trades_per_day": 30,
        },
    },
    "6": {
        "enabled": True,
        "label": "Momentum Rider Bot",
        "overrides": {
            "position_size_pct": 5.0,
            "cooldown_minutes": 8.0,
            "max_open_positions": 4,
            "max_exposure_per_coin_pct": 18.0,
            "max_total_exposure_pct": 65.0,
            "min_price_drop_pct": -1.08,
            "min_trade_usd": 40.0,
            "max_trade_pct_of_balance": 12.0,
            "stop_loss_pct": -1.12,
            "max_trades_per_day": 40,
            "cooldown_minutes": 7.0,
            "gen6_protect_profit_pct": 0.42,
            "gen6_protect_min_cycles": 2,
            "gen6_protect_instant_pct": 0.58,
            "gen6_runner_activation_pct": 0.52,
            "gen6_runner_weak_regime_add": 0.12,
            "gen6_scaleout_pct": 0.78,
            "gen6_scaleout_fraction": 0.28,
            "gen6_trail_tight_pct": 0.40,
            "gen6_trail_runner_weak_pct": 0.42,
            "gen6_trail_runner_normal_pct": 0.62,
            "gen6_trail_runner_strong_pct": 0.82,
            "gen6_max_hold_cycles": 46,
            "gen6_stall_cycles": 11,
            "gen6_runner_momentum_min_24h": -0.28,
            "gen6_catastrophic_entry_cutoff_pct": -10.5,
            "gen6_stall_epsilon_pct": 0.055,
            "gen6_runner_hard_hold_extra_cycles": 40,
            "gen6_entry_confirm_bounce_pct": 0.032,
            "gen6_entry_max_cycle_bleed_pct": -0.072,
            "gen6_entry_stabilize_cycle_floor_pct": -0.022,
            "gen6_entry_stabilize_24h_epsilon": 0.11,
            "gen6_entry_deep_dip_threshold_pct": -2.8,
            "gen6_entry_deep_dip_extra_bounce_pct": 0.018,
        },
    },
    "7": {
        "enabled": True,
        "label": "Active Micro-Movement Trader",
        "overrides": {
            "position_size_pct": 2.5,
            "cooldown_minutes": 3.0,
            "max_open_positions": 5,
            "max_exposure_per_coin_pct": 10.0,
            "max_total_exposure_pct": 48.0,
            "min_trade_usd": 22.0,
            "max_trade_pct_of_balance": 7.0,
            "max_trades_per_day": 48,
            "gen7_take_profit_pct": 0.22,
            "gen7_stop_loss_pct": -0.36,
            "gen7_max_hold_cycles": 9,
            "gen7_max_hold_hard_cycles": 14,
            "gen7_stall_cycles": 4,
            "gen7_stall_epsilon_pct": 0.05,
            "gen7_timeout_min_progress_pct": 0.06,
            "gen7_micro_lock_profit_pct": 0.14,
            "gen7_micro_lock_stall_cycles": 2,
            "gen7_fade_from_peak_pct": 0.09,
            "gen7_fade_min_peak_pct": 0.10,
            "gen7_min_price_drop_pct": -0.38,
            "gen7_max_entry_change_24h_pct": 0.42,
            "gen7_catastrophic_entry_cutoff_pct": -9.0,
            "gen7_rs_vs_avg_buffer_pct": 2.8,
            "gen7_cycle_burst_min_pct": 0.035,
            "gen7_continuation_max_24h_pct": 0.38,
        },
    },
}

API_KEYS_DEFAULTS = {
    "openai_api_key": "",
    "news_api_key": "",
    "cryptopanic_api_key": "",
    "coingecko_api_key": "",
}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict:
    _ensure_dir()
    if not SETTINGS_FILE.exists():
        return {
            "global_defaults": GLOBAL_DEFAULTS.copy(),
            "generations": GEN_DEFAULTS.copy(),
            "api_keys": API_KEYS_DEFAULTS.copy(),
        }
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        out = {
            "global_defaults": {**GLOBAL_DEFAULTS, **(data.get("global_defaults") or {})},
            "generations": data.get("generations") or GEN_DEFAULTS.copy(),
            "api_keys": {**API_KEYS_DEFAULTS, **(data.get("api_keys") or {})},
        }
        for g in "1", "2", "3", "4", "5", "6", "7":
            if g not in out["generations"]:
                out["generations"][g] = GEN_DEFAULTS.get(g, {"enabled": True, "label": f"Gen {g}", "overrides": {}})
        return out
    except Exception:
        return {
            "global_defaults": GLOBAL_DEFAULTS.copy(),
            "generations": GEN_DEFAULTS.copy(),
            "api_keys": API_KEYS_DEFAULTS.copy(),
        }


def _save_raw(data: dict) -> None:
    _ensure_dir()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_global_defaults() -> dict:
    return _load_raw()["global_defaults"].copy()


def get_gen_config(gen_id: str) -> dict:
    """Merged config for one generation: global_defaults + gen overrides."""
    raw = _load_raw()
    global_d = raw["global_defaults"]
    gen_d = raw["generations"].get(gen_id, {"enabled": True, "label": f"Gen {gen_id}", "overrides": {}})
    overrides = gen_d.get("overrides") or {}
    merged = {**global_d, **overrides}
    merged["enabled"] = gen_d.get("enabled", True)
    merged["label"] = gen_d.get("label", f"Gen {gen_id}")
    merged["gen_id"] = gen_id
    return merged


def get_all_gen_configs() -> dict[str, dict]:
    return {g: get_gen_config(g) for g in ("1", "2", "3", "4", "5", "6", "7")}


def get_api_keys() -> dict[str, str]:
    return _load_raw()["api_keys"].copy()


def get_api_keys_masked() -> dict[str, str]:
    """Same as get_api_keys but values replaced with '***' if non-empty (for UI)."""
    keys = get_api_keys()
    return {k: ("***" if (v and len(v) > 4) else (v or "")) for k, v in keys.items()}


def get_price_update_interval_seconds() -> int:
    return int(get_global_defaults().get("price_update_interval_seconds", 90))


def get_symbols_for_gen(gen_id: str) -> list[str]:
    cfg = get_gen_config(gen_id)
    syms = cfg.get("symbols") or []
    return syms if syms else ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def get_starting_balance_for_gen(gen_id: str) -> float:
    cfg = get_gen_config(gen_id)
    return float(cfg.get("starting_balance", 10_000.0))


def update_settings(global_defaults: dict | None = None, generations: dict | None = None, api_keys: dict | None = None) -> None:
    """Update and persist. Pass only the sections you want to update."""
    raw = _load_raw()
    if global_defaults is not None:
        raw["global_defaults"] = {**raw["global_defaults"], **global_defaults}
    if generations is not None:
        for g, v in generations.items():
            if g in raw["generations"]:
                raw["generations"][g] = {**raw["generations"][g], **v}
            else:
                raw["generations"][g] = v
    if api_keys is not None:
        for k, v in api_keys.items():
            if k in raw["api_keys"] and v != "***":
                raw["api_keys"][k] = v
    _save_raw(raw)


def update_api_keys(keys: dict[str, str]) -> None:
    """Update only API keys; skip masked values."""
    raw = _load_raw()
    for k, v in (keys or {}).items():
        if k in raw["api_keys"] and v and v != "***":
            raw["api_keys"][k] = v
    _save_raw(raw)


def get_settings_for_api() -> dict:
    """Full settings dict for GET /api/lab/settings (api_keys masked)."""
    raw = _load_raw()
    return {
        "global_defaults": raw["global_defaults"].copy(),
        "generations": {k: v.copy() for k, v in raw["generations"].items()},
        "api_keys": get_api_keys_masked(),
    }
