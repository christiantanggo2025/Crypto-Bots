"""
Toronto calendar for "today" boundaries; UTC-aware instants for storage and APIs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Aware-UTC default for cooldown math when a symbol has no prior trade
UTC_MIN = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_trade_timestamp(ts: str | None) -> datetime | None:
    """Parse trade/API timestamp: Z or offset, else treat naive as UTC."""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            return d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def toronto_calendar_date_iso(dt: datetime) -> str:
    """YYYY-MM-DD in America/Toronto."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TORONTO).date().isoformat()


def toronto_today_date_iso() -> str:
    return datetime.now(TORONTO).date().isoformat()


def trade_is_toronto_today(ts: str | None) -> bool:
    parsed = parse_trade_timestamp(ts)
    if not parsed:
        return False
    return toronto_calendar_date_iso(parsed) == toronto_today_date_iso()


def count_trades_toronto_today(state: dict) -> int:
    return sum(1 for t in state.get("trades", []) if trade_is_toronto_today(t.get("timestamp")))
