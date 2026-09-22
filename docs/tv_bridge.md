# TradingView MCP × the trading system — how the two pieces fit

Two capabilities were added around prompt #10 ("scan my watchlist, send a brief")
and the TradingView MCP. They play **different roles on purpose** — one is
unattended and reliable, the other is attended and additive.

## Part 1 — Morning Brief (scheduled, code path, ALWAYS works)

A one-page daily read, built on ccxt/code so it never needs TradingView open.

- Build/send:  `./run_morning_brief.sh`   (add `--dry-run` to print, not send)
- Schedule daily 08:00 local (cron): see the header in `run_morning_brief.sh`.
- Contents: BTC regime + macro deployment score, overnight trigger activity,
  what's still armed, your **watchlist** (price, 24h, flagged within 3% of the
  20-day high/low), and any setups the decay watch deactivated.
- Watchlist is managed in the **Trade Desk** tab (⭐ Watch button + expander),
  stored in `data/trading.db` (`watchlist` table).

Why code, not the MCP: an 8am job can't depend on TradingView Desktop running
with CDP — it would fail most mornings. The reliable path owns the schedule.

## Part 2 — Desk → your chart bridge (attended, via the TradingView MCP)

When TradingView **is** open, the system's computed numbers can be drawn on your
real chart. This is an **agent-driven workflow** (ask Claude in chat), not a
button in the Streamlit app — the MCP tools belong to the assistant, not the app.

Setup (once per session, when TV isn't already CDP-connected):
1. `tv_launch` — starts TradingView Desktop with the debug port.
2. `tv_health_check` — must return your real chart symbol + `cdp_connected: true`.
   If #01 doesn't return your real chart, the connection isn't live — stop.

Then, on request ("draw SOL's desk levels on my chart"), the assistant:
1. Computes the Trade Desk read for the coin (`desk/analysis.py`): direction,
   grid range low/high, 20-day range hi/lo.
2. `chart_set_symbol` to the coin (e.g. `MEXC:SOLUSDT` to match your venue).
3. `data_get_ohlcv` — sanity-check the chart's close matches the code's price
   (reconciliation: are you looking at what the model is looking at?).
4. `draw_shape` — a rectangle for the grid box (labelled with grids + leverage)
   and horizontal lines at the 20-day high/low.

Nothing here places or manages an order. The drawn levels are a starting
suggestion you set on MEXC yourself — identical guardrail to the Trade Desk.

## The honest split
- **Reliable / unattended:** regime, scanner, monitor alerts, morning brief,
  revalidation — all code/ccxt, no TradingView dependency.
- **Attended / additive:** the MCP puts those numbers on the chart you trade
  from, and reconciles your chart's indicators against the code read.
