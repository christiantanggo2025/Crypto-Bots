import httpx
from datetime import datetime

from app.config import settings
from app.models import MarketTick

# Map our symbols to CoinGecko IDs (free API, no key)
SYMBOL_TO_COINGECKO = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binancecoin",
    "XRPUSDT": "ripple",
    "DOGEUSDT": "dogecoin",
    "ADAUSDT": "cardano",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "DOTUSDT": "polkadot",
}

# In-memory cache to avoid hitting CoinGecko on every API request (rate limit ~10–30/min)
_cached_ticks: list[MarketTick] = []
_cache_time: datetime | None = None
CACHE_MAX_AGE_SECONDS = 90


def set_cached_prices(ticks: list[MarketTick]) -> None:
    global _cached_ticks, _cache_time
    _cached_ticks = ticks
    _cache_time = datetime.utcnow()


def get_cached_prices() -> list[MarketTick]:
    """Return cached prices if younger than CACHE_MAX_AGE_SECONDS, else empty list."""
    global _cache_time
    if _cache_time is None:
        return []
    if (datetime.utcnow() - _cache_time).total_seconds() > CACHE_MAX_AGE_SECONDS:
        return []
    return _cached_ticks


async def fetch_prices(symbols: list[str] | None = None) -> list[MarketTick]:
    """Fetch current prices from CoinGecko (no API key). On 429/errors returns [] and keeps cache.
    If symbols is provided use it; else use config symbols."""
    sym_list = symbols if symbols else settings.symbols
    ids = [
        SYMBOL_TO_COINGECKO[s]
        for s in sym_list
        if s in SYMBOL_TO_COINGECKO
    ]
    if not ids:
        return []

    url = f"{settings.coingecko_base}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "order": "market_cap_desc",
        "sparkline": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        # 429 Too Many Requests or other client/server error: don't crash, use cache
        if e.response.status_code == 429:
            pass  # rate limited
        return get_cached_prices()
    except Exception:
        return get_cached_prices()

    # Get USD→CAD rate (1 USDC ≈ 1 USD, so USDC in CAD ≈ rate)
    cad_per_usd: float | None = None
    try:
        rate_url = f"{settings.coingecko_base}/simple/price"
        rate_params = {"ids": "usd-coin", "vs_currencies": "cad"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            rate_r = await client.get(rate_url, params=rate_params)
            if rate_r.status_code == 200:
                j = rate_r.json()
                if "usd-coin" in j and "cad" in j["usd-coin"]:
                    cad_per_usd = float(j["usd-coin"]["cad"])
    except Exception:
        pass

    id_to_symbol = {v: k for k, v in SYMBOL_TO_COINGECKO.items()}
    ticks = []
    for row in data:
        cg_id = row["id"]
        symbol = id_to_symbol.get(cg_id)
        if not symbol:
            continue
        price_usd = float(row["current_price"])
        price_cad = (price_usd * cad_per_usd) if cad_per_usd else None
        ticks.append(
            MarketTick(
                symbol=symbol,
                price=price_usd,
                price_cad=price_cad,
                change_24h=float(row.get("price_change_percentage_24h") or 0),
                volume_24h=float(row.get("total_volume") or 0),
                timestamp=datetime.utcnow(),
            )
        )
    if ticks:
        set_cached_prices(ticks)
    return ticks
