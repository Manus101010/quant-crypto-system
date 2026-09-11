# QuantCore — Session Handoff Document
**Last updated:** 2026-06-02  
**Server:** `http://localhost:8501`  
**Start command:** `cd /Users/manusmclaughlin/Desktop/claude-trading-sytem && ./start.sh`  
(or `./venv/bin/python server.py` for one-off start)

---

## System Overview

QuantCore is a **hybrid AI-quant trading system** built with:
- **Backend:** FastAPI (Python), port 8501
- **Frontend:** Vanilla HTML/CSS/JS SPA at `/frontend/`
- **AI:** Anthropic Claude API for stock analysis
- **Data:** yfinance (price data), FRED API (macro data), CoinGecko (crypto universe)

---

## Current Project Structure

```
claude-trading-sytem/
├── server.py               — FastAPI entry point (uvicorn, port 8501)
├── config.py               — API keys, signal weights, thresholds
├── start.sh                — Auto-restart server script
├── .env                    — ANTHROPIC_API_KEY (do not commit)
│
├── api/
│   ├── macro.py            — /api/macro/run, /api/macro/latest
│   ├── analyst.py          — /api/analyst/analyze/stream, /api/analyst/latest
│   ├── scanner.py          — /api/scanner/run, /api/scanner/run/crypto, /api/scanner/universe/crypto
│   ├── backtest_api.py     — /api/backtest/run
│   ├── journal_api.py      — /api/journal/entries (CRUD)
│   └── log_store.py        — in-memory system log ring buffer
│
├── signals/                — Macro Gate: 10 signals, each returns score 0-100
│   ├── aggregator.py       — runs all 10 in parallel, weighted blend
│   ├── vix_level.py        — VIX percentile score
│   ├── vix_term_structure.py — VIX/VIX3M ratio (contango/backwardation)
│   ├── breadth.py          — % S&P 500 stocks above 200-SMA
│   ├── credit_spreads.py   — HYG/IEF spread proxy
│   ├── put_call.py         — VIX ROC (60%) + VIX9D/VIX ratio (40%) — UPGRADED
│   ├── yield_curve.py      — 10Y minus 3M Treasury spread
│   ├── momentum.py         — SPY golden cross + 3M + 12-1M momentum
│   ├── nfci.py             — Chicago Fed NFCI (FRED) — NEW
│   ├── m2_growth.py        — M2 money supply YoY (FRED) — NEW
│   └── inflation.py        — 10Y TIPS breakeven (FRED T10YIE) — NEW
│
├── utils/
│   ├── fred.py             — FRED CSV API fetcher with 1hr cache — NEW
│   ├── crypto_universe.py  — CoinGecko top-N by market cap with blocklist — NEW
│   └── logger.py           — structured logger
│
├── skills/
│   └── scanner.py          — Stock + Crypto scanner with mean reversion — MAJOR UPGRADE
│
├── analyst/                — Claude AI stock analysis pipeline
│   ├── data_fetcher.py
│   ├── peer_benchmarker.py
│   ├── analyzer.py         — calls Claude API
│   └── blender.py          — Quant 60% + Claude 40% blend
│
├── backtesting/
│   └── engine.py           — vectorbt engine, returns SMA + entry/exit signals
│
├── journal/                — SQLite-based trade journal
│
└── frontend/
    ├── index.html
    ├── css/styles.css
    └── js/
        ├── app.js          — State, renderLine/Gauge/Radar, router
        ├── api.js          — all API calls centralised
        └── pages.js        — all page render functions (~1400 lines)
```

---

## Pages / Tabs

| Page | Route | Status |
|------|-------|--------|
| Dashboard | `/` | Shows deployment score, analyst picks, scanner summary, macro regime |
| Scanner | `scanner` | **Stocks + Crypto tabs**, setup cards, Mean Reversion + Momentum, journal logging |
| Macro Gate | `macro` | 10-signal deployment score, gauges, what-if sliders |
| Analyst Rankings | `analyst` | SSE streaming analysis, deep-dive radar, peer benchmarks |
| Rank Deltas | `deltas` | Score breakdown (Quant 60%/Claude 40%), rank changes, collapsible table |
| Backtests | `backtests` | Price chart with SMA + buy/sell signals, equity curve, drawdown |
| Journal | `journal` | Trade/idea log, P&L tracking, stats |

---

## Macro Gate — 10 Signals (Weights)

```python
SIGNAL_WEIGHTS = {
    "vix_level":          0.80,  # correlated with term structure → reduced
    "vix_term_structure": 0.80,  # correlated with vix_level → reduced
    "breadth":            1.00,
    "credit_spreads":     1.00,
    "put_call":           1.00,  # upgraded: VIX ROC + VIX9D/VIX ratio
    "yield_curve":        0.80,  # long lead time → reduced
    "momentum":           1.00,
    "nfci":               1.00,  # Chicago Fed NFCI (FRED) — NEW
    "m2_growth":          0.80,  # M2 YoY growth (FRED) — NEW
    "inflation":          0.60,  # 10Y TIPS breakeven (FRED) — NEW
}
```
Aggregator normalises automatically. Current reading: **83.4 — Aggressive Deploy**.

---

## Scanner — Setup Types

### Momentum
- 🚀 Momentum Runner — golden cross + strong 3M momentum
- 📈 Confirmed Uptrend — above both SMAs, golden cross
- ⚡ Overbought Runner — RSI>72 + momentum>20%
- ↩ Pullback to SMA50 — above 200 but below 50
- 🏗 Building Base — above 200, consolidating

### Mean Reversion (NEW)
- 🎯 Deep Oversold — BB%B ≤ 0.05 AND RSI < 30
- 🎯 BB Bounce Setup — BB%B ≤ 0.20, above 200-SMA
- 📊 Z-Score Extreme — 2+ standard deviations below 20-day mean
- 🎯 Williams %R Oversold — %R ≤ −85, above 200-SMA
- ⚠ Overextended — BB%B ≥ 0.92 + RSI > 72 (take profit zone)
- ⚠ Far Above 200-SMA — >30% extended, high RSI

### Metrics on each card
- RSI-14 (bar + label)
- 3M Momentum %
- ✓/✗ SMA200 and SMA50 tags
- BB% (Bollinger Band %B)
- Z (Z-score vs 20-day mean)
- %R (Williams %R)
- MOMENTUM / MEAN REVERSION badge
- Vol $M/day

### Strategy filter buttons
All Setups | 🚀 Momentum Only | 🎯 Mean Reversion Only

### Crypto Universe
- Dropdown: Top 50 / Top 100 / Top 150 / Top 200 / Custom
- Live from CoinGecko free API by market cap
- Auto-filters stablecoins, wrapped tokens
- Default SMA filter: "No — show all" (crypto is currently below SMA50 broadly)

---

## Known Issues / Pending

1. **Yahoo Finance rate limit** — after heavy scanning/backtesting, Yahoo Finance returns 429. Clears in 15–30 minutes automatically. No code fix needed.

2. **^SPXA200R missing from yfinance** — breadth signal falls back to sector ETF breadth (10/11 ETFs above SMA200). Acceptable fallback but the signal reads 100 when all ETFs are in uptrend.

3. **Analyst tab FA only** — The user asked about adding TA scoring to Analyst Rankings (RSI, SMA position, 3M momentum as a separate TA leg). Not built yet. Currently: Quant 60% (FA metrics) + Claude AI 40% (qualitative).

4. **FRED data monthly lag** — M2 (1 month lag), PMI proxy not available on FRED. ISM Manufacturing PMI is not available free on FRED — best proxy is IPMAN (Industrial Production Manufacturing). Could be added as Signal 11 if desired.

5. **Auto-start on login** — `start.sh` auto-restarts server if it crashes but requires terminal open. Could set up a launchd plist for true background service.

---

## Key Config

```python
# config.py
DEPLOY_THRESHOLDS = {
    "aggressive": 70,   # ≥70 = Aggressive Deploy
    "moderate":   50,   # 50-69 = Moderate Deploy
    "cautious":   30,   # 30-49 = Cautious Deploy
}                       # <30 = Avoid / Reduce
```

---

## How to Resume in New Chat

1. Open new Claude session
2. Reference this file: `HANDOFF.md` in the project root
3. Say: *"Continue building QuantCore. Read HANDOFF.md and project_trading_system.md in the memory folder first."*
4. Memory files: `/Users/manusmclaughlin/.claude/projects/-Users-manusmclaughlin-Desktop-claude-trading-sytem/memory/`

---

## Suggested Next Steps

1. **Add TA scoring leg to Analyst Rankings** — RSI, SMA position, 3M momentum alongside FA metrics
2. **ISM PMI signal** — scrape/add industrial production proxy as Signal 11
3. **Persistent server** — set up launchd to start server on login
4. **Portfolio tracker tab** — track open positions, link to journal entries
5. **Backtest: multi-ticker comparison** — run same strategy on multiple tickers side-by-side
6. **Price alerts** — notify when a scanner setup appears for a watchlist ticker
