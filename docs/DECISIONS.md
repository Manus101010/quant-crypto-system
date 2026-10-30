# Decision log

Newest first. Each line says what was decided, why, and what would change it.

## 29 Oct 2026

| Area | Decision | Why | Revisit when |
| --- | --- | --- | --- |
| Live losses | The minus 4.06R since 8 Oct was a basket of Momentum Runner longs (10 to 12 Oct), not the shorts | Forensics replayed the live ledger (38 of 40 fires reproduced) | n/a |
| Distribution Short | KEEP with a 2R take profit, 3.5 ATR trail from the signal ATR, stop recomputed at fire, no entry after a bounce above 3% | Survivor free study: n 778, PF 2.01; 2R TP out of sample PF 2.36, +0.427R, both halves positive. 2026 loss was one Jul to Sep alt rally episode | Weekly decay warning arrives (manual decision only, never auto deactivated) |
| Downtrend Bounce Fade | KEEP as is | Out of sample PF 1.32, both halves positive; thin | Out of sample PF falls below 1 |
| Breakdown Short (55d low) | RETIRE (`RETIRED_SETUPS`) | 10 live eligible trades in 58 months; full rule PF 1.04 | n/a |
| Basket cap | At most 3 new fired signals per direction per Sydney day; extras are paper only | 35 correlated longs in 48h caused the loss | n/a |
| Validation record | Distribution Short entry recomputed and `locked`, so Run Validation can't overwrite it | Old entry was hand edited and inconsistent | New survivor free study |
| New intraday edges | None adopted | 7 families tested on 486 perps, all failed out of sample; costs eat 0.07 to 0.12R per intraday trade | n/a |
| Watch only | New listing ORB72 short, liquidity filter, BTC below 50d gate, OI 3d rising: logged, not gated | Not significant after correction | Enough forward data |
| Signal silence | Liquidity floors scaled for MEXC volume (x13.4) and the open cap counts only taken trades | Funnel: live floor used MEXC volume (13.4x below the Binance volume the research used) and skipped paper trades filled the 10 slot cap. Expected 4 to 6 tested short alerts a week instead of 1 to 2 | Bybit reachable host (use Bybit turnover) |
| Your own setups | Rollover short, capitulation long, trend pullback with the +3% / 5% trail: rejected as live setups | 1,360 variants on 496 coins: none pass out of sample; random entries scored as well | Trade history review shows a personal edge |
| Sizing | Trader choice: $150 margin per trade, max 2 at once, 25% max loss ($37.50) each, $300 sleeve: $75 open risk and daily caps (two stop outs end the day). Claude recommended $80 / $20 | Trader wants bigger trades; $20 keeps a half the account losing streak at about 8.6% odds over 40 trades vs 65.6% at $37.50 | Account passes $500 (step to $25) |
| Bot venue | Pionex for grid bots if bots are the main instrument; Bybit stays for scanner trades | Pionex grid tools (adjust range, add margin, stop on a running grid); scanner coverage and read only API are on Bybit | n/a |
| Desk sizing | Desk fact pack sizes exactly like the alert (wide stops sized down at 1x count as within rules) | Desk was rejecting trades the alert allowed | n/a |

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

## 30 Oct 2026: daily movers board
* He trades the day's top gainers and losers by hand. Built `desk/movers.py` to do that sorting: top 5 each side, a state (rolling over, still running, stretched, still dumping, turning up, chop), a 0 to 100 fit score and the backtest verdict. Available as `/movers`, in the morning brief, and on the web app's Movers page.
* Tested his states (docs/edge_fix/movers.md): the fade to the midline and the bounce long both lose. Shorting losers that keep dumping is the best (PF 1.35 in 2023-25 and 2025-26) but weak statistically, so it stays paper only, gated on BTC below its 50 day.
* The old web scanner's tiles (Momentum Runner, Overextended, Z-Score Extreme) were daily-bar labels that were never backtested; their volume of names came from labelling, not from edge.
