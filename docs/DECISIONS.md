# Decision log

Newest first. Each line says what was decided, why, and what would change it.

## 28 Oct 2026

| Area | Decision | Why | Revisit when |
| --- | --- | --- | --- |
| Desk layer | Build a veto only multi agent desk (`desk/agents/`) inspired by TradingAgents, not a clone of it | TradingAgents is stock focused (Yahoo, SEC, StockTwits), has no perps, funding or liquidation concepts and publishes no backtest | Never clone; borrow patterns only |
| Desk powers | Can only keep, shrink (TAKE_REDUCED), delay (WAIT) or skip. Never creates a trade, raises size, widens a stop | Stops the desk becoming a voice for revenge trades; all money numbers stay in tested code | Only if the scorecard passes, and even then never "add" |
| Desk placement | Runs after scanner and guard, in the background; the alert is never delayed | 60 to 120 s per run; the alert must not wait | n/a |
| Desk models | Claude API, Haiku 5.5 for every role (`DESK_MODEL_FAST`, `DESK_MODEL_DEEP`) | About 0.012 USD per run, about 2.50 USD a month. API credits are billed separately from Claude Pro | Move only the Trader to Sonnet 5.5 if debates read shallow |
| Desk switch | Off by default (`DESK_ENABLED` secret). `/desk` works on demand whenever the API key exists | Phase 0 manual test first | Set `DESK_ENABLED=1` after Phase 0 to start shadow mode |
| Desk proof | Scored as "all signals" vs "desk approved" vs "vetoed" (`/deskstats`). Passes only with 60+ closed signals, approved beats all, approved PF above 1 in both halves, vetoed loses | LLM decisions can't be backtested honestly (models know 2024 to 2026 outcomes) | After 60 closed signals |
| Desk data | Agents see only a code built fact pack and must cite its keys; more than 2 invented keys tightens the verdict one notch | Prevents hallucinated numbers | n/a |
| TradingAgents patterns kept | Bull vs bear debate (2 rounds, round 1 blind), portfolio aware review, settled decision memory, HTML report per run | These are the parts that transfer to crypto | n/a |
| Grids | Grid suggestions stay in alerts but are labelled "not edge tested"; the desk caps any grid pick at TAKE_REDUCED | 0 of 1,440 grid configs passed the backtest; independent review confirmed | A grid strategy passes the edge gate |
| Position reviews | Not wired yet | Needs the read only Bybit watcher running on a Sydney host | Bybit key + runner exist |

## 27 Oct 2026

| Area | Decision | Why |
| --- | --- | --- |
| Venue | Bybit only, for signals and grids | Pionex lacks most coins the scanner fires on; one venue keeps the daily cap and revenge tagging airtight |
| Grid adjust | "Adjust" = close and relaunch through the guard | Bybit futures grids can't change range after creation |
| Revenge trading | No cooldown. After a stop out, the next `/took` trade is locked to 1R; unissued positions are tagged and scored separately; 125 USD daily cap | Trader said he won't respect a cooldown |
| Risk rules | 50 USD margin, stop loses at most 25% of margin, liq at least 2x stop distance, grids at least 3x, open risk and daily caps 125 USD | Trader's rules, now enforced in `guard/` |
| Data | Free first: OKX, MEXC, Hyperliquid, DEX Screener, Coinalyze (free key). Skip CoinGlass Hobbyist (4h only) and Whale Alert 14.95 (no API) | Budget 50 USD a month; free sources cover the same ground |
| Features | Positioning snapshot logged on every alert; nothing used as a filter until it passes on live data. Two OI rules pre registered | 9 filters tested, none survived a multiple testing correction |
| Runner | Read only watcher must run from a non US host: Supabase Edge Function in Sydney first, Oracle Always Free Sydney VM second | Bybit blocks US IPs including GitHub runners; Singapore is restricted |
