"""
Gen 5: Aggressive Scalper Bot. Intraday-focused, smaller positions, faster profit targets,
shorter holds. Looks for small repeatable opportunities; backs off when market is weak or messy.
"""
from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide


def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    config: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None = None,
    trades_today: int = 0,
) -> tuple[list[tuple[str, OrderSide, float, str, str | None]], dict]:
    """
    Returns (signals, context). context has strategy_summary and activity_mode for UI.
    """
    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    min_drop = config.get("min_price_drop_pct", -0.5)
    min_rise = config.get("min_price_rise_pct", 0.3)
    position_pct = config.get("position_size_pct", 3.0) / 100.0
    min_trade_usd = config.get("min_trade_usd", 25.0)
    max_trade_pct = config.get("max_trade_pct_of_balance", 8.0) / 100.0
    max_coin_pct = config.get("max_exposure_per_coin_pct", 12.0) / 100.0
    max_total_exposure_pct = config.get("max_total_exposure_pct", 50.0) / 100.0
    max_open_positions = config.get("max_open_positions", 4)
    cooldown_min = config.get("cooldown_minutes", 5.0)
    take_profit_pct = config.get("take_profit_pct", 0.4)
    stop_loss_pct = config.get("stop_loss_pct", -0.6)
    max_trades_per_day = config.get("max_trades_per_day", 30)
    last_trade = last_trade_time_by_symbol or {}
    at_daily_cap = max_trades_per_day and trades_today >= max_trades_per_day

    signals = []
    prices = {t.symbol: t.price for t in ticks}
    total_value = balance_usd + sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    if total_value <= 0:
        total_value = balance_usd

    # Market context: broad weakness → protective mode (no new buys or very selective)
    changes = [t.change_24h for t in ticks if t.symbol in enabled]
    avg_24h = sum(changes) / len(changes) if changes else 0.0
    red_count = sum(1 for c in changes if c < 0)
    all_red = red_count == len(changes) and len(changes) > 0
    broad_weak = avg_24h < -1.0 or (all_red and avg_24h < -0.5)
    messy = len(changes) >= 2 and -0.8 < avg_24h < 0.8 and red_count > 0 and red_count < len(changes)

    if broad_weak:
        activity_mode = "protective"
        strategy_summary = "Slowing down: market is weak. Avoiding new entries; only managing existing positions."
    elif messy:
        activity_mode = "waiting"
        strategy_summary = "Waiting for clearer conditions. Market is mixed; not ideal for quick scalps."
    else:
        activity_mode = "active"
        strategy_summary = "Looking for quick rebound opportunities and short intraday profit windows."

    now = datetime.utcnow()
    cooldown_delta = timedelta(minutes=cooldown_min)
    current_positions_count = sum(1 for s, p in positions.items() if (p.get("quantity") or 0) > 0)
    current_exposure = sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    exposure_pct = (current_exposure / total_value * 100) if total_value else 0

    # Optional: cap trades today (from state we don't have here; caller can enforce)
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

        # SELL: fast take profit or tight stop
        if pos["quantity"] > 0:
            if pnl_pct_pos >= take_profit_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Scalp TP: +{pnl_pct_pos:.2f}% (target {take_profit_pct}%)",
                    "take_profit",
                ))
            elif pnl_pct_pos <= stop_loss_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Scalp SL: {pnl_pct_pos:.2f}% (limit {stop_loss_pct}%)",
                    "stop_loss",
                ))
            elif change_24h >= min_rise:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Quick exit: 24h +{change_24h:.2f}%",
                    "price_rise",
                ))

        # BUY: only when not protective/waiting (e.g. not at daily cap); smaller dips; respect caps
        elif activity_mode == "active" and not at_daily_cap and current_positions_count < max_open_positions and exposure_pct < max_total_exposure_pct * 100:
            if change_24h <= min_drop and position_pct_current < max_coin_pct * 100:
                max_spend = balance_usd * position_pct
                if max_spend >= min_trade_usd:
                    spend = min(max_spend, balance_usd * max_trade_pct)
                    qty = spend / price if price else 0
                    if qty > 0:
                        signals.append((
                            symbol, OrderSide.BUY, qty,
                            f"Scalp entry: 24h {change_24h:.2f}% (quick rebound)",
                            "price_drop",
                        ))

    if signals and activity_mode == "active":
        strategy_summary = "Taking short intraday profit windows; entering and exiting on small moves."
    elif not signals and activity_mode == "active":
        strategy_summary = "Looking for quick rebound opportunities. No setup met this cycle."

    context = {
        "strategy_summary": strategy_summary,
        "activity_mode": activity_mode,
        "broad_weakness": broad_weak,
        "market_avg_24h": avg_24h,
    }
    return signals, context
