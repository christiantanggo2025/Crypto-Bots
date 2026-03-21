"""
Gen 3: Adaptive bot. Uses simple market context (trend) to decide when dip-buying is appropriate.
- Classifies context: uptrend / sideways / downtrend (e.g. from 24h vs 7d or volume)
- Only buys dips in uptrend or sideways; avoids buying into clear weakness
- More selective entries and better timing
"""
from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide


def _market_context(ticks: list[MarketTick]) -> str:
    """
    Simple context: average 24h change and spread.
    'uptrend' if avg change > 0.5%, 'downtrend' if < -1%, else 'sideways'.
    """
    if not ticks:
        return "sideways"
    avg_change = sum(t.change_24h for t in ticks) / len(ticks)
    if avg_change > 0.5:
        return "uptrend"
    if avg_change < -1.0:
        return "downtrend"
    return "sideways"


def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    config: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None = None,
) -> tuple[list[tuple[str, OrderSide, float, str, str | None]], list[dict]]:
    """Returns (signals, decisions). decisions = list of {symbol, action, reason} for skip/no-trade reasons."""
    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    min_drop = config.get("min_price_drop_pct", -1.5)
    min_rise = config.get("min_price_rise_pct", 1.0)
    position_pct = config.get("position_size_pct", 7.0) / 100.0
    min_trade_usd = config.get("min_trade_usd", 50.0)
    max_trade_pct = config.get("max_trade_pct_of_balance", 12.0) / 100.0
    max_coin_pct = config.get("max_exposure_per_coin_pct", 20.0) / 100.0
    cooldown_min = config.get("cooldown_minutes", 15.0)
    take_profit_pct = config.get("take_profit_pct", 1.0)
    stop_loss_pct = config.get("stop_loss_pct", -2.5)
    last_trade = last_trade_time_by_symbol or {}

    context = _market_context(ticks)
    allow_dip_buy = context in ("uptrend", "sideways")

    signals = []
    decisions: list[dict] = []
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
            decisions.append({"symbol": symbol, "action": "skip", "reason": "Cooldown active; waiting before re-entering."})
            continue

        price = t.price
        change_24h = t.change_24h
        pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
        pos_value = pos["quantity"] * price
        position_pct_current = (pos_value / total_value * 100) if total_value else 0
        pnl_pct_pos = ((price - pos["avg_price"]) / pos["avg_price"] * 100) if pos["avg_price"] else 0

        if pos["quantity"] > 0:
            if pnl_pct_pos >= take_profit_pct:
                qty = pos["quantity"]
                signals.append((symbol, OrderSide.SELL, qty, f"Take profit: +{pnl_pct_pos:.2f}%", "take_profit"))
            elif pnl_pct_pos <= stop_loss_pct:
                qty = pos["quantity"]
                signals.append((symbol, OrderSide.SELL, qty, f"Stop loss: {pnl_pct_pos:.2f}%", "stop_loss"))
            elif change_24h >= min_rise:
                qty = pos["quantity"]
                signals.append((symbol, OrderSide.SELL, qty, f"24h rise: +{change_24h:.2f}% (market: {context})", "price_rise"))
            else:
                decisions.append({"symbol": symbol, "action": "hold", "reason": f"Position +{pnl_pct_pos:.2f}%; 24h {change_24h:.2f}%. No sell trigger yet (need ≥{min_rise}% rise or TP/SL)."})
        else:
            if not allow_dip_buy:
                decisions.append({"symbol": symbol, "action": "skip_buy", "reason": f"Market context is {context}; not buying dips (only in uptrend/sideways)."})
            elif change_24h > min_drop:
                decisions.append({"symbol": symbol, "action": "skip_buy", "reason": f"24h change {change_24h:.2f}% (need ≤ {min_drop}% to buy dip)."})
            elif position_pct_current >= max_coin_pct * 100:
                decisions.append({"symbol": symbol, "action": "skip_buy", "reason": f"Already at max exposure for this coin ({max_coin_pct*100:.0f}%)."})
            else:
                max_spend = balance_usd * position_pct
                if max_spend < min_trade_usd:
                    decisions.append({"symbol": symbol, "action": "skip_buy", "reason": f"Position size would be ${max_spend:.0f} (min ${min_trade_usd})."})
                else:
                    spend = min(max_spend, balance_usd * max_trade_pct)
                    qty = spend / price if price else 0
                    if qty > 0:
                        signals.append((symbol, OrderSide.BUY, qty, f"Adaptive buy: 24h {change_24h:.2f}% in {context}", "price_drop"))

    if not signals and not decisions:
        decisions.append({"symbol": "—", "action": "no_action", "reason": f"Market context: {context}. No symbols met buy/sell rules this cycle."})
    return signals, decisions
