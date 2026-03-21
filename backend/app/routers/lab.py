"""Lab API: overview, per-gen status/positions/trades, comparison, settings, reset."""
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.lab_settings import (
    get_gen_config,
    get_all_gen_configs,
    get_starting_balance_for_gen,
    update_settings,
    update_api_keys,
    get_settings_for_api,
)
from app.paper_engine import load_state, get_positions, reset_gen
from app.market import get_cached_prices
from app.bot_lab import lab_status, lab_last_cycle, get_gen_status
from app.models import (
    GenStatus,
    LabOverview,
    ComparisonRow,
    Trade,
    Position,
)

router = APIRouter(prefix="/api/lab", tags=["lab"])


def _recent_activity(limit: int = 20) -> list[dict]:
    out = []
    for gen_id in ("1", "2", "3", "4", "5"):
        config = get_gen_config(gen_id)
        initial = get_starting_balance_for_gen(gen_id)
        state = load_state(gen_id, initial)
        for t in state.get("trades", [])[-5:]:
            out.append({
                "gen_id": gen_id,
                "label": config.get("label", f"Gen {gen_id}"),
                "timestamp": t.get("timestamp"),
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "reason": t.get("reason", ""),
            })
    out.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return out[:limit]


@router.get("/overview")
async def overview() -> LabOverview:
    configs = get_all_gen_configs()
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    generations = []
    combined_pnl = 0.0
    combined_initial = 0.0
    total_positions = 0

    for gen_id in ("1", "2", "3", "4", "5"):
        config = configs.get(gen_id) or get_gen_config(gen_id)
        initial = get_starting_balance_for_gen(gen_id)
        state = load_state(gen_id, initial)
        gs = get_gen_status(gen_id, state, price_map, initial)
        combined_pnl += gs["total_pnl_usd"]
        combined_initial += initial
        total_positions += gs["positions_count"]
        last_decision = (lab_status.get(gen_id, {}).get("last_decision") or state.get("last_ai_decision")) if gen_id == "4" else None
        last_reasoning = (lab_status.get(gen_id, {}).get("last_reasoning") or state.get("last_ai_reasoning")) if gen_id == "4" else None
        generations.append(GenStatus(
            gen_id=gen_id,
            label=config.get("label", f"Gen {gen_id}"),
            enabled=config.get("enabled", True),
            balance_usd=gs["balance_usd"],
            total_value_usd=gs["total_value_usd"],
            total_pnl_usd=gs["total_pnl_usd"],
            total_pnl_percent=gs["total_pnl_percent"],
            positions_count=gs["positions_count"],
            trade_count_today=gs["trade_count_today"],
            last_run=lab_status.get(gen_id, {}).get("last_run"),
            last_decision=last_decision,
            last_reasoning=last_reasoning,
        ))

    active = sum(1 for g in generations if g.enabled)
    combined_pct = (combined_pnl / combined_initial * 100) if combined_initial else 0.0

    return LabOverview(
        total_bots_active=active,
        combined_pnl_usd=combined_pnl,
        combined_pnl_percent=combined_pct,
        total_open_positions=total_positions,
        last_cycle=lab_last_cycle,
        generations=generations,
        recent_activity=_recent_activity(),
    )


@router.get("/generations")
async def generations_list() -> list[GenStatus]:
    ov = await overview()
    return ov.generations


@router.get("/generations/{gen_id}/status")
async def gen_status_detail(gen_id: str) -> dict:
    if gen_id not in ("1", "2", "3", "4", "5"):
        raise HTTPException(404, "Unknown generation")
    config = get_gen_config(gen_id)
    initial = get_starting_balance_for_gen(gen_id)
    state = load_state(gen_id, initial)
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    gs = get_gen_status(gen_id, state, price_map, initial)
    raw_trades = state.get("trades", [])[-50:]
    trades = [Trade(**t) for t in reversed(raw_trades)]
    decisions = state.get("decisions", [])[-50:]
    # Gen 4: prefer persisted AI fields so reasoning shows after restart or before next cycle
    last_decision = lab_status.get(gen_id, {}).get("last_decision") or state.get("last_ai_decision")
    last_reasoning = lab_status.get(gen_id, {}).get("last_reasoning") or state.get("last_ai_reasoning")
    last_news_context = lab_status.get(gen_id, {}).get("last_news_context") or state.get("last_ai_news_context")
    last_ai_override_applied = state.get("last_ai_override_applied") if gen_id == "4" else None
    last_ai_override_type = state.get("last_ai_override_type") if gen_id == "4" else None
    last_ai_decision_source = state.get("last_ai_decision_source") if gen_id == "4" else None
    last_ai_market_stats = state.get("last_ai_market_stats") if gen_id == "4" else None
    gen4_decision_history = state.get("gen4_decision_history", []) if gen_id == "4" else []
    gen5_strategy_summary = state.get("gen5_strategy_summary") if gen_id == "5" else None
    gen5_activity_mode = state.get("gen5_activity_mode") if gen_id == "5" else None
    gen5_market_avg_24h = state.get("gen5_market_avg_24h") if gen_id == "5" else None
    gen5_broad_weakness = state.get("gen5_broad_weakness") if gen_id == "5" else None
    return {
        **gs,
        "label": config.get("label", f"Gen {gen_id}"),
        "enabled": config.get("enabled", True),
        "last_decision": last_decision,
        "last_reasoning": last_reasoning,
        "last_news_context": last_news_context,
        "last_ai_override_applied": last_ai_override_applied,
        "last_ai_override_type": last_ai_override_type,
        "last_ai_decision_source": last_ai_decision_source,
        "last_ai_market_stats": last_ai_market_stats,
        "gen4_decision_history": gen4_decision_history,
        "gen5_strategy_summary": gen5_strategy_summary,
        "gen5_activity_mode": gen5_activity_mode,
        "gen5_market_avg_24h": gen5_market_avg_24h,
        "gen5_broad_weakness": gen5_broad_weakness,
        "trades": [t.model_dump(mode="json") for t in trades],
        "decisions": decisions,
    }


@router.get("/generations/{gen_id}/positions")
async def gen_positions(gen_id: str) -> list[Position]:
    if gen_id not in ("1", "2", "3", "4", "5"):
        raise HTTPException(404, "Unknown generation")
    initial = get_starting_balance_for_gen(gen_id)
    state = load_state(gen_id, initial)
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    return get_positions(state, price_map)


@router.get("/generations/{gen_id}/trades")
async def gen_trades(gen_id: str, limit: int = 100) -> list[Trade]:
    if gen_id not in ("1", "2", "3", "4", "5"):
        raise HTTPException(404, "Unknown generation")
    initial = get_starting_balance_for_gen(gen_id)
    state = load_state(gen_id, initial)
    raw = state.get("trades", [])[-limit:]
    return [Trade(**t) for t in reversed(raw)]


@router.post("/generations/{gen_id}/reset")
async def gen_reset(gen_id: str) -> dict:
    if gen_id not in ("1", "2", "3", "4", "5"):
        raise HTTPException(404, "Unknown generation")
    initial = get_starting_balance_for_gen(gen_id)
    state = reset_gen(gen_id, initial)
    return {"gen_id": gen_id, "balance_usd": state["balance_usd"], "message": "Reset complete."}


@router.get("/comparison")
async def comparison() -> list[ComparisonRow]:
    configs = get_all_gen_configs()
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    rows = []
    for gen_id in ("1", "2", "3", "4", "5"):
        config = configs.get(gen_id) or get_gen_config(gen_id)
        initial = get_starting_balance_for_gen(gen_id)
        state = load_state(gen_id, initial)
        positions = get_positions(state, price_map)
        balance = state["balance_usd"]
        total_value = balance + sum(p.value_usd for p in positions)
        pnl_usd = total_value - initial
        pnl_pct = (pnl_usd / initial * 100) if initial else 0
        trades = state.get("trades", [])
        wins = sum(1 for t in trades if t.get("side") == "sell" and (t.get("total_usd", 0) or 0) > 0)
        win_rate = (wins / len(trades) * 100) if trades else None
        avg_per = (pnl_usd / len(trades)) if trades else None
        exposure = sum(p.value_usd for p in positions)
        rows.append(ComparisonRow(
            gen_id=gen_id,
            label=config.get("label", f"Gen {gen_id}"),
            pnl_usd=pnl_usd,
            pnl_percent=pnl_pct,
            trade_count=len(trades),
            win_count=wins,
            win_rate=win_rate,
            open_positions=len(positions),
            drawdown_pct=None,
            avg_per_trade_usd=avg_per,
            cash_balance=balance,
            exposure_usd=exposure,
        ))
    return rows


@router.get("/settings")
async def get_settings() -> dict:
    return get_settings_for_api()


@router.put("/settings")
async def put_settings(body: dict) -> dict:
    if body.get("global_defaults"):
        update_settings(global_defaults=body["global_defaults"])
    if body.get("generations"):
        update_settings(generations=body["generations"])
    if body.get("api_keys") is not None:
        update_api_keys(body["api_keys"])
    return get_settings_for_api()
