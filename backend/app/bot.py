"""
Bot runner: fetch market data, run strategy, execute paper orders.
"""
from datetime import datetime, timedelta
from app.config import settings
from app.market import fetch_prices
from app.paper_engine import (
    load_state,
    save_state,
    execute_order,
    get_positions,
)
from app.strategy import get_signals
from app.models import OrderSide


# In-memory status for the API
bot_status = {
    "running": True,
    "last_run": None,
    "next_run": None,
    "trade_count_today": 0,
}


def _count_trades_today(state: dict) -> int:
    today = datetime.utcnow().date().isoformat()
    return sum(
        1
        for t in state.get("trades", [])
        if (t.get("timestamp") or "").startswith(today)
    )


async def run_bot_once():
    """Fetch prices, generate signals, execute paper trades."""
    state = load_state(settings.initial_balance_usd)
    ticks = await fetch_prices()
    if not ticks:
        save_state(state)
        return

    prices = {t.symbol: t.price for t in ticks}
    positions = state["positions"]
    balance = state["balance_usd"]

    # Cooldown: last trade time per symbol
    last_trade_time: dict[str, datetime] = {}
    for t in state.get("trades", []):
        ts = t.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                sym = t.get("symbol", "")
                if sym and (sym not in last_trade_time or dt > last_trade_time[sym]):
                    last_trade_time[sym] = dt
            except Exception:
                pass

    signals = get_signals(ticks, balance, positions, last_trade_time)
    for symbol, side, quantity, reason, world_signal in signals:
        trade = execute_order(
            state, symbol, side, quantity, prices[symbol], reason, world_signal
        )
        if trade:
            balance = state["balance_usd"]
            positions = state["positions"]

    bot_status["last_run"] = datetime.utcnow()
    bot_status["trade_count_today"] = _count_trades_today(state)
    save_state(state)


def get_status_and_portfolio():
    """Load state and compute status + positions + total value for API."""
    state = load_state(settings.initial_balance_usd)
    prices = {s: 0.0 for s in settings.symbols}
    # We don't have prices here; API will merge with latest market data
    positions = get_positions(state, prices)
    balance = state["balance_usd"]
    total_value = balance + sum(p.value_usd for p in positions)
    initial = settings.initial_balance_usd
    pnl_usd = total_value - initial
    pnl_pct = (pnl_usd / initial * 100) if initial else 0

    return {
        "state": state,
        "positions": positions,
        "balance_usd": balance,
        "total_value_usd": total_value,
        "total_pnl_usd": pnl_usd,
        "total_pnl_percent": pnl_pct,
        "trade_count_today": _count_trades_today(state),
    }
