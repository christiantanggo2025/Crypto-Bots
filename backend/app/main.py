from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.market import fetch_prices, get_cached_prices
from app.models import BotStatus, Trade, Position, MarketTick, TradingParams, TradingRule
from app.paper_engine import load_state, get_positions
from app.trading_params import load_params, save_params, get_enabled_symbols
from app.lab_settings import get_starting_balance_for_gen
from app.bot_lab import run_lab_cycle
from app.routers import lab as lab_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_lab_cycle()
    scheduler = AsyncIOScheduler()
    from app.lab_settings import get_price_update_interval_seconds
    interval = get_price_update_interval_seconds()
    scheduler.add_job(run_lab_cycle, "interval", seconds=max(interval, 60))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Crypto Paper Bot", lifespan=lifespan)


@app.get("/health")
async def health():
    """Railway / load balancer health check."""
    return {"status": "ok"}


# CORS: use * for simple cross-origin (Vercel → Railway). Credentials disabled so * is valid in browsers.
_cors_origins = os.getenv("CORS_ORIGINS", "*").strip()
_cors_list = [o.strip() for o in _cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status() -> BotStatus:
    initial = get_starting_balance_for_gen("1")
    state = load_state("1", initial)
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    positions = get_positions(state, price_map)
    balance = state["balance_usd"]
    total_value = balance + sum(p.value_usd for p in positions)
    pnl_usd = total_value - initial
    pnl_pct = (pnl_usd / initial * 100) if initial else 0
    from app.bot_lab import lab_status
    today = sum(1 for t in state.get("trades", []) if (t.get("timestamp") or "").startswith(__import__("datetime").datetime.utcnow().date().isoformat()))
    return BotStatus(
        running=True,
        last_run=lab_status.get("1", {}).get("last_run"),
        next_run=None,
        balance_usd=balance,
        total_value_usd=total_value,
        total_pnl_usd=pnl_usd,
        total_pnl_percent=pnl_pct,
        trade_count_today=today,
    )


@app.get("/api/market")
async def market() -> list[MarketTick]:
    return get_cached_prices()


@app.get("/api/positions")
async def positions() -> list[Position]:
    initial = get_starting_balance_for_gen("1")
    state = load_state("1", initial)
    prices = get_cached_prices()
    price_map = {t.symbol: t.price for t in prices}
    return get_positions(state, price_map)


@app.get("/api/trades")
async def trades(limit: int = 100) -> list[Trade]:
    initial = get_starting_balance_for_gen("1")
    state = load_state("1", initial)
    raw = state.get("trades", [])[-limit:]
    return [Trade(**t) for t in reversed(raw)]


@app.get("/api/trading-params")
async def get_trading_params() -> TradingParams:
    p = load_params()
    return TradingParams(
        min_price_drop_pct=p["min_price_drop_pct"],
        min_price_rise_pct=p["min_price_rise_pct"],
        position_pct_of_balance=p["position_pct_of_balance"],
        min_trade_usd=p["min_trade_usd"],
        max_trade_pct_of_balance=p["max_trade_pct_of_balance"],
        max_position_pct_per_coin=p["max_position_pct_per_coin"],
        cooldown_minutes=p["cooldown_minutes"],
        enabled_symbols=p.get("enabled_symbols") or [],
    )


@app.put("/api/trading-params")
async def update_trading_params(body: TradingParams) -> TradingParams:
    save_params(body.model_dump())
    return body


@app.get("/api/trading-rules")
async def get_trading_rules() -> list[TradingRule]:
    """Human-readable rules derived from current params."""
    p = load_params()
    syms = get_enabled_symbols()
    return [
        TradingRule(id="buy_trigger", description="Buy when 24h price drop is at or below", value=f"{p['min_price_drop_pct']}%"),
        TradingRule(id="sell_trigger", description="Sell (take profit) when 24h price rise is at or above", value=f"{p['min_price_rise_pct']}%"),
        TradingRule(id="position_size", description="Max % of balance per new position", value=f"{p['position_pct_of_balance'] * 100}%"),
        TradingRule(id="min_trade", description="Minimum trade size", value=f"${p['min_trade_usd']}"),
        TradingRule(id="max_trade", description="Max % of balance per single trade", value=f"{p['max_trade_pct_of_balance']}%"),
        TradingRule(id="max_per_coin", description="Max % of portfolio in one coin", value=f"{p['max_position_pct_per_coin']}%"),
        TradingRule(id="cooldown", description="Minutes before re-trading same symbol", value=f"{p['cooldown_minutes']} min"),
        TradingRule(id="symbols", description="Symbols enabled for trading", value=", ".join(syms) if syms else "all"),
    ]


app.include_router(lab_router.router)

# Serve frontend in production (optional; Vercel hosts UI separately in typical deploy)
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
