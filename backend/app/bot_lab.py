"""
Strategy lab: one cycle = fetch prices once, then run Gen 1–6 in sequence with same snapshot.
Each gen has its own paper state and config. Status per gen is kept for the API.
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.time_toronto import count_trades_toronto_today, parse_trade_timestamp, utc_now
from app.lab_settings import (
    get_gen_config,
    get_all_gen_configs,
    get_starting_balance_for_gen,
    get_symbols_for_gen,
    get_price_update_interval_seconds,
)
from app.market import fetch_prices, get_cached_prices, set_cached_prices
from app.paper_engine import (
    load_state,
    save_state,
    execute_order,
    get_positions,
    reset_gen,
)
from app.strategies.gen1_baseline import get_signals as get_signals_gen1
from app.strategies.gen2_optimized import get_signals as get_signals_gen2
from app.strategies.gen3_adaptive import get_signals as get_signals_gen3
from app.strategies.gen4_ai_supervisor import get_signals as get_signals_gen4
from app.strategies.gen5_scalper import get_signals as get_signals_gen5
from app.news_sentiment import fetch_news_context
from app.openai_supervisor import get_supervisor_decision
from app.models import OrderSide

log = logging.getLogger(__name__)

# Per-gen status for API (last run time, trade count today, Gen 4 last decision/reasoning)
lab_status: dict[str, dict] = {
    "1": {"last_run": None, "trade_count_today": 0},
    "2": {"last_run": None, "trade_count_today": 0},
    "3": {"last_run": None, "trade_count_today": 0},
    "4": {"last_run": None, "trade_count_today": 0, "last_decision": None, "last_reasoning": None, "last_news_context": None},
    "5": {"last_run": None, "trade_count_today": 0},
    "6": {"last_run": None, "trade_count_today": 0},
}
lab_last_cycle: datetime | None = None


def _count_trades_today(state: dict) -> int:
    return count_trades_toronto_today(state)


def _last_trade_time_by_symbol(state: dict) -> dict[str, datetime]:
    out = {}
    for t in state.get("trades", []):
        dt = parse_trade_timestamp(t.get("timestamp"))
        if dt:
            sym = t.get("symbol", "")
            if sym and (sym not in out or dt > out[sym]):
                out[sym] = dt
    return out


MAX_DECISIONS_STORED = 100
MAX_GEN4_DECISION_HISTORY = 50

# Gen 4 hard safety overrides: code-level boundaries around the AI decision
ALL_RED_MEANINGFUL_WEAKNESS_AVG_24H = -2.0   # at least "limit" when all symbols red and avg 24h <= this
ALL_RED_SIGNIFICANT_DOWN_AVG_24H = -5.0      # force "block" when all symbols red and avg 24h <= this


def _build_market_summary_for_gen4(ticks: list) -> tuple[str, dict]:
    """Build a rich plain-language market summary and stats for the Gen 4 AI. Returns (summary_str, stats_dict)."""
    if not ticks:
        return "No market data.", {"average_24h": 0.0, "red_count": 0, "green_count": 0, "total_count": 0, "strongest_loser": 0.0, "strongest_gainer": 0.0, "all_red": False, "broad_weakness": False, "market_look": "unknown"}

    changes = [t.change_24h for t in ticks]
    n = len(changes)
    avg_24h = sum(changes) / n if n else 0.0
    red_count = sum(1 for c in changes if c < 0)
    green_count = n - red_count
    strongest_loser = min(changes) if changes else 0.0
    strongest_gainer = max(changes) if changes else 0.0
    all_red = red_count == n and n > 0
    # Broad weakness: most symbols red and average 24h meaningfully negative
    broad_weakness = (red_count >= (n + 1) // 2 and avg_24h < -0.5) or (all_red and avg_24h < -1.0)
    if avg_24h >= 0.5 and red_count <= 1:
        market_look = "stable"
    elif avg_24h <= -1.5 or (all_red and avg_24h < -1.0):
        market_look = "weak"
    else:
        market_look = "mixed"

    strongest_loser_sym = min(ticks, key=lambda t: t.change_24h)
    strongest_gainer_sym = max(ticks, key=lambda t: t.change_24h)
    per_symbol = "; ".join([f"{t.symbol.replace('USDT', '')} ${t.price:.0f} 24h {t.change_24h:+.2f}%" for t in ticks[:10]])

    summary_lines = [
        f"Tracked symbols: {n}. Average 24h change: {avg_24h:+.2f}%.",
        f"Red: {red_count}, Green: {green_count}.",
        f"Strongest loser: {strongest_loser_sym.symbol.replace('USDT', '')} {strongest_loser:+.2f}%.",
        f"Strongest gainer: {strongest_gainer_sym.symbol.replace('USDT', '')} {strongest_gainer_sym.change_24h:+.2f}%.",
        f"Broad market weakness: {'yes' if broad_weakness else 'no'}.",
        f"Market character: {market_look}.",
        f"Per-symbol: {per_symbol}.",
    ]
    summary_str = " ".join(summary_lines)

    stats = {
        "average_24h": avg_24h,
        "red_count": red_count,
        "green_count": green_count,
        "total_count": n,
        "strongest_loser": strongest_loser,
        "strongest_gainer": strongest_gainer,
        "strongest_loser_symbol": strongest_loser_sym.symbol.replace("USDT", ""),
        "strongest_gainer_symbol": strongest_gainer_sym.symbol.replace("USDT", ""),
        "all_red": all_red,
        "broad_weakness": broad_weakness,
        "market_look": market_look,
    }
    return summary_str, stats


def _apply_safety_overrides(decision_dict: dict, stats: dict) -> tuple[dict, bool, str | None]:
    """Apply code-level safety overrides. Returns (decision_dict, override_applied, override_type)."""
    decision = (decision_dict.get("decision") or "limit").lower()
    reasoning = decision_dict.get("reasoning", "")
    all_red = stats.get("all_red", False)
    avg_24h = stats.get("average_24h", 0.0)
    override_type: str | None = None

    if all_red and avg_24h <= ALL_RED_SIGNIFICANT_DOWN_AVG_24H:
        return (
            {
                **decision_dict,
                "decision": "block",
                "reasoning": f"{reasoning} [Override: all symbols significantly down (avg 24h {avg_24h:.1f}%) → block.]",
            },
            True,
            "all_red_significant_down",
        )
    if all_red and avg_24h <= ALL_RED_MEANINGFUL_WEAKNESS_AVG_24H and decision == "allow":
        return (
            {
                **decision_dict,
                "decision": "limit",
                "reasoning": f"{reasoning} [Override: all symbols red, meaningful weakness (avg 24h {avg_24h:.1f}%) → at least limit.]",
            },
            True,
            "all_red_meaningful_weakness",
        )
    return (decision_dict, False, None)


def _run_gen(gen_id: str, ticks: list, config: dict, state: dict, prices: dict):
    state.setdefault("decisions", [])
    gen5_context: dict | None = None
    gen6_context: dict | None = None
    if gen_id == "1":
        result = get_signals_gen1(ticks, state["balance_usd"], state["positions"], config, _last_trade_time_by_symbol(state))
        signals = result if isinstance(result, list) else result[0]
        decisions: list = []
    elif gen_id == "2":
        result = get_signals_gen2(ticks, state["balance_usd"], state["positions"], config, _last_trade_time_by_symbol(state))
        signals = result if isinstance(result, list) else result[0]
        decisions = []
    elif gen_id == "3":
        signals, decisions = get_signals_gen3(ticks, state["balance_usd"], state["positions"], config, _last_trade_time_by_symbol(state))
    elif gen_id == "5":
        signals, gen5_context = get_signals_gen5(ticks, state["balance_usd"], state["positions"], config, _last_trade_time_by_symbol(state), _count_trades_today(state))
        decisions = []
    elif gen_id == "6":
        signals, decisions, gen6_context = get_signals_gen6(
            ticks,
            state["balance_usd"],
            state["positions"],
            config,
            _last_trade_time_by_symbol(state),
            _count_trades_today(state),
            state,
        )
    else:
        return state
    for symbol, side, quantity, reason, world_signal in signals:
        execute_order(state, gen_id, symbol, side, quantity, prices.get(symbol, 0), reason, config, world_signal)
    now_iso = utc_now().isoformat()
    for d in decisions:
        state["decisions"].append({"timestamp": now_iso, "symbol": d.get("symbol", ""), "action": d.get("action", "skip"), "reason": d.get("reason", "")})
    state["decisions"] = state["decisions"][-MAX_DECISIONS_STORED:]
    if gen_id == "5" and gen5_context:
        state["gen5_strategy_summary"] = gen5_context.get("strategy_summary", "")
        state["gen5_activity_mode"] = gen5_context.get("activity_mode", "active")
        state["gen5_market_avg_24h"] = gen5_context.get("market_avg_24h")
        state["gen5_broad_weakness"] = gen5_context.get("broad_weakness", False)
    if gen_id == "6" and gen6_context:
        state["gen6_strategy_summary"] = gen6_context.get("strategy_summary", "")
        state["gen6_market_regime"] = gen6_context.get("market_regime", "mixed")
        state["gen6_market_avg_24h"] = gen6_context.get("market_avg_24h")
        state["gen6_broad_weakness"] = gen6_context.get("broad_weakness", False)
        state["gen6_market_look"] = gen6_context.get("market_look", "mixed")
        state["gen6_any_runner"] = gen6_context.get("any_runner", False)
        state["gen6_protective_entries"] = gen6_context.get("protective_entries", False)
        state["gen6_position_snapshots"] = gen6_context.get("position_snapshots", [])
        state["gen6_evaluation_metrics"] = gen6_context.get("evaluation_metrics", {})
        le = gen6_context.get("last_exit")
        state["gen6_last_exit"] = le
        if le:
            state["gen6_last_exit_reason"] = le.get("reason")
            state["gen6_last_exit_tag"] = le.get("tag")
    return state


async def run_lab_cycle():
    """Fetch prices once, then run each enabled gen in sequence with same ticks."""
    global lab_last_cycle
    log.info("Lab cycle begin")
    try:
        await _run_lab_cycle_impl()
        log.info("Lab cycle completed successfully")
    except Exception:
        # Do not re-raise: keep APScheduler running; full traceback is logged once.
        log.exception("Lab cycle failed: unhandled error")


async def _run_lab_cycle_impl():
    global lab_last_cycle
    configs = get_all_gen_configs()
    symbols = []
    for c in configs.values():
        symbols.extend(c.get("symbols") or [])
    symbols = list(dict.fromkeys(symbols)) or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    ticks = await fetch_prices(symbols)
    if not ticks:
        ticks = get_cached_prices()
    if not ticks:
        ticks = get_cached_prices(allow_stale=True)
    if not ticks:
        log.warning(
            "Lab cycle skipped: no market ticks (CoinGecko returned nothing and cache is empty). "
            "lab_last_cycle will not update until prices are available."
        )
        return

    prices = {t.symbol: t.price for t in ticks}
    lab_last_cycle = utc_now()

    # Gen 4: fetch news, build rich market summary, get AI decision, then apply hard safety overrides
    news_context = await fetch_news_context()
    ticks_for_summary = ticks[:10] if len(ticks) > 10 else ticks
    market_summary, market_stats = _build_market_summary_for_gen4(ticks_for_summary)
    supervisor_decision = await get_supervisor_decision(market_summary, news_context)
    supervisor_decision, override_applied, override_type = _apply_safety_overrides(supervisor_decision, market_stats)
    ai_source = supervisor_decision.get("source", "api")
    if ai_source == "fallback":
        decision_source = "fallback_limit"
    elif override_applied:
        decision_source = "ai_plus_override"
    else:
        decision_source = "ai_only"
    lab_status["4"]["last_decision"] = supervisor_decision.get("decision")
    lab_status["4"]["last_reasoning"] = supervisor_decision.get("reasoning")
    lab_status["4"]["last_news_context"] = news_context[:500]

    for gen_id in ("1", "2", "3", "4", "5", "6"):
        config = configs.get(gen_id) or get_gen_config(gen_id)
        if not config.get("enabled", True):
            continue
        initial = get_starting_balance_for_gen(gen_id)
        state = load_state(gen_id, initial)
        gen_ticks = [t for t in ticks if t.symbol in (config.get("symbols") or [])]
        if not gen_ticks:
            gen_ticks = ticks

        if gen_id == "4":
            signals, _ = await get_signals_gen4(
                gen_ticks, state["balance_usd"], state["positions"], config,
                _last_trade_time_by_symbol(state), supervisor_decision,
            )
            reasoning = supervisor_decision.get("reasoning", "").strip()
            guidance = supervisor_decision.get("guidance", "").strip()
            ai_suffix = " ".join(filter(None, [reasoning, guidance])).strip()
            for symbol, side, quantity, reason, world_signal in signals:
                if ai_suffix:
                    reason = f"{reason}. AI: {ai_suffix}"
                execute_order(state, gen_id, symbol, side, quantity, prices.get(symbol, 0), reason, config, world_signal)
            # Persist AI decision, override info, and market stats so status API can show them (e.g. after restart)
            state["last_ai_decision"] = supervisor_decision.get("decision")
            state["last_ai_reasoning"] = supervisor_decision.get("reasoning")
            state["last_ai_guidance"] = supervisor_decision.get("guidance")
            state["last_ai_news_context"] = news_context[:500] if news_context else None
            state["last_ai_override_applied"] = override_applied
            state["last_ai_override_type"] = override_type
            state["last_ai_decision_source"] = decision_source
            state["last_ai_market_stats"] = market_stats
            # Append to Gen 4 decision history for recent-decision log
            state.setdefault("gen4_decision_history", [])
            reasoning_full = supervisor_decision.get("reasoning") or ""
            reasoning_summary = (reasoning_full[:120] + "…") if len(reasoning_full) > 120 else reasoning_full
            state["gen4_decision_history"].append({
                "timestamp": utc_now().isoformat(),
                "decision": supervisor_decision.get("decision"),
                "decision_source": decision_source,
                "override_applied": override_applied,
                "override_type": override_type,
                "average_24h": market_stats.get("average_24h"),
                "red_count": market_stats.get("red_count"),
                "green_count": market_stats.get("green_count"),
                "broad_weakness": market_stats.get("broad_weakness"),
                "market_look": market_stats.get("market_look"),
                "reasoning_summary": reasoning_summary or "",
            })
            state["gen4_decision_history"] = state["gen4_decision_history"][-MAX_GEN4_DECISION_HISTORY:]
        else:
            state = _run_gen(gen_id, gen_ticks, config, state, prices)

        lab_status[gen_id]["last_run"] = utc_now()
        lab_status[gen_id]["trade_count_today"] = _count_trades_today(state)
        save_state(gen_id, state)


def get_gen_status(gen_id: str, state: dict, prices: dict, initial_balance: float) -> dict:
    positions = get_positions(state, prices)
    balance = state["balance_usd"]
    total_value = balance + sum(p.value_usd for p in positions)
    pnl_usd = total_value - initial_balance
    pnl_pct = (pnl_usd / initial_balance * 100) if initial_balance else 0
    return {
        "gen_id": gen_id,
        "balance_usd": balance,
        "total_value_usd": total_value,
        "total_pnl_usd": pnl_usd,
        "total_pnl_percent": pnl_pct,
        "positions_count": len(positions),
        "trade_count_today": lab_status.get(gen_id, {}).get("trade_count_today", 0),
        "last_run": lab_status.get(gen_id, {}).get("last_run"),
        "positions": positions,
        "state": state,
    }
