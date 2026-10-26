# Morning brief and human to do list (27 Oct 2026)

## What happened overnight
- **Guard** (`guard/`): checks any plain trade or Bybit futures grid against your rules before entry. Telegram: `/guard short DOODUSDT grid 0.0016 0.00221 200 3x 263.86 sl 0.002221`. Add `issue` at the end to register it.
- **Revenge handling, no cooldown:** after a stop out the next trade you `/took` is locked to 1R ($12.50). Any Bybit position the system didn't issue is tagged and its P&L reported separately. Alerts show "Daily loss cap hit" once you are down $125 on the Sydney day.
- **Watcher** (`watcher.py`): read only Bybit monitor. Liquidation distance, grid edges, missing stops, open risk, daily cap, BTC regime, 07:00 / 15:30 / 21:30 summaries. Needs a non US host (Bybit blocks GitHub's US servers).
- **Signal features:** every alert now carries a positioning line (funding, OI, long/short, taker, DEX volume) from free sources, stored for later scoring.
- **Grid backtest:** 1,440 configs on 70 coins, Nov 2025 to Oct 2026, 5m candles with real funding. **None pass the edge gate.** Your style (200 grids, 5x, ±20 to 25%) has PF 0.51 to 0.56: wins 61% of the time, but about one run in six gives back most of the margin; without stops 40% end liquidated. An independent review re-derived the numbers and confirmed the verdict.
- **Warning on the live edges:** Distribution Short is negative in 2026 so far (n 42, −0.47R) and Bounce Fade's expectancy has shrunk every year (+0.75, +0.22, +0.08R).

## Your to do list
1. **DOOD bot:** if still running without a stop, close it. Compliant relaunch if you want it: short 3x, 0.0016 to 0.00221, 200 grids, $263.86, SL 0.002221 (worst case $65.91).
2. **Bybit sub account:** create one, move only the $500 sleeve in.
3. **Read only API key** on that sub account (Read permission only, no trade, no withdraw). Bind it to an IP once the runner exists (unbound keys expire every 90 days).
4. **Coinalyze free API key** (coinalyze.net, free, 40 calls/min). Add as GitHub secret `COINALYZE_API_KEY`. Skip CoinGlass and Whale Alert for now (CoinGlass Hobbyist is 4h data only; Whale Alert's $14.95 plan has no API).
5. **Runner:** create a free Supabase Edge Function in the Sydney region (I'll write it once you have the key), or say if you'd rather use an Oracle Always Free VM in Sydney.
6. **Grid bot IDs:** after relaunching any grid, send `/addbot <Bot ID> DOOD` in Telegram (Bot ID is on the bot details page; Bybit has no API to list bots).
7. **Review and merge the PR** on GitHub when happy; nothing changes live until it's merged.
8. **Never paste keys into chat.** They go into GitHub/Supabase secrets.

## Reports
- `docs/night/research_tools.md`: APIs, runners, data stack
- `docs/night/grid_backtest.md`: full grid results
- `docs/night/guard_watcher.md`: guard and watcher details
- `docs/night/features.md`: signal features and evaluation
- `docs/night/review.md`: independent review
