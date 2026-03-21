from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    total_usd: float
    reason: str
    timestamp: datetime
    world_signal: Optional[str] = None
    fee_usd: Optional[float] = None
    """Trading fee paid on this fill (USD)."""
    realized_pnl_usd: Optional[float] = None
    """On sells: net proceeds minus cost basis at avg entry (USD). Buys: null."""


class Position(BaseModel):
    symbol: str
    quantity: float
    avg_price: float
    current_price: float
    value_usd: float
    pnl_usd: float
    pnl_percent: float


class MarketTick(BaseModel):
    symbol: str
    price: float
    price_cad: float | None = None  # Canadian price (when available)
    change_24h: float
    volume_24h: float
    timestamp: datetime


class BotStatus(BaseModel):
    running: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    balance_usd: float
    total_value_usd: float
    total_pnl_usd: float
    total_pnl_percent: float
    trade_count_today: int


class TradingParams(BaseModel):
    min_price_drop_pct: float = -1.5
    min_price_rise_pct: float = 1.0
    position_pct_of_balance: float = 0.15
    min_trade_usd: float = 50.0
    max_trade_pct_of_balance: float = 20.0
    max_position_pct_per_coin: float = 25.0
    cooldown_minutes: float = 0.0
    enabled_symbols: list[str] = []


class TradingRule(BaseModel):
    id: str
    description: str
    value: str


# --- Strategy lab ---

class GenStatus(BaseModel):
    gen_id: str
    label: str
    enabled: bool
    balance_usd: float
    total_value_usd: float
    total_pnl_usd: float
    total_pnl_percent: float
    positions_count: int
    trade_count_today: int
    last_run: Optional[datetime] = None
    last_decision: Optional[str] = None
    last_reasoning: Optional[str] = None


class LabOverview(BaseModel):
    total_bots_active: int
    combined_pnl_usd: float
    combined_pnl_percent: float
    total_open_positions: int
    last_cycle: Optional[datetime] = None
    generations: list[GenStatus]
    recent_activity: list[dict]


class ComparisonRow(BaseModel):
    gen_id: str
    label: str
    pnl_usd: float
    pnl_percent: float
    trade_count: int
    win_count: int
    win_rate: Optional[float] = None
    open_positions: int
    drawdown_pct: Optional[float] = None
    avg_per_trade_usd: Optional[float] = None
    cash_balance: float
    exposure_usd: float
