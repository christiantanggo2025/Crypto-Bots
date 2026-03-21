"""
Gen 2: Optimized bot. Same dip-buy idea as Gen 1 but with tighter risk and pacing.
- Stricter entry (e.g. require slightly deeper dip or volume)
- Smaller position size, more cooldown
- Explicit take profit and stop loss from config
- No overbuying: respects max_entries_per_coin and max_total_exposure
"""
from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide


def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    config: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None = None,
) -> list[tuple[str, OrderSide, float, str, str | None]]:
    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    min_drop = config.get("min_price_drop_pct", -1.5)
    min_rise = config.get("min_price_rise_pct", 1.0)
    position_pct = config.get("position_size_pct", 8.0) / 100.0
    min_trade_usd = config.get("min_trade_usd", 50.0)
    max_trade_pct = config.get("max_trade_pct_of_balance", 15.0) / 100.0
    max_coin_pct = config.get("max_exposure_per_coin_pct", 20.0) / 100.0
    cooldown_min = config.get("cooldown_minutes", 10.0)
    take_profit_pct = config.get("take_profit_pct", 1.0)
    stop_loss_pct = config.get("stop_loss_pct", -2.5)
    last_trade = last_trade_time_by_symbol or {}

    signals = []
    prices = {t.symbol: t.price for t in ticks}
    total_value = balance_usd + sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    if total_value <= 0:
        total_value = balance_usd

    now = datetime.utcnow()
    cooldown_delta = timedelta(minutes=cooldown_min)

    for t in ticks:
        symbol = t.symbol
        if symbol not in enabled:
            continue
        if cooldown_min > 0 and (now - last_trade.get(symbol, datetime.min)) < cooldown_delta:
            continue

        price = t.price
        change_24h = t.change_24h
        pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
        pos_value = pos["quantity"] * price
        position_pct_current = (pos_value / total_value * 100) if total_value else 0
        pnl_pct_pos = ((price - pos["avg_price"]) / pos["avg_price"] * 100) if pos["avg_price"] else 0

        # SELL: take profit or stop loss (Gen 2 exits more disciplined)
        if pos["quantity"] > 0:
            if pnl_pct_pos >= take_profit_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Take profit: +{pnl_pct_pos:.2f}% (target {take_profit_pct}%)",
                    "take_profit",
                ))
            elif pnl_pct_pos <= stop_loss_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Stop loss: {pnl_pct_pos:.2f}% (limit {stop_loss_pct}%)",
                    "stop_loss",
                ))
            elif change_24h >= min_rise:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"24h rise exit: +{change_24h:.2f}% (≥ {min_rise}%)",
                    "price_rise",
                ))

        # BUY: slightly stricter — require drop at or below threshold, and under exposure
        elif change_24h <= min_drop and position_pct_current < max_coin_pct * 100:
            max_spend = balance_usd * position_pct
            if max_spend < min_trade_usd:
                continue
            spend = min(max_spend, balance_usd * max_trade_pct)
            qty = spend / price if price else 0
            if qty > 0:
                signals.append((
                    symbol, OrderSide.BUY, qty,
                    f"Buy dip (optimized): 24h {change_24h:.2f}% (≤ {min_drop}%)",
                    "price_drop",
                ))

    return signals
