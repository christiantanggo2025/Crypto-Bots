"""
Gen 4: AI supervisor bot. Asks the supervisor (OpenAI + news context) for allow/limit/block,
then runs Gen1-style signals only when allowed (or with reduced size when limited).
"""
from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide


async def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    config: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None,
    supervisor_decision: dict,
) -> tuple[list[tuple[str, OrderSide, float, str, str | None]], str]:
    """
    Returns (signals, market_context_string).
    If decision is 'block', returns no buys (only sells for stop/target).
    If 'limit', reduces position size. If 'allow', normal size.
    """
    decision = (supervisor_decision.get("decision") or "allow").lower()
    reasoning = supervisor_decision.get("reasoning", "")
    guidance = supervisor_decision.get("guidance", "")

    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    min_drop = config.get("min_price_drop_pct", -1.5)
    min_rise = config.get("min_price_rise_pct", 1.0)
    position_pct = config.get("position_size_pct", 5.0) / 100.0
    min_trade_usd = config.get("min_trade_usd", 50.0)
    max_trade_pct = config.get("max_trade_pct_of_balance", 15.0) / 100.0
    max_coin_pct = config.get("max_exposure_per_coin_pct", 20.0) / 100.0
    cooldown_min = config.get("cooldown_minutes", 30.0)
    take_profit_pct = config.get("take_profit_pct", 1.0)
    stop_loss_pct = config.get("stop_loss_pct", -2.5)
    last_trade = last_trade_time_by_symbol or {}

    if decision == "limit":
        position_pct *= 0.5
        max_trade_pct *= 0.5
    if decision == "block":
        position_pct = 0
        max_trade_pct = 0

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

        # SELL: always allow (take profit, stop loss, or rise)
        if pos["quantity"] > 0:
            if pnl_pct_pos >= take_profit_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"[AI allow] Take profit: +{pnl_pct_pos:.2f}%",
                    "take_profit",
                ))
            elif pnl_pct_pos <= stop_loss_pct:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"[AI allow] Stop loss: {pnl_pct_pos:.2f}%",
                    "stop_loss",
                ))
            elif change_24h >= min_rise:
                qty = pos["quantity"]
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"[AI allow] 24h rise: +{change_24h:.2f}%",
                    "price_rise",
                ))

        # BUY: only if supervisor is not blocking
        elif decision != "block" and change_24h <= min_drop and position_pct_current < max_coin_pct * 100:
            max_spend = balance_usd * position_pct
            if max_spend >= min_trade_usd:
                spend = min(max_spend, balance_usd * max_trade_pct)
                qty = spend / price if price else 0
                if qty > 0:
                    tag = "[AI limit] " if decision == "limit" else "[AI allow] "
                    signals.append((
                        symbol, OrderSide.BUY, qty,
                        f"{tag}Buy dip: 24h {change_24h:.2f}%",
                        "price_drop",
                    ))

    market_context = f"Decision: {decision.upper()}. {reasoning} {guidance}".strip()
    return signals, market_context
