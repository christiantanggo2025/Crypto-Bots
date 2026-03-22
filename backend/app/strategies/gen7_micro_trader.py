"""
Gen 7: Active Micro-Movement Trader — short holds, frequent small wins, tight risk.
Harvests repeated small intraday-style moves (lab cycles as time steps); not a Gen 6 runner.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide
from app.time_toronto import UTC_MIN, utc_now


def _market_stats(ticks: list[MarketTick], enabled: set[str]) -> tuple[float, int, int, bool, str, bool]:
    changes = [t.change_24h for t in ticks if t.symbol in enabled]
    n = len(changes)
    if not n:
        return 0.0, 0, 0, False, "unknown", False
    avg = sum(changes) / n
    red = sum(1 for c in changes if c < 0)
    all_red = red == n
    broad = (red >= (n + 1) // 2 and avg < -0.5) or (all_red and avg < -1.0)
    if avg >= 0.5 and red <= 1:
        look = "stable"
    elif avg <= -1.5 or (all_red and avg < -1.0):
        look = "weak"
    else:
        look = "mixed"
    return avg, red, n, all_red, look, broad


def _regime(avg_24h: float, broad_weak: bool, market_look: str) -> str:
    if broad_weak or market_look == "weak":
        return "weak"
    if avg_24h >= 0.55 and not broad_weak:
        return "strong"
    return "mixed"


def _inc(stats: dict, key: str, n: int = 1) -> None:
    stats[key] = int(stats.get(key, 0)) + n


def get_signals(
    ticks: list[MarketTick],
    balance_usd: float,
    positions: dict,
    config: dict,
    last_trade_time_by_symbol: dict[str, datetime] | None,
    trades_today: int,
    state: dict,
) -> tuple[list[tuple[str, OrderSide, float, str, str | None]], list[dict], dict]:
    """
    Returns (signals, decisions, context). Mutates state["gen7"] for per-position micro state.
    """
    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    position_pct = float(config.get("position_size_pct", 2.5)) / 100.0
    max_trade_pct = float(config.get("max_trade_pct_of_balance", 7.0)) / 100.0
    min_trade_usd = float(config.get("min_trade_usd", 22.0))
    max_coin_pct = float(config.get("max_exposure_per_coin_pct", 10.0)) / 100.0
    max_total_exposure_pct = float(config.get("max_total_exposure_pct", 48.0)) / 100.0
    max_open_positions = int(config.get("max_open_positions", 5))
    cooldown_min = float(config.get("cooldown_minutes", 3.0))
    max_trades_per_day = int(config.get("max_trades_per_day", 48) or 0)

    take_profit_pct = float(config.get("gen7_take_profit_pct", 0.22))
    stop_loss_pct = float(config.get("gen7_stop_loss_pct", -0.36))
    max_hold_cycles = int(config.get("gen7_max_hold_cycles", 9))
    max_hold_hard = int(config.get("gen7_max_hold_hard_cycles", 14))
    stall_cycles_exit = int(config.get("gen7_stall_cycles", 4))
    stall_epsilon = float(config.get("gen7_stall_epsilon_pct", 0.05))
    timeout_min_progress = float(config.get("gen7_timeout_min_progress_pct", 0.06))
    micro_lock_pct = float(config.get("gen7_micro_lock_profit_pct", 0.14))
    micro_lock_stall = int(config.get("gen7_micro_lock_stall_cycles", 2))
    fade_from_peak = float(config.get("gen7_fade_from_peak_pct", 0.09))
    fade_need_peak = float(config.get("gen7_fade_min_peak_pct", 0.10))

    # Entry tunables (smaller moves than Gen 6)
    gen7_min_drop = float(config.get("gen7_min_price_drop_pct", -0.38))
    gen7_max_entry_24h = float(config.get("gen7_max_entry_change_24h_pct", 0.42))
    gen7_catastrophic = float(config.get("gen7_catastrophic_entry_cutoff_pct", -9.0))
    gen7_rs_vs_avg = float(config.get("gen7_rs_vs_avg_buffer_pct", 2.8))
    gen7_burst_min_pct = float(config.get("gen7_cycle_burst_min_pct", 0.035))
    gen7_continuation_cap = float(config.get("gen7_continuation_max_24h_pct", 0.38))

    last_trade = last_trade_time_by_symbol or {}
    now = utc_now()
    cooldown_delta = timedelta(minutes=cooldown_min)
    at_daily_cap = max_trades_per_day > 0 and trades_today >= max_trades_per_day

    prices = {t.symbol: t.price for t in ticks}
    tick_by_sym = {t.symbol: t for t in ticks}

    avg_24h, _red, _n_syms, _all_red, market_look, broad_weak = _market_stats(ticks, enabled)
    regime = _regime(avg_24h, broad_weak, market_look)

    g7 = state.setdefault("gen7", {})
    by_sym: dict = g7.setdefault("by_symbol", {})
    stats = g7.setdefault("stats", {})
    last_prices: dict = g7.setdefault("last_cycle_close_prices", {})

    for s in list(by_sym.keys()):
        p = positions.get(s, {})
        if not p or (p.get("quantity") or 0) <= 0:
            del by_sym[s]

    signals: list[tuple[str, OrderSide, float, str, str | None]] = []
    decisions: list[dict] = []

    total_value = balance_usd + sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    if total_value <= 0:
        total_value = balance_usd

    current_positions_count = sum(1 for s, p in positions.items() if (p.get("quantity") or 0) > 0)
    current_exposure = sum(
        positions.get(s, {}).get("quantity", 0) * prices.get(s, 0) for s in positions
    )
    exposure_pct = (current_exposure / total_value * 100) if total_value else 0

    # Defensive: broad weakness — no new buys (still exit positions)
    defensive_entries = regime == "weak" and broad_weak
    position_snapshots: list[dict] = []
    last_exit_this_cycle: dict | None = None
    in_trade_symbols: set[str] = set()

    for symbol, pos in list(positions.items()):
        qty = pos.get("quantity", 0)
        if qty <= 0 or symbol not in enabled:
            continue
        tick = tick_by_sym.get(symbol)
        if not tick:
            continue
        price = tick.price
        change_24h = tick.change_24h
        avg = pos.get("avg_price", 0) or 0
        if avg <= 0:
            continue
        pnl_pct = (price - avg) / avg * 100
        in_trade_symbols.add(symbol)

        if symbol not in by_sym:
            by_sym[symbol] = {
                "cycles_held": 0,
                "stall_cycles": 0,
                "last_pnl_pct": pnl_pct,
                "max_pnl_pct_seen": pnl_pct,
                "entry_change_24h": change_24h,
                "regime_at_entry": regime,
                "stage": "holding_micro_momentum",
            }
        m = by_sym[symbol]

        m["cycles_held"] = int(m.get("cycles_held", 0)) + 1
        m["max_pnl_pct_seen"] = max(float(m.get("max_pnl_pct_seen", pnl_pct)), pnl_pct)

        if abs(pnl_pct - float(m.get("last_pnl_pct", pnl_pct))) < stall_epsilon:
            m["stall_cycles"] = int(m.get("stall_cycles", 0)) + 1
        else:
            m["stall_cycles"] = 0
        m["last_pnl_pct"] = pnl_pct

        exit_reason = ""
        exit_tag: str | None = None

        if pnl_pct >= take_profit_pct:
            exit_reason = "Exited after quick profit target was reached."
            exit_tag = "gen7_quick_profit"
        elif pnl_pct <= stop_loss_pct:
            exit_reason = "Exited because downside exceeded the acceptable micro-trade risk."
            exit_tag = "gen7_stop"
        elif m["cycles_held"] >= max_hold_hard:
            exit_reason = "Exited on hard time cap — freeing capital for the next setup."
            exit_tag = "gen7_hard_cap"
        elif m["cycles_held"] >= max_hold_cycles and pnl_pct < timeout_min_progress:
            exit_reason = "Exited on timeout — the move did not develop in time."
            exit_tag = "gen7_timeout"
        elif (
            float(m.get("max_pnl_pct_seen", 0)) >= fade_need_peak
            and pnl_pct <= float(m.get("max_pnl_pct_seen", 0)) - fade_from_peak
        ):
            exit_reason = "Exited on immediate momentum loss after a small favorable move."
            exit_tag = "gen7_momentum_fade"
        elif pnl_pct >= micro_lock_pct and int(m.get("stall_cycles", 0)) >= micro_lock_stall:
            exit_reason = "Exited — locked a small gain before the move stalled."
            exit_tag = "gen7_stall_take"
        elif -0.12 < pnl_pct < timeout_min_progress * 2 and int(m.get("stall_cycles", 0)) >= stall_cycles_exit:
            exit_reason = "Exited because the move stalled and failed to continue."
            exit_tag = "gen7_stall"
        elif change_24h < float(m.get("entry_change_24h", change_24h)) - 0.55:
            exit_reason = "Exited — short-term tape weakened vs entry."
            exit_tag = "gen7_tape_weak"

        if exit_tag:
            signals.append((symbol, OrderSide.SELL, qty, exit_reason, exit_tag))
            last_exit_this_cycle = {"symbol": symbol, "reason": exit_reason, "tag": exit_tag}
            if exit_tag == "gen7_quick_profit":
                _inc(stats, "exits_quick_profit")
            elif exit_tag == "gen7_stop":
                _inc(stats, "exits_stop")
            elif exit_tag in ("gen7_timeout", "gen7_hard_cap"):
                _inc(stats, "exits_timeout")
            elif exit_tag in ("gen7_stall", "gen7_stall_take"):
                _inc(stats, "exits_stall")
            elif exit_tag in ("gen7_momentum_fade", "gen7_tape_weak"):
                _inc(stats, "exits_momentum")
            del by_sym[symbol]
            continue

        # Snapshot for UI
        stage = str(m.get("stage", "holding_micro_momentum"))
        if pnl_pct >= take_profit_pct * 0.85:
            stage = "taking_quick_profit"
        elif int(m.get("stall_cycles", 0)) >= 2:
            stage = "exiting_on_stall" if pnl_pct < timeout_min_progress * 1.5 else "holding_micro_momentum"
        position_snapshots.append({
            "symbol": symbol,
            "pnl_pct": round(pnl_pct, 4),
            "cycles_held": m["cycles_held"],
            "stall_cycles": m["stall_cycles"],
            "stage": stage,
            "max_pnl_pct_seen": round(float(m.get("max_pnl_pct_seen", pnl_pct)), 4),
            "regime_at_entry": m.get("regime_at_entry", regime),
        })

    # --- New entries ---
    strategy_summary = ""
    operational_state = "scanning"

    if in_trade_symbols:
        operational_state = "in_trade"

    if defensive_entries and not in_trade_symbols:
        operational_state = "defensive_mode"
        strategy_summary = (
            "Defensive mode: broad weakness reducing new entries. Managing risk and scanning only."
        )
        decisions.append({
            "symbol": "",
            "action": "skip",
            "reason": "defensive_mode: weak broad market — no new micro entries.",
        })
    elif defensive_entries and in_trade_symbols:
        strategy_summary = "Defensive mode: not adding new positions; managing open micro trades."
        operational_state = "defensive_mode"
    elif at_daily_cap:
        strategy_summary = "Daily trade cap reached — standing down on new entries."
        decisions.append({"symbol": "", "action": "skip", "reason": "max_trades_per_day reached."})
    else:
        if regime == "strong":
            strategy_summary = (
                "Scanning for micro continuation and rebound setups; regime favorable for active trading."
            )
        elif regime == "mixed":
            strategy_summary = (
                "Scanning — choppy but tradeable conditions suit small repeated moves."
            )
        else:
            strategy_summary = "Cautious scanning in softer conditions; entries only on clear micro setups."

    for t in ticks:
        symbol = t.symbol
        if symbol not in enabled:
            continue
        pos = positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
        if (pos.get("quantity") or 0) > 0:
            continue
        if defensive_entries or at_daily_cap:
            continue
        if cooldown_min > 0 and (now - last_trade.get(symbol, UTC_MIN)) < cooldown_delta:
            continue
        if current_positions_count >= max_open_positions:
            break
        if exposure_pct >= max_total_exposure_pct * 100:
            break

        price = t.price
        change_24h = t.change_24h
        prev = last_prices.get(symbol)
        cycle_mom_pct = 0.0
        if prev and prev > 0:
            cycle_mom_pct = (price - prev) / prev * 100

        position_pct_current = (
            (pos.get("quantity", 0) * price / total_value * 100) if total_value else 0
        )
        if position_pct_current >= max_coin_pct * 100:
            continue

        rs_ok = change_24h >= avg_24h - gen7_rs_vs_avg
        if change_24h < gen7_catastrophic:
            continue
        if not rs_ok:
            continue

        allow_entry = False
        entry_reason = ""

        # Micro dip / rebound proxy (24h)
        if gen7_catastrophic < change_24h <= gen7_min_drop and change_24h <= gen7_max_entry_24h:
            allow_entry = True
            entry_reason = "Entered on short-term rebound setup with limited stretch vs peers."

        # Cycle burst (immediate movement)
        elif cycle_mom_pct >= gen7_burst_min_pct and change_24h <= gen7_max_entry_24h:
            allow_entry = True
            entry_reason = "Entered on brief momentum burst with controlled 24h context."

        # Continuation in strong regime only
        elif (
            regime == "strong"
            and 0.04 <= change_24h <= gen7_continuation_cap
            and cycle_mom_pct >= gen7_burst_min_pct * 0.65
        ):
            allow_entry = True
            entry_reason = "Entered micro continuation in a strong tape."

        # Slightly red / flat improving: small negative band + green cycle tick
        elif (
            -0.45 <= change_24h < -0.06
            and cycle_mom_pct >= gen7_burst_min_pct * 0.85
        ):
            allow_entry = True
            entry_reason = "Entered on pullback recovery with immediate follow-through."

        if allow_entry:
            max_spend = balance_usd * position_pct
            if max_spend < min_trade_usd:
                continue
            spend = min(max_spend, balance_usd * max_trade_pct)
            qty = spend / price if price else 0
            if qty <= 0:
                continue
            signals.append((
                symbol,
                OrderSide.BUY,
                qty,
                entry_reason,
                "gen7_micro_entry",
            ))
            decisions.append({"symbol": symbol, "action": "buy", "reason": entry_reason})
            _inc(stats, "entries")
            current_positions_count += 1
            exposure_pct += (qty * price / total_value * 100) if total_value else 0

    # Persist last prices for next cycle momentum
    for t in ticks:
        if t.symbol in enabled:
            last_prices[t.symbol] = t.price

    if signals and any(s[1] == OrderSide.BUY for s in signals):
        strategy_summary = "Entering micro trades — short holds, quick targets, tight risk."
    elif signals and all(s[1] == OrderSide.SELL for s in signals):
        if not strategy_summary:
            strategy_summary = "Managing exits — capturing small wins or cutting stale moves."
    elif not signals and not defensive_entries and not at_daily_cap:
        if not strategy_summary:
            strategy_summary = "Scanning for small tradable movement; no setup met this cycle."

    total_trades = int(stats.get("entries", 0))  # entries counter; sells tracked in exit counters
    evaluation_metrics = {
        "gen7_exits_quick_profit": int(stats.get("exits_quick_profit", 0)),
        "gen7_exits_stop": int(stats.get("exits_stop", 0)),
        "gen7_exits_timeout": int(stats.get("exits_timeout", 0)),
        "gen7_exits_stall": int(stats.get("exits_stall", 0)),
        "gen7_exits_momentum": int(stats.get("exits_momentum", 0)),
        "gen7_entries": int(stats.get("entries", 0)),
        "operational_state": operational_state,
        "regime": regime,
    }

    context = {
        "strategy_summary": strategy_summary,
        "market_regime": regime,
        "market_avg_24h": avg_24h,
        "broad_weakness": broad_weak,
        "market_look": market_look,
        "defensive_entries": defensive_entries,
        "operational_state": operational_state,
        "position_snapshots": position_snapshots,
        "evaluation_metrics": evaluation_metrics,
        "last_exit": last_exit_this_cycle,
        "trades_session_entries": total_trades,
    }
    return signals, decisions, context
