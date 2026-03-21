from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paper trading
    initial_balance_usd: float = 10_000.0
    # Coins to track (Binance symbols)
    symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    # How often to run the bot (seconds); keep >= 60 to respect CoinGecko rate limits
    bot_interval_seconds: int = 90
    # API (optional - CoinGecko is free, no key needed for basic)
    coingecko_base: str = "https://api.coingecko.com/api/v3"

    class Config:
        env_file = ".env"


settings = Settings()
