"""
Gen 6: Momentum Rider Bot — hybrid scalper / trend rider.
Tuned for: disciplined entries, early protection, real runner promotion, adaptive trails,
efficient weak exits, sensible timeouts, partial scale-out that preserves upside.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models import MarketTick, OrderSide
from app.time_toronto import UTC_MIN, utc_now

MAX_LEG_HISTORY = 120


def _market_stats(ticks: list[MarketTick], enabled: set[str]) -> tuple[float, int, int, bool, str, bool]:
    """avg_24h, red_count, n, all_red, market_look, broad_weakness (Gen4-style)."""
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
    if avg_24h >= 0.65 and not broad_weak:
        return "strong"
    return "mixed"


def _inc(stats: dict, key: str, n: int = 1) -> None:
    stats[key] = int(stats.get(key, 0)) + n


def _append_leg(g6: dict, record: dict) -> None:
    hist = g6.setdefault("leg_history", [])
    hist.append(record)
    if len(hist) > MAX_LEG_HISTORY:
        del hist[: len(hist) - MAX_LEG_HISTORY]


def _rollup_leg_history(hist: list) -> dict:
    """Aggregates for UI from recent closed legs (approx; partials included with flag)."""
    if not hist:
        return {
            "closed_legs": 0,
            "avg_peak_pnl_pct": None,
            "avg_pnl_at_exit_pct": None,
            "avg_giveback_pct": None,
            "avg_cycles_winners": None,
            "avg_cycles_losers": None,
        }
    full_closes = [h for h in hist if not h.get("partial")]
    if not full_closes:
        full_closes = hist[-20:]
    peaks = [float(h.get("peak_pnl_pct") or 0) for h in full_closes]
    pex = [float(h.get("pnl_at_exit_pct") or 0) for h in full_closes]
    gb = [float(h.get("giveback_pct") or 0) for h in full_closes]
    cy = [int(h.get("cycles") or 0) for h in full_closes]
    winners = [h for h in full_closes if float(h.get("pnl_at_exit_pct") or 0) > 0]
    losers = [h for h in full_closes if float(h.get("pnl_at_exit_pct") or 0) <= 0]
    return {
        "closed_legs": len(full_closes),
        "avg_peak_pnl_pct": sum(peaks) / len(peaks) if peaks else None,
        "avg_pnl_at_exit_pct": sum(pex) / len(pex) if pex else None,
        "avg_giveback_pct": sum(gb) / len(gb) if gb else None,
        "avg_cycles_winners": (
            sum(int(h.get("cycles") or 0) for h in winners) / len(winners) if winners else None
        ),
        "avg_cycles_losers": (
            sum(int(h.get("cycles") or 0) for h in losers) / len(losers) if losers else None
        ),
    }


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
    Returns (signals, decisions, context). Mutates state["gen6"] for per-position rider state.
    """
    enabled = set(config.get("symbols") or ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    min_drop = float(config.get("min_price_drop_pct", -1.08))
    min_trade_usd = float(config.get("min_trade_usd", 40.0))
    position_pct = float(config.get("position_size_pct", 5.0)) / 100.0
    max_trade_pct = float(config.get("max_trade_pct_of_balance", 12.0)) / 100.0
    max_coin_pct = float(config.get("max_exposure_per_coin_pct", 18.0)) / 100.0
    max_total_exposure_pct = float(config.get("max_total_exposure_pct", 65.0)) / 100.0
    max_open_positions = int(config.get("max_open_positions", 4))
    cooldown_min = float(config.get("cooldown_minutes", 7.0))
    stop_loss_pct = float(config.get("stop_loss_pct", -1.12))
    max_trades_per_day = int(config.get("max_trades_per_day", 40) or 0)

    protect_pct = float(config.get("gen6_protect_profit_pct", 0.30))
    runner_pct = float(config.get("gen6_runner_activation_pct", 0.62))
    scaleout_pct = float(config.get("gen6_scaleout_pct", 0.55))
    scaleout_fraction = float(config.get("gen6_scaleout_fraction", 0.38))
    trail_tight = float(config.get("gen6_trail_tight_pct", 0.28))
    trail_runner_weak = float(config.get("gen6_trail_runner_weak_pct", 0.36))
    trail_runner_mixed = float(config.get("gen6_trail_runner_normal_pct", 0.55))
    trail_runner_strong = float(config.get("gen6_trail_runner_strong_pct", 0.72))
    max_hold_cycles = int(config.get("gen6_max_hold_cycles", 36))
    stall_cycles_exit = int(config.get("gen6_stall_cycles", 9))
    runner_mom_min = float(config.get("gen6_runner_momentum_min_24h", -0.22))
    catastrophic = float(config.get("gen6_catastrophic_entry_cutoff_pct", -10.5))
    stall_epsilon = float(config.get("gen6_stall_epsilon_pct", 0.07))

    last_trade = last_trade_time_by_symbol or {}
    now = utc_now()
    cooldown_delta = timedelta(minutes=cooldown_min)
    at_daily_cap = max_trades_per_day > 0 and trades_today >= max_trades_per_day

    prices = {t.symbol: t.price for t in ticks}
    tick_by_sym = {t.symbol: t for t in ticks}

    avg_24h, red_count, _n_syms, all_red, market_look, broad_weak = _market_stats(ticks, enabled)
    regime = _regime(avg_24h, broad_weak, market_look)

    g6 = state.setdefault("gen6", {})
    by_sym: dict = g6.setdefault("by_symbol", {})
    stats = g6.setdefault("stats", {})

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

    protective_entries = regime == "weak" and broad_weak
    any_runner = False
    position_snapshots: list[dict] = []
    last_exit_this_cycle: dict | None = None

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

        if symbol not in by_sym:
            by_sym[symbol] = {
                "peak_price": price,
                "cycles_held": 0,
                "stall_cycles": 0,
                "last_pnl_pct": pnl_pct,
                "stage": "entered_probe",
                "runner_active": False,
                "protected": False,
                "scaled_out": False,
                "max_pnl_pct_seen": pnl_pct,
            }
        m = by_sym[symbol]

        was_runner = bool(m.get("runner_active"))
        was_protected = bool(m.get("protected"))

        m["cycles_held"] = int(m.get("cycles_held", 0)) + 1
        m["peak_price"] = max(float(m.get("peak_price", price)), price)
        m["max_pnl_pct_seen"] = max(float(m.get("max_pnl_pct_seen", pnl_pct)), pnl_pct)

        if abs(pnl_pct - float(m.get("last_pnl_pct", pnl_pct))) < stall_epsilon:
            m["stall_cycles"] = int(m.get("stall_cycles", 0)) + 1
        else:
            m["stall_cycles"] = 0
        m["last_pnl_pct"] = pnl_pct

        if pnl_pct >= protect_pct:
            m["protected"] = True
        if m["protected"] and not was_protected:
            _inc(stats, "protected_activations")

        runner_bar = runner_pct
        if regime == "weak":
            runner_bar = runner_pct + 0.20
        elif regime == "strong":
            runner_bar = max(0.42, runner_pct - 0.08)

        mom_ok = change_24h >= runner_mom_min
        follow_through = float(m.get("max_pnl_pct_seen", 0)) >= runner_bar * 0.88
        price_confirmation = pnl_pct >= runner_bar * 0.92

        can_runner = (
            m["protected"]
            and pnl_pct >= runner_bar
            and mom_ok
            and (follow_through or price_confirmation or (regime == "strong" and pnl_pct >= runner_bar * 1.02))
        )

        if can_runner:
            m["runner_active"] = True
            m["stage"] = "runner_mode"
        elif was_runner:
            demote = (
                pnl_pct < protect_pct * 0.42
                or (change_24h < runner_mom_min - 0.55 and pnl_pct < runner_bar * 0.75)
                or (not can_runner and (not mom_ok) and pnl_pct < runner_bar * 0.82)
            )
            if demote:
                m["runner_active"] = False
                m["stage"] = "trailing_profit" if pnl_pct > 0 else "entered_probe"
        elif m["protected"] and not m["runner_active"]:
            m["stage"] = "protected_profit"
        elif pnl_pct < protect_pct:
            m["stage"] = "entered_probe"

        if m["runner_active"] and not was_runner:
            _inc(stats, "runner_activations")

        if m["runner_active"]:
            any_runner = True

        peak = float(m["peak_price"])
        dd_from_peak_pct = ((peak - price) / peak * 100) if peak > 0 else 0.0
        max_seen = float(m.get("max_pnl_pct_seen", pnl_pct))

        if m["runner_active"]:
            if regime == "weak":
                trail = trail_runner_weak
            elif regime == "strong":
                trail = trail_runner_strong
            else:
                trail = trail_runner_mixed
        else:
            trail = trail_tight

        if max_seen >= 4.0:
            trail *= 1.14
        elif max_seen >= 2.2:
            trail *= 1.08
        elif max_seen >= 1.15:
            trail *= 1.04

        if pnl_pct >= 2.4:
            trail *= 1.06
        elif pnl_pct < 0.48 and m["protected"] and not m["runner_active"]:
            trail *= 0.90

        trail = min(trail, 1.35)

        trail_needs_confirm = not m["runner_active"]
        trail_fired = dd_from_peak_pct >= trail and peak >= avg * 1.001
        if trail_fired and trail_needs_confirm:
            trail_fired = m["stall_cycles"] >= 2 or dd_from_peak_pct >= trail * 1.08
        elif trail_fired and m["runner_active"]:
            trail_fired = m["stall_cycles"] >= 1 or dd_from_peak_pct >= trail * 1.03

        position_snapshots.append({
            "symbol": symbol,
            "stage": m["stage"],
            "runner_active": m["runner_active"],
            "protected": bool(m.get("protected")),
            "scaled_out": bool(m.get("scaled_out")),
            "pnl_pct": round(pnl_pct, 3),
            "peak_price": peak,
            "max_pnl_pct_seen": round(max_seen, 3),
            "drawdown_from_peak_pct": round(dd_from_peak_pct, 3),
            "cycles_held": m["cycles_held"],
            "stall_cycles": m["stall_cycles"],
            "trail_threshold_pct": round(trail, 3),
        })

        sold_this_symbol = False

        def _record_exit(tag: str, partial: bool, reason_human: str) -> None:
            nonlocal last_exit_this_cycle
            rec = {
                "tag": tag,
                "symbol": symbol,
                "partial": partial,
                "peak_pnl_pct": max_seen,
                "pnl_at_exit_pct": pnl_pct,
                "giveback_pct": dd_from_peak_pct,
                "cycles": m["cycles_held"],
            }
            _append_leg(g6, rec)
            last_exit_this_cycle = {"tag": tag, "symbol": symbol, "reason": reason_human}

        if pnl_pct <= stop_loss_pct:
            signals.append((
                symbol, OrderSide.SELL, qty,
                f"Exited on failed rebound / stop: {pnl_pct:.2f}% (limit {stop_loss_pct}%).",
                "gen6_stop_loss",
            ))
            decisions.append({
                "symbol": symbol,
                "action": "exiting_on_failed_rebound",
                "reason": "Stop loss hit — rebound did not hold; capital protected.",
            })
            _inc(stats, "exits_failed_rebound")
            _record_exit("gen6_stop_loss", False, "Failed rebound / stop loss")
            sold_this_symbol = True

        elif m["cycles_held"] >= max_hold_cycles:
            if not m["runner_active"] or pnl_pct < protect_pct * 0.80:
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Time exit: held {m['cycles_held']} cycles without sufficient runner follow-through.",
                    "gen6_time_exit",
                ))
                decisions.append({
                    "symbol": symbol,
                    "action": "exiting_on_timeout",
                    "reason": "Trade did not develop in time; releasing capital for active trading.",
                })
                _inc(stats, "exits_timeout")
                _record_exit("gen6_time_exit", False, "Time exit — no follow-through")
                sold_this_symbol = True
            elif m["runner_active"] and m["stall_cycles"] >= stall_cycles_exit + 5:
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    "Time + stall: runner stalled too long; locking in progress.",
                    "gen6_time_stall",
                ))
                decisions.append({
                    "symbol": symbol,
                    "action": "exiting_on_timeout",
                    "reason": "Runner mode but price stalled; exiting per time/stagnation rules.",
                })
                _inc(stats, "exits_timeout")
                _record_exit("gen6_time_stall", False, "Timeout with stalled runner")
                sold_this_symbol = True
            elif m["cycles_held"] >= max_hold_cycles + 32:
                signals.append((
                    symbol, OrderSide.SELL, qty,
                    f"Hard time cap: held {m['cycles_held']} cycles — active trader, not long-term hold.",
                    "gen6_hard_time_cap",
                ))
                decisions.append({
                    "symbol": symbol,
                    "action": "exiting_on_timeout",
                    "reason": "Absolute max hold reached; releasing capital even if runner was still active.",
                })
                _inc(stats, "exits_timeout")
                _record_exit("gen6_hard_time_cap", False, "Hard max hold cap")
                sold_this_symbol = True

        elif pnl_pct > 0 and trail_fired:
            signals.append((
                symbol, OrderSide.SELL, qty,
                f"Trailing exit: pullback {dd_from_peak_pct:.2f}% from peak (≥{trail:.2f}% tolerance).",
                "gen6_trailing_stop",
            ))
            decisions.append({
                "symbol": symbol,
                "action": "exiting_on_trailing_stop",
                "reason": "Pullback from peak exceeded adaptive trailing tolerance after strength.",
            })
            _inc(stats, "exits_trailing")
            _record_exit("gen6_trailing_stop", False, "Trailing stop — giveback after peak")
            sold_this_symbol = True

        elif (
            m["protected"]
            and not m["runner_active"]
            and pnl_pct > 0
            and m["stall_cycles"] >= (stall_cycles_exit + 2 if pnl_pct < 0.85 else stall_cycles_exit)
            and change_24h < 0.06
        ):
            signals.append((
                symbol, OrderSide.SELL, qty,
                f"Weak momentum exit: +{pnl_pct:.2f}% but stalled {m['stall_cycles']} cycles; 24h {change_24h:+.2f}%.",
                "gen6_weak_momentum",
            ))
            decisions.append({
                "symbol": symbol,
                "action": "exiting_on_weakness",
                "reason": "Profit reached but move did not strengthen — taking gain and moving on.",
            })
            _inc(stats, "exits_weak_momentum")
            _record_exit("gen6_weak_momentum", False, "Weak momentum / stall — took profit")
            sold_this_symbol = True

        elif (
            m["runner_active"]
            and pnl_pct > protect_pct * 0.92
            and change_24h < runner_mom_min - 0.28
            and dd_from_peak_pct >= trail * 0.52
        ):
            signals.append((
                symbol, OrderSide.SELL, qty,
                f"Runner exit: upward momentum weakened (24h {change_24h:+.2f}%) with pullback from peak.",
                "gen6_runner_weak",
            ))
            decisions.append({
                "symbol": symbol,
                "action": "exiting_on_weakness",
                "reason": "Runner mode ended — 24h momentum deteriorated; exit after strength faded.",
            })
            _inc(stats, "exits_runner_weak")
            _record_exit("gen6_runner_weak", False, "Runner ended — momentum faded + pullback")
            sold_this_symbol = True

        elif (
            not sold_this_symbol
            and not m.get("scaled_out")
            and pnl_pct >= scaleout_pct
            and qty > 0
            and scaleout_fraction > 0
            and scaleout_fraction < 1.0
        ):
            skip_scale = (
                regime == "strong"
                and pnl_pct >= runner_bar * 0.90
                and change_24h >= runner_mom_min
            ) or (m["runner_active"] and pnl_pct >= runner_bar * 0.85)
            if not skip_scale:
                partial_qty = qty * scaleout_fraction
                if partial_qty * price >= min_trade_usd * 0.25:
                    signals.append((
                        symbol, OrderSide.SELL, partial_qty,
                        f"Partial scale-out (~{scaleout_fraction*100:.0f}%): secured gain at +{pnl_pct:.2f}%; remainder may run.",
                        "gen6_scaleout",
                    ))
                    m["scaled_out"] = True
                    m["stage"] = "protected_profit"
                    _inc(stats, "scaleouts")
                    _append_leg(
                        g6,
                        {
                            "tag": "gen6_scaleout",
                            "symbol": symbol,
                            "partial": True,
                            "peak_pnl_pct": max_seen,
                            "pnl_at_exit_pct": pnl_pct,
                            "giveback_pct": dd_from_peak_pct,
                            "cycles": m["cycles_held"],
                        },
                    )
                    decisions.append({
                        "symbol": symbol,
                        "action": "protected_profit",
                        "reason": "Partial scale-out — locked profit; remainder can still run as runner.",
                    })

    if not protective_entries and not at_daily_cap and current_positions_count < max_open_positions and exposure_pct < max_total_exposure_pct * 100:
        rel_gap = 3.3 if regime == "mixed" else 3.8 if regime == "strong" else 4.2
        for t in ticks:
            symbol = t.symbol
            if symbol not in enabled:
                continue
            if positions.get(symbol, {}).get("quantity", 0) > 0:
                continue
            if cooldown_min > 0 and (now - last_trade.get(symbol, UTC_MIN)) < cooldown_delta:
                continue
            change_24h = t.change_24h
            price = t.price
            pos_value = positions.get(symbol, {}).get("quantity", 0) * price
            position_pct_current = (pos_value / total_value * 100) if total_value else 0

            if change_24h > min_drop:
                continue
            if change_24h <= catastrophic:
                decisions.append({
                    "symbol": symbol,
                    "action": "waiting_for_entry",
                    "reason": f"Skip: move too extreme ({change_24h:.2f}%) for safe rebound entry.",
                })
                continue
            if change_24h < avg_24h - rel_gap:
                decisions.append({
                    "symbol": symbol,
                    "action": "rebound_candidate",
                    "reason": "Skip: symbol lagging much worse than market average — poor relative strength.",
                })
                continue
            if position_pct_current >= max_coin_pct * 100:
                continue

            max_spend = balance_usd * position_pct
            if max_spend < min_trade_usd:
                continue
            spend = min(max_spend, balance_usd * max_trade_pct)
            qty = spend / price if price else 0
            if qty <= 0:
                continue

            signals.append((
                symbol, OrderSide.BUY, qty,
                f"Entered on rebound setup: 24h {change_24h:.2f}% (dip) while market regime={regime}; downside momentum priced in, watching for continuation.",
                "gen6_rebound_entry",
            ))
            decisions.append({
                "symbol": symbol,
                "action": "entered_probe",
                "reason": "Entered on rebound after weakness; tight stop — will promote to protected/runner if strength follows.",
            })

    elif protective_entries and not any(s[1] == OrderSide.SELL for s in signals):
        decisions.append({
            "symbol": "",
            "action": "waiting_for_entry",
            "reason": "Weak/sloppy market — no new entries; managing open risk only.",
        })

    if any_runner:
        summary = "Runner mode active — wider trail while follow-through holds; trims on real giveback, not noise."
    elif protective_entries:
        summary = "Defensive: broad weakness; favoring exits and skipping new rebound entries."
    elif signals and any(s[1] == OrderSide.BUY for s in signals):
        summary = "Selective rebound entries; staged protect → runner on real strength."
    elif signals and any(s[1] == OrderSide.SELL for s in signals):
        summary = "Managing exits (stop, trail, weak-momentum, or time) — retain gains, free capital when stalled."
    elif at_daily_cap:
        summary = "Daily trade cap reached; standing down on new entries."
    else:
        summary = "Scanning dip-to-rebound setups; mixed markets slightly relaxed vs deep knives only."

    rollup = _rollup_leg_history(g6.get("leg_history", []))

    gen6_sells_usd = [
        float(t["realized_pnl_usd"])
        for t in (state.get("trades") or [])
        if str(t.get("side", "")).lower() == "sell" and t.get("realized_pnl_usd") is not None
    ]
    if gen6_sells_usd:
        avg_realized_usd = round(sum(gen6_sells_usd) / len(gen6_sells_usd), 4)
    else:
        avg_realized_usd = None

    evaluation_metrics = {
        "runner_activations": stats.get("runner_activations", 0),
        "protected_activations": stats.get("protected_activations", 0),
        "scaleouts": stats.get("scaleouts", 0),
        "exits_trailing": stats.get("exits_trailing", 0),
        "exits_timeout": stats.get("exits_timeout", 0),
        "exits_weak_momentum": stats.get("exits_weak_momentum", 0),
        "exits_runner_weak": stats.get("exits_runner_weak", 0),
        "exits_failed_rebound": stats.get("exits_failed_rebound", 0),
        "avg_realized_pnl_usd": avg_realized_usd,
        "gen6_scored_sell_count": len(gen6_sells_usd),
        **rollup,
    }

    context = {
        "strategy_summary": summary,
        "market_regime": regime,
        "market_avg_24h": avg_24h,
        "broad_weakness": broad_weak,
        "market_look": market_look,
        "any_runner": any_runner,
        "protective_entries": protective_entries,
        "position_snapshots": position_snapshots,
        "evaluation_metrics": evaluation_metrics,
        "last_exit": last_exit_this_cycle,
    }

    g6["last_context"] = {k: v for k, v in context.items() if k != "position_snapshots"}
    g6["position_snapshots"] = position_snapshots
    g6["evaluation_metrics"] = evaluation_metrics
    if last_exit_this_cycle:
        g6["last_exit"] = last_exit_this_cycle

    return signals, decisions, context
