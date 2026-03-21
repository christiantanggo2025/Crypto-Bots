"""
Strategy: buy/sell signals from price change (and optional world signals).
Uses persistent trading params so the UI can control behavior.
"""
from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide
from app.time_toronto import UTC_MIN, utc_now
from app.trading_params import load_params, get_enabled_symbols


def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None = None,
) -> list[tuple[str, OrderSide, float, str, str | None]]:
    """
    Returns list of (symbol, side, quantity, reason, world_signal).
    quantity is in coin units.
    """
    params = load_params()
    enabled = set(get_enabled_symbols())
    min_drop = params["min_price_drop_pct"]
    min_rise = params["min_price_rise_pct"]
    position_pct = params["position_pct_of_balance"]
    min_trade_usd = params["min_trade_usd"]
    max_trade_pct = params.get("max_trade_pct_of_balance", 20.0) / 100.0
    max_position_pct = params.get("max_position_pct_per_coin", 25.0) / 100.0
    cooldown_min = params.get("cooldown_minutes", 0)
    last_trade = last_trade_time_by_symbol or {}

    signals = []
    prices = {t.symbol: t.price for t in ticks}
    total_value = balance_usd + sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    if total_value <= 0:
        total_value = balance_usd

    now = utc_now()
    cooldown_delta = timedelta(minutes=cooldown_min)

    for t in ticks:
        symbol = t.symbol
        if symbol not in enabled:
            continue
        if cooldown_min > 0 and (now - last_trade.get(symbol, UTC_MIN)) < cooldown_delta:
            continue

        price = t.price
        change_24h = t.change_24h
        pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
        pos_value = pos["quantity"] * price
        position_pct_current = (pos_value / total_value * 100) if total_value else 0

        # SELL: we have position and price is up enough (take profit)
        if pos["quantity"] > 0 and change_24h >= min_rise:
            qty = pos["quantity"]
            signals.append((
                symbol,
                OrderSide.SELL,
                qty,
                f"Take profit: 24h change +{change_24h:.2f}% (rule: ≥ {min_rise}%)",
                "price_rise",
            ))

        # BUY: price dropped and we're under max position size
        elif change_24h <= min_drop and position_pct_current < max_position_pct * 100:
            max_spend = balance_usd * position_pct
            if max_spend < min_trade_usd:
                continue
            spend = min(max_spend, balance_usd * max_trade_pct)
            qty = spend / price if price else 0
            if qty > 0:
                signals.append((
                    symbol,
                    OrderSide.BUY,
                    qty,
                    f"Buy dip: 24h change {change_24h:.2f}% (rule: ≤ {min_drop}%)",
                    "price_drop",
                ))

    return signals
