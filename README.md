# Crypto Paper Bot (Website)

A **paper-trading** crypto bot that runs as a **website**. It tracks the market, generates buy/sell signals from price and world-style signals, and executes simulated trades—no real money. The dashboard shows balance, positions, P&L, and recent trades.

## What it does

- **Tracks** BTC, ETH, SOL (configurable) via CoinGecko (no API key).
- **Runs a strategy** every 60 seconds: “buy the dip” when 24h price drops, “take profit” when 24h price rises.
- **Paper trades** only: virtual $10,000, simulated orders, state saved to `backend/data/`.
- **Dashboard**: balance, portfolio value, P&L, market tickers, positions, recent trades.

## Quick start

### 1. Backend (Python)

```bash
cd backend
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Frontend (dev)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The frontend proxies `/api` to the backend at port 8000.

### 3. Production-style (single server)

Build the frontend and run the backend; it will serve the built site:

```bash
cd frontend && npm run build && cd ..
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000**.

## Project layout

```
Crypto-bot/
├── backend/
│   ├── app/
│   │   ├── main.py      # FastAPI app, API routes, scheduler
│   │   ├── bot.py       # Bot runner (fetch data, strategy, execute paper orders)
│   │   ├── market.py    # CoinGecko price fetching
│   │   ├── paper_engine.py  # Virtual balance, positions, order execution
│   │   ├── strategy.py  # Buy/sell signal logic
│   │   ├── config.py
│   │   └── models.py
│   ├── data/            # paper_state.json (created at runtime)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx      # Dashboard UI
│   │   ├── main.tsx
│   │   └── index.css
│   ├── index.html
│   └── package.json
└── README.md
```

## Configuration

- **Initial balance**: `initial_balance_usd` in `backend/app/config.py` (default 10,000).
- **Symbols**: `symbols` in `config.py` (default BTC, ETH, SOL). CoinGecko IDs are in `market.py`.
- **Bot interval**: `bot_interval_seconds` (default 60).
- **Strategy**: thresholds in `backend/app/strategy.py` (`MIN_PRICE_DROP_PCT`, `MIN_PRICE_RISE_PCT`, etc.).

## Next steps

- Add **news/sentiment** APIs and feed them into the strategy as “world” signals.
- Tweak strategy (e.g. more pairs, different thresholds, or simple indicators).
- Add **backtesting** and charts.
- When ready for real trading, swap the paper engine for an exchange API (with keys in env, never in code).
