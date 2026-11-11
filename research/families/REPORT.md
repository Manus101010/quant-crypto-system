# New signal families: research findings (8 Oct 2026)

Research only. Nothing here is imported by the live scanner, monitor or bot.

## Why this exists

The live scanner almost never produces shorts or neutral plans because every short
setup is nested under `if below_200:` in `skills/scanner.py`, the two mean reversion
shorts stack conditions that produced zero trades in 600 days, and the fail closed
edge gate then never arms them. Before changing any of that, each candidate
replacement was tested here.

## Data and rules

* 219 MEXC USDT perpetual coins (top 250 by volume, stables and tokenised stocks
  removed), daily candles 2020 to 8 Oct 2026 from MEXC spot, OKX fallback.
  Grids additionally use hourly candles for the 60 most liquid coins, Jun 2024 onward.
* Entry on the signal close, stop checked before target, 0.36% round trip cost,
  one open trade per coin, $0.5M daily volume floor.
* PASS = PF > 1, n >= 25, PF > 1 in both halves (the `mr_shorts.py` bar) AND
  expectancy in R > 0 (the live bot sizes by fixed risk).
* BTC regime: UP = close above 200 and 50 SMA with 50 above 200; DOWN = the mirror;
  MIXED = everything else (the bot's "NEUTRAL").

Harness sanity check: the production Donchian 55d idea reran at n 917, PF 1.34,
+0.167R (live validation: PF 1.27).

## Findings

| Family | Result | Key numbers |
|---|---|---|
| Fade rips ABOVE the 200 SMA | Fails in every BTC regime | BTC UP n 309, PF 0.89, −0.047R; MIXED n 100, PF 1.08, −0.103R |
| Fade bounces BELOW the 200 SMA, BTC MIXED | Passes | n 282, PF 2.10, +0.137R, 72% win, ~4 days; excluding busy crash days n 146, PF 1.93, +0.130R |
| Distribution short (coil after a big run up, short in lower half of range) | Passes, not in BTC DOWN | n 415, PF 2.66, +0.447R; excluding 2025 n 237, PF 1.55, +0.180R; BTC DOWN n 37, PF 0.58; 2026 so far n 28, PF 0.68 |
| Compression breakout long after a downtrend | Only with BTC UP | BTC UP n 209, PF 1.52, +0.396R; MIXED n 317, PF 0.90; DOWN n 43, PF 0.72 |
| Breakout retest (CONFIRMED) entries | Worse than buying the breakout close | see results/breakout.md |
| Pre positioning in the coil (longs) | Fails | see results/breakout.md |
| Capitulation longs (buy the flush), BTC MIXED | Event driven, not steady | n 256, PF 3.56, but 113 of 282 trades on 10 Oct 2025, 51 distinct days; excluding busy days n 45, PF 1.24 |
| Grids (hourly paths), any mechanical deployment rule | No edge found | every 10 days PF 0.92; in chop PF 0.71 (worst); long grid on breakout PF 1.03 |
| Squeeze fuel (funding before breakouts) | No edge from funding | Since Apr 2025 (MEXC funding history start): long breakouts with funding < 0 n 109, PF 0.69 vs funding >= 0 n 283, PF 0.73, both losing; crowded long funding (> +0.01%) before breakdowns only happened 3 to 6 times. Not worth wiring |

## What this means for the live scanner

1. Keep "Overextended — Reversion Risk" as an exit flag. Fading strong coins above
   the 200 SMA loses money.
2. Candidate new shorts: the downtrend bounce fade (BTC MIXED only) and the
   distribution short (not when BTC is DOWN).
3. Breakout longs belong behind the existing BTC long gate; the compression
   version is a candidate upgrade to the Donchian setup when BTC is UP.
4. Stop auto attaching grid plans to directional signals; no deployment rule tested
   had a measured edge.

## Best trade TYPE per setup (what the alert should suggest)

Every passing family was tested as a plain directional position with a stop. None
of the grid deployments beat that, so for these setups the suggestion should be a
leveraged long/short with the stop below (MEXC supports stop loss and trailing stop
orders on futures), not a grid:

| Setup | Suggested trade | Exit |
|---|---|---|
| Downtrend bounce fade | Short, stop 0.25 ATR above the 7 day high | Take profit at the 20 EMA (most exits hit target, ~4 days) |
| Distribution short | Short, initial stop 3.5 ATR | Trailing stop 3.5 ATR, up to 60 days |
| Compression breakout (BTC UP) | Long, stop 1 ATR below the breakout level | Trailing stop 3 ATR, up to 60 days |

Leverage note: a grid feels safer at high leverage because it scales in, so the
average position is smaller than the headline leverage. The same safety comes from
sizing a directional trade by its stop distance (risk a fixed $ per trade) and
setting leverage so liquidation sits well beyond the stop.

## Caveats

* Survivorship: only coins listed today, which flatters longs and understates shorts.
* Daily bars only for signals (no 4H confirmation); funding payments not modelled.
* Many variants were tested. Only results that held across neighbouring settings,
  both halves, and with crash cluster days removed are treated as real.

## Reproduce

```
./venv/bin/python research/families/fetch_history.py /tmp/hist.pkl 250
./venv/bin/python research/families/fetch_hourly.py /tmp/hist.pkl /tmp/hourly.pkl 60 2024-06-01
./venv/bin/python research/families/exhaustion.py /tmp/hist.pkl results/exhaustion.md
./venv/bin/python research/families/breakout.py   /tmp/hist.pkl results/breakout.md
./venv/bin/python research/families/grids.py      /tmp/hist.pkl results/grids_hourly.md /tmp/hourly.pkl
./venv/bin/python research/families/squeeze.py    /tmp/hist.pkl results/squeeze.md
```
