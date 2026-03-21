"""
Paper trading engine: virtual balance, positions, and order execution per generation.
State is persisted per gen in data/paper_state_gen{N}.json.
Applies configurable fees, slippage, and risk limits from lab_settings.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from app.models import OrderSide, Position, Trade

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _state_file(gen_id: str) -> Path:
    return DATA_DIR / f"paper_state_gen{gen_id}.json"


def _default_state(initial_balance: float, gen_id: str) -> dict:
    return {
        "gen_id": gen_id,
        "balance_usd": initial_balance,
        "positions": {},
        "trades": [],
        "decisions": [],
        "entry_count_per_symbol": {},
        "created_at": datetime.utcnow().isoformat(),
    }


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_state(gen_id: str, initial_balance: float) -> dict:
    _ensure_dir()
    path = _state_file(gen_id)
    if not path.exists():
        return _default_state(initial_balance, gen_id)
    try:
        with open(path, "r") as f:
            state = json.load(f)
        state.setdefault("entry_count_per_symbol", {})
        state.setdefault("decisions", [])
        state.setdefault("gen4_decision_history", [])
        return state
    except Exception:
        return _default_state(initial_balance, gen_id)


def save_state(gen_id: str, state: dict) -> None:
    _ensure_dir()
    with open(_state_file(gen_id), "w") as f:
        json.dump(state, f, indent=2)


def reset_gen(gen_id: str, initial_balance: float) -> dict:
    """Reset this generation to a fresh balance and no positions. Returns new state."""
    state = _default_state(initial_balance, gen_id)
    save_state(gen_id, state)
    return state


def get_positions(state: dict, prices: dict[str, float]) -> list[Position]:
    out = []
    for symbol, pos in state["positions"].items():
        qty = pos["quantity"]
        avg = pos["avg_price"]
        current = prices.get(symbol, avg)
        value = qty * current
        cost = qty * avg
        pnl_usd = value - cost
        pnl_pct = (pnl_usd / cost * 100) if cost else 0
        out.append(
            Position(
                symbol=symbol,
                quantity=qty,
                avg_price=avg,
                current_price=current,
                value_usd=value,
                pnl_usd=pnl_usd,
                pnl_percent=pnl_pct,
            )
        )
    return out


def _apply_slippage(price: float, side: OrderSide, slippage_pct: float) -> float:
    mult = 1 + (slippage_pct / 100.0)
    if side == OrderSide.BUY:
        return price * mult
    return price / mult


def _apply_fee(total_usd: float, fee_pct: float) -> float:
    return total_usd * (fee_pct / 100.0)


def _total_exposure_usd(state: dict, prices: dict[str, float]) -> float:
    total = 0.0
    for sym, pos in state["positions"].items():
        total += pos["quantity"] * prices.get(sym, pos["avg_price"])
    return total


def execute_order(
    state: dict,
    gen_id: str,
    symbol: str,
    side: OrderSide,
    quantity: float,
    price: float,
    reason: str,
    config: dict,
    world_signal: str | None = None,
) -> Trade | None:
    """
    Execute a paper order for the given gen. Applies slippage and fees from config.
    Enforces: max_open_positions, max_total_exposure_pct, max_exposure_per_coin_pct,
    max_entries_per_coin (for buys). Returns Trade if filled, else None.
    """
    slippage_pct = config.get("slippage_pct", 0.1)
    fee_pct = config.get("trading_fee_pct", 0.1)
    max_open = config.get("max_open_positions", 5)
    max_total_exposure_pct = config.get("max_total_exposure_pct", 80.0) / 100.0
    max_coin_pct = config.get("max_exposure_per_coin_pct", 25.0) / 100.0
    max_entries = config.get("max_entries_per_coin", 3)

    fill_price = _apply_slippage(price, side, slippage_pct)
    total_usd = quantity * fill_price
    fee = _apply_fee(total_usd, fee_pct)
    balance = state["balance_usd"]
    positions = state["positions"]
    entry_count = state.setdefault("entry_count_per_symbol", {})

    if side == OrderSide.BUY:
        if total_usd + fee > balance:
            return None
        if len(positions) >= max_open and symbol not in positions:
            return None
        current_exposure = sum(
            positions.get(s, {}).get("quantity", 0) * positions.get(s, {}).get("avg_price", 0)
            for s in positions
        )
        equity_before = balance + current_exposure
        exposure_after = current_exposure + total_usd
        if equity_before > 0 and exposure_after / equity_before > max_total_exposure_pct:
            return None
        pos_value_after = (positions.get(symbol, {}).get("quantity", 0) + quantity) * fill_price
        equity_after = balance - total_usd - fee + current_exposure + total_usd
        if equity_after > 0 and pos_value_after / equity_after > max_coin_pct:
            return None
        if entry_count.get(symbol, 0) >= max_entries:
            return None

        state["balance_usd"] -= total_usd + fee
        if symbol not in positions:
            positions[symbol] = {"quantity": 0.0, "avg_price": 0.0}
        p = positions[symbol]
        p["quantity"] += quantity
        p["avg_price"] = (
            (p["avg_price"] * (p["quantity"] - quantity) + total_usd
        ) / p["quantity"] if p["quantity"] else fill_price
        )
        entry_count[symbol] = entry_count.get(symbol, 0) + 1
    else:
        pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
        if pos["quantity"] < quantity:
            return None
        state["balance_usd"] += total_usd - fee
        pos["quantity"] -= quantity
        if pos["quantity"] <= 0:
            del positions[symbol]
            entry_count.pop(symbol, None)

    trade = Trade(
        id=str(uuid.uuid4()),
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=fill_price,
        total_usd=total_usd,
        reason=reason,
        timestamp=datetime.utcnow(),
        world_signal=world_signal,
    )
    state["trades"].append(trade.model_dump(mode="json"))
    return trade
