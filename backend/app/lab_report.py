"""
Build structured Crypto Strategy Lab export reports (JSON / CSV / MD / ZIP).
Uses persisted paper state and lab_status — no UI scraping.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

from app.bot_lab import lab_status, lab_last_cycle
from app.lab_settings import get_gen_config, get_all_gen_configs, get_starting_balance_for_gen
from app.market import get_cached_prices
from app.paper_engine import load_state, get_positions
from app.time_toronto import count_trades_toronto_today, parse_trade_timestamp, utc_now

LAB_GEN_IDS = ("1", "2", "3", "4", "5", "6", "7")

RANGE_ALIASES = {
    "all_time": None,
    "last_1h": timedelta(hours=1),
    "last_24h": timedelta(hours=24),
    "last_7d": timedelta(days=7),
}


def _r2(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, dict):
        return {k: _r2(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_r2(v) for v in x]
    return x


def _since_dt(range_key: str) -> datetime | None:
    delta = RANGE_ALIASES.get(range_key)
    if delta is None:
        return None
    return utc_now() - delta


def _in_range(ts_str: str | None, since: datetime | None) -> bool:
    if since is None:
        return True
    dt = parse_trade_timestamp(ts_str)
    if not dt:
        return True
    return dt >= since


def _exit_reason_from_world_signal(ws: str | None, reason: str = "") -> str:
    if not ws and not reason:
        return "unknown"
    w = (ws or "").lower()
    r = (reason or "").lower()
    if "gen6_trailing" in w:
        return "trailing_stop"
    if "gen6_time" in w or "hard_time" in w or "time exit" in r or "time cap" in r:
        return "timeout"
    if "gen6_weak" in w or "runner_weak" in w or "weak momentum" in r:
        return "weak_momentum"
    if "gen6_stop" in w or "stop loss" in r or "failed rebound" in r:
        return "hard_stop"
    if "gen6_scaleout" in w or "scale-out" in r or "partial scale" in r:
        return "scale_out"
    if "gen7_quick" in w or "gen7_stall_take" in w:
        return "gen7_quick_profit"
    if "gen7_stop" in w:
        return "gen7_stop"
    if "gen7_timeout" in w or "gen7_hard_cap" in w:
        return "gen7_timeout"
    if "gen7_stall" in w:
        return "gen7_stall"
    if "gen7_momentum" in w or "gen7_tape_weak" in w:
        return "gen7_momentum_loss"
    if "take_profit" in w or "scalp tp" in r or "tp:" in r:
        return "take_profit"
    if "stop_loss" in w or "scalp sl" in r or "sl:" in r:
        return "stop_loss"
    if "price_rise" in w or "quick exit" in r:
        return "price_rise_exit"
    return "other"


def _market_snapshot_from_ticks(ticks: list) -> dict[str, Any]:
    if not ticks:
        return {
            "btc_price": None,
            "eth_price": None,
            "sol_price": None,
            "avg_24h_change_pct": None,
            "red_count": None,
            "green_count": None,
            "broad_weakness": None,
            "market_character": "unknown",
        }
    sym_price = {t.symbol: float(t.price) for t in ticks}
    changes = [float(t.change_24h) for t in ticks]
    n = len(changes)
    avg = sum(changes) / n if n else 0.0
    red = sum(1 for c in changes if c < 0)
    green = n - red
    all_red = red == n and n > 0
    broad = (red >= (n + 1) // 2 and avg < -0.5) or (all_red and avg < -1.0)
    if avg >= 0.5 and red <= 1:
        look = "stable"
    elif avg <= -1.5 or (all_red and avg < -1.0):
        look = "weak"
    else:
        look = "mixed"
    if avg >= 0.75 and not broad:
        char = "strong"
    elif look == "weak" or broad:
        char = "weak"
    elif look == "stable":
        char = "stable"
    else:
        char = "mixed"
    return {
        "btc_price": sym_price.get("BTCUSDT"),
        "eth_price": sym_price.get("ETHUSDT"),
        "sol_price": sym_price.get("SOLUSDT"),
        "avg_24h_change_pct": round(avg, 2),
        "red_count": red,
        "green_count": green,
        "broad_weakness": bool(broad),
        "market_character": char,
    }


def _fifo_closed_sells(trades: list[dict]) -> list[dict]:
    """Chronological trades → list of sell events with matched avg entry & hold minutes."""
    from collections import defaultdict

    stacks: dict[str, list[dict]] = defaultdict(list)
    out: list[dict] = []
    for t in sorted(trades, key=lambda x: parse_trade_timestamp(x.get("timestamp")) or UTC_MIN):
        sym = t.get("symbol") or ""
        side = (t.get("side") or "").lower()
        qty = float(t.get("quantity") or 0)
        price = float(t.get("price") or 0)
        ts = parse_trade_timestamp(t.get("timestamp"))
        if side == "buy" and qty > 0:
            stacks[sym].append({"qty": qty, "price": price, "ts": ts})
        elif side == "sell" and qty > 0:
            rem = qty
            cost = 0.0
            qtot = 0.0
            entry_ts: datetime | None = None
            while rem > 1e-9 and stacks[sym]:
                lot = stacks[sym][0]
                take = min(rem, lot["qty"])
                cost += take * lot["price"]
                qtot += take
                lt = lot["ts"]
                if lt and (entry_ts is None or lt < entry_ts):
                    entry_ts = lt
                lot["qty"] -= take
                if lot["qty"] < 1e-9:
                    stacks[sym].pop(0)
                rem -= take
            wavg = cost / qtot if qtot > 0 else price
            hold_min = None
            if ts and entry_ts:
                hold_min = round((ts - entry_ts).total_seconds() / 60.0, 2)
            pnl_pct = ((price - wavg) / wavg * 100) if wavg > 0 else None
            realized = t.get("realized_pnl_usd")
            if realized is not None:
                try:
                    realized = float(realized)
                except (TypeError, ValueError):
                    realized = None
            out.append({
                "symbol": sym.replace("USDT", ""),
                "entry_price": round(wavg, 2),
                "exit_price": round(price, 2),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "hold_minutes": hold_min,
                "exit_reason": _exit_reason_from_world_signal(t.get("world_signal"), t.get("reason", "")),
                "peak_pnl_pct": None,
                "giveback_pct": None,
                "timestamp": t.get("timestamp"),
                "realized_pnl_usd": round(realized, 2) if realized is not None else None,
            })
    return out


UTC_MIN = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _filter_trades(trades: list[dict], since: datetime | None) -> list[dict]:
    if since is None:
        return list(trades)
    return [t for t in trades if _in_range(t.get("timestamp"), since)]


def _performance_from_state(
    state: dict,
    positions: list,
    initial: float,
    filtered_trades: list[dict],
    all_trades: list[dict],
) -> dict[str, Any]:
    balance = float(state.get("balance_usd", 0))
    total_value = balance + sum(float(p.value_usd) for p in positions)
    unrealized = sum(float(p.pnl_usd) for p in positions)
    realized = total_value - initial - unrealized
    total_pnl = total_value - initial
    total_pnl_pct = (total_pnl / initial * 100) if initial else 0.0

    sells_scored = [
        t
        for t in filtered_trades
        if (t.get("side") or "").lower() == "sell" and t.get("realized_pnl_usd") is not None
    ]
    wins = sum(1 for t in sells_scored if float(t.get("realized_pnl_usd") or 0) > 0)
    win_rate = (wins / len(sells_scored) * 100) if sells_scored else None

    realized_list = [
        float(t["realized_pnl_usd"])
        for t in sells_scored
        if t.get("realized_pnl_usd") is not None
    ]
    best_trade = max(realized_list) if realized_list else None
    worst_trade = min(realized_list) if realized_list else None

    n_ft = len(filtered_trades)
    avg_trade_pnl = (total_pnl / n_ft) if n_ft else None

    return {
        "starting_balance": round(initial, 2),
        "cash": round(balance, 2),
        "portfolio_value": round(total_value, 2),
        "total_equity": round(total_value, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "total_trades": n_ft,
        "trades_today": None,
        "avg_trade_pnl": round(avg_trade_pnl, 2) if avg_trade_pnl is not None else None,
        "best_trade": round(best_trade, 2) if best_trade is not None else None,
        "worst_trade": round(worst_trade, 2) if worst_trade is not None else None,
    }


def _bot_status(gen_id: str, state: dict, config: dict, positions: list) -> dict[str, Any]:
    enabled = config.get("enabled", True)
    last_trade_at = None
    trades = state.get("trades", [])
    if trades:
        last_trade_at = trades[-1].get("timestamp")

    last_cycle_at = None
    lr = lab_status.get(gen_id, {}).get("last_run")
    if lr is not None:
        if isinstance(lr, datetime):
            last_cycle_at = lr.isoformat().replace("+00:00", "Z")
        else:
            last_cycle_at = str(lr)

    n_pos = len(positions)
    if not enabled:
        st = "waiting"
    elif gen_id == "4" and (state.get("last_ai_decision") or "").lower() == "block" and n_pos == 0:
        st = "blocked"
    elif n_pos > 0:
        st = "holding"
    else:
        st = "waiting"

    last_reason = ""
    last_action = "none"
    if trades:
        lt = trades[-1]
        last_action = f"{(lt.get('side') or '').upper()} {lt.get('symbol', '')}"
        last_reason = (lt.get("reason") or "")[:500]

    return {
        "state": st,
        "last_action": last_action,
        "last_reason": last_reason,
        "last_trade_at": last_trade_at,
        "last_cycle_at": last_cycle_at,
        "enabled": enabled,
    }


def _decision_summary(gen_id: str, state: dict) -> dict[str, Any]:
    if gen_id == "4":
        return {
            "latest_decision": state.get("last_ai_decision"),
            "latest_reason": (state.get("last_ai_reasoning") or "")[:800],
            "decision_source": state.get("last_ai_decision_source") or "rules",
        }
    if gen_id == "6":
        return {
            "latest_decision": "momentum_rider_cycle",
            "latest_reason": state.get("gen6_strategy_summary") or "",
            "decision_source": "rules",
        }
    if gen_id == "5":
        return {
            "latest_decision": state.get("gen5_activity_mode") or "active",
            "latest_reason": state.get("gen5_strategy_summary") or "",
            "decision_source": "rules",
        }
    if gen_id == "7":
        return {
            "latest_decision": state.get("gen7_operational_state") or "scanning",
            "latest_reason": state.get("gen7_strategy_summary") or "",
            "decision_source": "rules",
        }
    return {
        "latest_decision": None,
        "latest_reason": "",
        "decision_source": "rules",
    }


def _gen7_metrics_block(state: dict) -> dict[str, Any] | None:
    ev = state.get("gen7_evaluation_metrics") or {}
    if not ev and not state.get("gen7"):
        return None

    def _i(k: str) -> int:
        v = ev.get(k)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    return {
        "micro_entries": _i("gen7_entries"),
        "exits_quick_profit": _i("gen7_exits_quick_profit"),
        "exits_stop": _i("gen7_exits_stop"),
        "exits_timeout": _i("gen7_exits_timeout"),
        "exits_stall": _i("gen7_exits_stall"),
        "exits_momentum": _i("gen7_exits_momentum"),
        "operational_state": ev.get("operational_state"),
        "regime": ev.get("regime"),
    }


def _gen6_metrics_block(state: dict) -> dict[str, Any] | None:
    if not state.get("gen6"):
        return None
    ev = state.get("gen6_evaluation_metrics") or {}
    def _f(k: str) -> float | None:
        v = ev.get(k)
        if v is None:
            return None
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None

    return {
        "runner_activations": int(ev.get("runner_activations", 0)),
        "protected_activations": int(ev.get("protected_activations", 0)),
        "scale_out_count": int(ev.get("scaleouts", 0)),
        "trailing_exits": int(ev.get("exits_trailing", 0)),
        "timeout_exits": int(ev.get("exits_timeout", 0)),
        "weak_exits": int(ev.get("exits_weak_momentum", 0)) + int(ev.get("exits_runner_weak", 0)),
        "failed_rebounds": int(ev.get("exits_failed_rebound", 0)),
        "avg_peak_pnl": _f("avg_peak_pnl_pct"),
        "avg_realized_pnl": _f("avg_realized_pnl_usd"),
        "avg_giveback": _f("avg_giveback_pct"),
    }


def _positions_report(gen_id: str, state: dict, positions: list, price_map: dict[str, float]) -> list[dict]:
    g6_snaps = {s["symbol"]: s for s in (state.get("gen6_position_snapshots") or [])} if gen_id == "6" else {}
    out = []
    for p in positions:
        sym = p.symbol
        base = sym.replace("USDT", "")
        if gen_id == "6":
            snap = g6_snaps.get(sym, {})
        elif gen_id == "7":
            snap = g7_snaps.get(sym, {})
        else:
            snap = {}
        entry = float(p.avg_price)
        cur = float(p.current_price)
        pnl_pct = float(p.pnl_percent)
        peak = snap.get("max_pnl_pct_seen", snap.get("pnl_pct", pnl_pct))
        dd = snap.get("drawdown_from_peak_pct", 0)
        hold_min = None
        trades = state.get("trades", [])
        last_buy_ts = None
        for t in reversed(trades):
            if t.get("symbol") == sym and (t.get("side") or "").lower() == "buy":
                last_buy_ts = parse_trade_timestamp(t.get("timestamp"))
                break
        now = utc_now()
        if last_buy_ts:
            hold_min = round((now - last_buy_ts).total_seconds() / 60.0, 2)
        out.append({
            "symbol": base,
            "entry_price": round(entry, 2),
            "current_price": round(cur, 2),
            "pnl_pct": round(pnl_pct, 2),
            "peak_pnl_pct": round(float(peak), 2) if peak is not None else round(pnl_pct, 2),
            "drawdown_from_peak_pct": round(float(dd), 2) if dd is not None else None,
            "holding_time_minutes": hold_min,
            "stage": snap.get("stage") or ("runner_mode" if snap.get("runner_active") else "open"),
            "runner_active": bool(snap.get("runner_active", False)),
            "protected": bool(snap.get("protected", pnl_pct >= 0.3)),
            "scaled_out": bool(snap.get("scaled_out", False)),
            "micro_cycles_held": snap.get("cycles_held") if gen_id == "7" else None,
        })
    return out


def _merge_leg_history_for_peaks(state: dict, closed_sells: list[dict]) -> None:
    """Attach peak/giveback from gen6 leg_history for recent closed sells (best-effort)."""
    hist = (state.get("gen6") or {}).get("leg_history") or []
    for c in closed_sells:
        sym = c.get("symbol") or ""
        for h in reversed(hist):
            if h.get("partial"):
                continue
            hs = (h.get("symbol") or "").replace("USDT", "")
            if hs == sym:
                if h.get("peak_pnl_pct") is not None:
                    c["peak_pnl_pct"] = round(float(h["peak_pnl_pct"]), 2)
                if h.get("giveback_pct") is not None:
                    c["giveback_pct"] = round(float(h["giveback_pct"]), 2)
                break


def build_lab_report(range_key: str = "all_time") -> dict[str, Any]:
    if range_key not in RANGE_ALIASES:
        range_key = "all_time"
    since = _since_dt(range_key)
    now = utc_now()
    ticks = get_cached_prices(allow_stale=True)
    price_map = {t.symbol: float(t.price) for t in ticks}

    time_from = None
    time_to = now.isoformat().replace("+00:00", "Z")
    if since:
        time_from = since.isoformat().replace("+00:00", "Z")

    bots: list[dict] = []
    configs = get_all_gen_configs()

    for gen_id in LAB_GEN_IDS:
        config = configs.get(gen_id) or get_gen_config(gen_id)
        initial = get_starting_balance_for_gen(gen_id)
        state = load_state(gen_id, initial)
        all_trades = state.get("trades", [])
        filtered = _filter_trades(all_trades, since)
        positions_objs = get_positions(state, price_map)

        perf = _performance_from_state(state, positions_objs, initial, filtered, all_trades)
        perf["trades_today"] = count_trades_toronto_today(state)

        bot_id = f"gen{gen_id}"
        bot_name = f"Gen {gen_id}: {config.get('label', 'Bot')}"

        closed_all = _fifo_closed_sells(all_trades)
        closed_filtered = [c for c in closed_all if _in_range(c.get("timestamp"), since)]
        closed_filtered.sort(key=lambda x: parse_trade_timestamp(x.get("timestamp")) or UTC_MIN, reverse=True)
        if gen_id == "6":
            _merge_leg_history_for_peaks(state, closed_filtered)
        recent_trades = closed_filtered[:25]
        for c in recent_trades:
            c.pop("timestamp", None)
            c.pop("realized_pnl_usd", None)

        bot = {
            "bot_id": bot_id,
            "bot_name": bot_name,
            "status": _bot_status(gen_id, state, config, positions_objs),
            "performance": perf,
            "positions": _positions_report(gen_id, state, positions_objs, price_map),
            "recent_trades": recent_trades,
            "decision_summary": _decision_summary(gen_id, state),
            "gen6_metrics": _gen6_metrics_block(state) if gen_id == "6" else None,
            "gen7_metrics": _gen7_metrics_block(state) if gen_id == "7" else None,
        }
        bots.append(bot)

    perf_list = [(b["bot_id"], b["performance"]["total_pnl"], b["performance"].get("win_rate_pct")) for b in bots]
    ranked_pnl = sorted(perf_list, key=lambda x: x[1], reverse=True)
    wr_valid = [(bid, wr) for bid, _, wr in perf_list if wr is not None]
    ranked_wr = sorted(wr_valid, key=lambda x: x[1], reverse=True) if wr_valid else []
    most_trades = max(bots, key=lambda b: b["performance"]["total_trades"])

    comparison = {
        "ranked_by_total_pnl": [x[0] for x in ranked_pnl],
        "ranked_by_win_rate_pct": [x[0] for x in ranked_wr],
        "most_total_trades_bot_id": most_trades["bot_id"],
        "rows": [
            {
                "bot_id": b["bot_id"],
                "total_pnl": b["performance"]["total_pnl"],
                "total_pnl_pct": b["performance"]["total_pnl_pct"],
                "win_rate_pct": b["performance"]["win_rate_pct"],
                "total_trades": b["performance"]["total_trades"],
            }
            for b in bots
        ],
    }

    notes: list[str] = []
    if ranked_pnl:
        notes.append(f"Highest total P&L in this range: {ranked_pnl[0][0]} (${ranked_pnl[0][1]:.2f}).")
    if ranked_wr:
        notes.append(f"Highest win rate (scored sells): {ranked_wr[0][0]} ({ranked_wr[0][1]:.1f}%).")
    notes.append(f"Most fills in range: {most_trades['bot_id']} ({most_trades['performance']['total_trades']} trades).")
    mw = _market_snapshot_from_ticks(ticks)
    if mw.get("market_character") == "weak":
        notes.append("Market snapshot looks weak — expect defensive behavior from supervised / rider / Gen 7 micro bots.")
    elif mw.get("market_character") == "strong":
        notes.append("Market snapshot favorable — momentum-style bots may show wider trails; Gen 7 may be more active on micro setups.")
    elif mw.get("market_character") == "mixed":
        notes.append("Mixed tape — Gen 7 (micro-movement trader) is tuned for repeated small opportunities in choppy conditions.")

    lc = lab_last_cycle
    last_cycle_iso = lc.isoformat().replace("+00:00", "Z") if isinstance(lc, datetime) else None

    report = {
        "report_type": "crypto_strategy_lab",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "lab_last_cycle_at": last_cycle_iso,
        "time_range": {
            "preset": range_key,
            "from": time_from,
            "to": time_to,
        },
        "market_snapshot": _market_snapshot_from_ticks(ticks),
        "bots": bots,
        "comparison": comparison,
        "analysis_notes": notes,
    }
    return _r2(report)


def report_to_csv(report: dict) -> str:
    buf = io.StringIO()
    cols = [
        "bot_id",
        "total_pnl",
        "total_pnl_pct",
        "win_rate",
        "total_trades",
        "trades_today",
        "avg_trade_pnl",
        "best_trade",
        "worst_trade",
        "open_positions",
        "exposure_pct",
        "latest_decision",
        "latest_reason",
    ]
    w = csv.writer(buf)
    w.writerow(cols)
    for b in report["bots"]:
        p = b["performance"]
        st = b["status"]
        ds = b["decision_summary"]
        npos = len(b["positions"])
        exp = sum(x["current_price"] * 0 for x in b["positions"])
        tv = p.get("portfolio_value") or 0
        cash = p.get("cash") or 0
        exposure_usd = max(0.0, float(tv) - float(cash))
        exp_pct = (exposure_usd / float(tv) * 100) if tv else 0.0
        w.writerow(
            [
                b["bot_id"],
                p.get("total_pnl"),
                p.get("total_pnl_pct"),
                p.get("win_rate_pct") if p.get("win_rate_pct") is not None else "",
                p.get("total_trades"),
                p.get("trades_today"),
                p.get("avg_trade_pnl") if p.get("avg_trade_pnl") is not None else "",
                p.get("best_trade") if p.get("best_trade") is not None else "",
                p.get("worst_trade") if p.get("worst_trade") is not None else "",
                npos,
                round(exp_pct, 2),
                ds.get("latest_decision") or "",
                (ds.get("latest_reason") or "")[:200].replace("\n", " "),
            ]
        )
    return buf.getvalue()


def report_to_markdown(report: dict) -> str:
    lines: list[str] = [
        "# Crypto Strategy Lab Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Range:** {report['time_range']['preset']}"
        + (f" ({report['time_range']['from']} → {report['time_range']['to']})" if report["time_range"]["from"] else " (all time)"),
        "",
        "## Market Overview",
        "",
    ]
    m = report["market_snapshot"]
    lines.extend(
        [
            f"- **BTC:** ${m.get('btc_price')}" if m.get("btc_price") is not None else "- **BTC:** —",
            f"- **ETH:** ${m.get('eth_price')}" if m.get("eth_price") is not None else "- **ETH:** —",
            f"- **SOL:** ${m.get('sol_price')}" if m.get("sol_price") is not None else "- **SOL:** —",
            f"- **Avg 24h change (tracked):** {m.get('avg_24h_change_pct')}%",
            f"- **Red / Green symbols:** {m.get('red_count')} / {m.get('green_count')}",
            f"- **Broad weakness:** {m.get('broad_weakness')}",
            f"- **Character:** {m.get('market_character')}",
            "",
            "## Bot comparison (key metrics)",
            "",
            "| Bot | P&L | P&L % | Win % | Trades | Open pos |",
            "|-----|-----|-------|-------|--------|----------|",
        ]
    )
    for b in report["bots"]:
        p = b["performance"]
        wr = p.get("win_rate_pct")
        wrs = f"{wr}%" if wr is not None else "—"
        lines.append(
            f"| {b['bot_id']} | ${p.get('total_pnl')} | {p.get('total_pnl_pct')}% | {wrs} | {p.get('total_trades')} | {len(b['positions'])} |"
        )
    lines.extend(["", "## Key insights (auto)", ""])
    for n in report.get("analysis_notes", []):
        lines.append(f"- {n}")
    lines.append("")

    for b in report["bots"]:
        p = b["performance"]
        ds = b["decision_summary"]
        st = b["status"]
        lines.extend(
            [
                f"## {b['bot_name']} (`{b['bot_id']}`)",
                "",
                "### Status",
                f"- State: **{st.get('state')}** (enabled: {st.get('enabled')})",
                f"- Last action: {st.get('last_action')}",
                f"- Last trade at: {st.get('last_trade_at') or '—'}",
                f"- Last lab cycle at: {st.get('last_cycle_at') or '—'}",
                "",
                "### Performance",
                f"- Total P&L: **${p.get('total_pnl')}** ({p.get('total_pnl_pct')}%)",
                f"- Realized / Unrealized: ${p.get('realized_pnl')} / ${p.get('unrealized_pnl')}",
                f"- Win rate (scored sells): {p.get('win_rate_pct') if p.get('win_rate_pct') is not None else '—'}%",
                f"- Trades in range: {p.get('total_trades')} (today all-time: {p.get('trades_today')})",
                f"- Avg trade P&L (approx): {p.get('avg_trade_pnl')}",
                f"- Best / worst realized sell: {p.get('best_trade')} / {p.get('worst_trade')}",
                "",
                "### Decision / reasoning",
                f"- Latest: `{ds.get('latest_decision')}` ({ds.get('decision_source')})",
                f"- Summary: {ds.get('latest_reason') or '—'}",
                "",
            ]
        )
        if b["positions"]:
            lines.append("### Open positions")
            for pos in b["positions"]:
                lines.append(
                    f"- **{pos['symbol']}** @ {pos['entry_price']} → {pos['current_price']} "
                    f"({pos['pnl_pct']}%) stage={pos.get('stage')} runner={pos.get('runner_active')}"
                )
            lines.append("")
        else:
            lines.append("### Open positions\n- None\n")

        if b["recent_trades"]:
            lines.append("### Recent closed sells (FIFO matched, newest first)")
            for rt in b["recent_trades"][:10]:
                lines.append(
                    f"- {rt.get('symbol')}: entry {rt.get('entry_price')} exit {rt.get('exit_price')} "
                    f"P&L% {rt.get('pnl_pct')} hold {rt.get('hold_minutes')}m reason={rt.get('exit_reason')}"
                )
            lines.append("")
        if b.get("gen6_metrics"):
            g = b["gen6_metrics"]
            lines.append("### Gen 6 metrics")
            lines.append(f"- Runner / protected activations: {g.get('runner_activations')} / {g.get('protected_activations')}")
            lines.append(
                f"- Exits — trail: {g.get('trailing_exits')}, timeout: {g.get('timeout_exits')}, weak: {g.get('weak_exits')}, stop: {g.get('failed_rebounds')}"
            )
            lines.append("")
        if b.get("gen7_metrics"):
            g7 = b["gen7_metrics"]
            lines.append("### Gen 7 metrics (micro-trader)")
            lines.append(
                f"- State / regime: {g7.get('operational_state')} / {g7.get('regime')}"
            )
            lines.append(
                f"- Entries (session counter): {g7.get('micro_entries')} | "
                f"exits — quick: {g7.get('exits_quick_profit')}, stop: {g7.get('exits_stop')}, "
                f"timeout: {g7.get('exits_timeout')}, stall: {g7.get('exits_stall')}, momentum: {g7.get('exits_momentum')}"
            )
            lines.append("")

    lines.append("---\n*Upload `report.json` into ChatGPT for deeper cross-bot analysis.*\n")
    return "\n".join(lines)


def build_zip_bytes(report: dict) -> tuple[bytes, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"crypto_lab_report_{ts}.zip"
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.json", json.dumps(report, indent=2))
        zf.writestr("report.csv", report_to_csv(report))
        zf.writestr("report.md", report_to_markdown(report))
    return bio.getvalue(), filename
