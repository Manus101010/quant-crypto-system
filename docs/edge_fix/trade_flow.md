# Trade flow: why Telegram is nearly silent (29 Oct 2026)

Owner: TRADE FLOW agent. Code: `research/trade_flow.py` (refresh, funding, replay, replay_hourly, replay_binvol, report). No production file was edited; production modules are only monkeypatched in process. Outputs (`flow*.pkl`, `report.json`) are in the scratchpad cache `tf/cache`.

## 0. Headline

* **Window:** every scheduled scan from 28 Oct 21:58 UTC back 30 days (90 scans: 06:50 Sydney, 00:05 UTC, 15:00 Sydney, DST aware) plus a 5 day warm up so the book is realistic at the start. Last 7 days = 21 scans.
* **Code:** the CURRENT branch (`research/fix-live-edge`): DS 2R take profit, restop at arm and at fire, 3% up and down drift bounds, Breakdown Short retired, basket cap 3 per direction per Sydney day, 25% stop cap (DS 50%), open cap 10, top_n 5, decay watch state of today (Momentum Runner, Donchian 55d, RSL, Volume Breakout, Squeeze Breakout off). Driven through `live_forensics.Replay` on MEXC perp candles (the path the US hosted live scan uses), OKX funding.
* **Result: 8 tradeable alerts in 30 days (1.87 per week), 1 in the last 7 days.** All 8 are Distribution Short. Zero longs, zero Downtrend Bounce Fade.
* **Three gates explain the silence:**
  1. **Longs are switched off twice (long gate + decay watch):** 93.5% of everything the scanner detects is a long (11,490 of 12,290 detections in 30 days, 2,316 of 2,627 in 7 days). All of it is blocked. These longs are what lost about -26R in the 10 to 12 Oct burst (forensics.md), so this silence is correct.
  2. **The liquidity floor is measured on MEXC volume, not Bybit or Binance volume:** only 177 of 468 coins with candles pass the $0.5M scan floor (164 in the last week). The research measured liquidity on Binance UM, where the same coins trade a median **13.4x** more. With research equivalent volume 449 coins pass, and DS plus DBF detections roughly triple (19 to 57 unique signals in 30 days). This is a live vs research mismatch, not an edge choice.
  3. **The open position cap counts paper trades:** DS holds up to 60 days, so ten paper DS positions the trader never took fill all 10 slots and block every new alert. In the replay the book hit 10 on 26 Oct and blocked SPX, UNI, BTC, ETHFI, PENDLE type signals; with research equivalent volume the book is full from 8 Oct and the cap blocks 23 unique short signals in 30 days.
* **More scan times add nothing:** 7 scans a day instead of 3 gave exactly the same 8 alerts (setups are read on CLOSED daily bars, so every scan in a UTC day sees the same signal).
* **Forecast, current rules, this market (BTC below its 50d, above its 200d, trend MIXED):** about **1 to 2 tradeable alerts per week**, all DS, often 0 for a week, and **0** whenever BTC flips to trend DOWN (both shorts switch off) or the book holds 10 paper positions.

## 1. Funnel, last 30 days (90 scans, current rules)

Detections are per scan (a coin with a setup counts once per scan it is seen). Each detection is charged to the FIRST gate that removes it, in this order: long gate, decay, retired, not validated, held, bad plan, drift, stop cap, funding, open cap, top_n, then the post arm steps.

| step | total (90 scans) | per scan | note |
|---|---|---|---|
| universe (data/bybit_perps.json, saved 10 Oct) | 523 | 523 | Bybit is geo blocked on the live host |
| coins with candles (MEXC perp of the same coin) | | 468.5 | 47 Bybit perps have no MEXC perp |
| liquid (20d turnover >= $0.5M on MEXC) | | 177.0 | 62% removed |
| setups detected (BUY or SELL card) | 12,290 | 136.6 | 4,162 unique (coin, setup, signal day) |
| removed: long gate (BTC below 50d or 200d, breadth < 60%) | 5,952 | 66.1 | gate open in 40 of 90 scans (closed since 12 Oct) |
| removed: decay deactivated | 4,638 | 51.5 | Momentum Runner, RSL, Donchian, Volume, Squeeze (while the long gate was open) |
| removed: retired (Breakdown Short 55d) | 0 | 0 | never detected on MEXC liquidity |
| removed: not validated | 1,643 | 18.3 | Relative Weakness Short (PF 0.48), Pullback to SMA50, Counter Trend Bounce, Confirmed Uptrend |
| removed: coin already held | 37 | 0.41 | same DS signal seen again while the paper trade is open |
| removed: drift at arm (> 3% from signal close) | 1 | 0.01 | |
| removed: stop cap (25%, DS 50%) | 0 | 0 | DS 50% cap did not bind |
| removed: funding crowding | 0 | 0 | never triggered (also 0 in forensics) |
| removed: open position cap (10) | 11 | 0.12 | book full from 26 Oct |
| removed: top_n 5 / diversify | 0 | 0 | |
| armed | 8 | 0.09 | all Distribution Short |
| invalidated before firing / cancelled unfired | 0 | | enter now shorts fire on the first poll |
| fired | 8 | | |
| basket cap (paper only) | 0 | | never more than 3 shorts a day |
| **tradeable alerts** | **8** | | **1.87 per week**: BOME 7 Oct, XMR 8 Oct, BTC and ACE 12 Oct, GIGGLE 13 Oct, UAI 19 Oct, AKT 21 Oct, ZEC 25 Oct |

Detected by type (30 days, per scan detections): Relative Strength Leader 5,318, Pullback to SMA50 2,912, Momentum Runner 2,249, Counter Trend Bounce 765, Relative Weakness Short 743, Confirmed Uptrend 114, Donchian 55d 102, **Distribution Short 57 (19 unique)**, Volume Breakout 18, Squeeze Breakout 12, **Downtrend Bounce Fade 0**.

Unique signals by their best outcome over the day's scans (30 days): long gate 2,203, decay 1,451, not validated 489, held 7, open cap 3, drift 1, armed 8. **Of the 19 unique DS signals, 8 became alerts, 7 were coins already held, 3 hit the open cap, 1 drifted.**

## 2. Funnel, last 7 days (21 scans)

| step | total | per scan |
|---|---|---|
| coins with candles | | 470.4 |
| liquid ($0.5M on MEXC) | | 164.3 |
| setups detected | 2,627 | 125.1 (884 unique) |
| removed: long gate | 2,316 | 110.3 |
| removed: decay | 0 (all already blocked by the long gate; 882 would also be decay blocked) | |
| removed: not validated | 290 | 13.8 |
| removed: held | 8 | 0.38 |
| removed: drift | 1 | 0.05 |
| removed: open cap (book 9 to 10 paper positions) | 11 | 0.52 |
| armed and fired | 1 | |
| **tradeable** | **1** (ZEC 25 Oct) | |

Unique DS signals in the week: 7 (1 alert, 2 held, 3 open cap, 1 drift). Downtrend Bounce Fade: 0 detections (needs BTC MIXED and $2M a day on MEXC volume: only 84 coins qualify on MEXC, 344 on Binance).

**Live ledger for comparison** (track_export.json of 28 Oct 21:39 UTC, old main code): 81 armed rows since 10 Oct; 13 counted fires plus 28 `over_cap` fires (22 Momentum Runner, 13 RSL, 6 DS); the last 7 days were 6 DS fires on 24 to 27 Oct and nothing since the 27 Oct 04:00 scan. The current rules would have sent fewer of those (BTC, ETHFI, PENDLE, SPX, UNI blocked by held coins and the open cap in the replay, because the replay also counts the DS paper trades of 7 to 21 Oct that the old code did not fire). Live today has about 5 free slots; each new DS keeps a slot for weeks.

## 3. Which gates cause the silence

| rank | gate | share of detections removed (30d) | is the silence right? |
|---|---|---|---|
| 1 | long gate + decay watch (all longs) | 86.2% (10,590 of 12,290) | **Yes.** These are the setups that went 0 for 32 on paper in October. |
| 2 | liquidity floor on MEXC volume (before detection) | 62% of coins, about 2/3 of DS/DBF signals | **No.** It is stricter than the research it relies on. |
| 3 | open cap counting paper trades | 3 unique DS in 30d (base), 23 with research volume | **Partly.** It protects against one correlated DS basket, but it blocks real alerts with trades he never took. |
| | not validated (mostly Relative Weakness Short) | 13.4% | Yes (PF 0.48). |

Everything else (drift, stop cap, funding, top_n, basket cap, invalidation) removes almost nothing in this market.

## 4. Base rate in this regime (survivor free shorts panel, docs/edge_fix/shorts.md)

827 Binance UM perps incl. 157 delisted, 2022-01 to 2026-10, live filters (DS stop <= 50%, DBF <= 25%, funding veto, one DBF per coin per 10 days):

| BTC regime (days) | signals per week | DS | DBF | after basket cap | median per week | weeks with zero |
|---|---|---|---|---|---|---|
| all days (1,759) | 5.60 | 3.28 | 2.32 | 3.42 | 1.0 | 38% |
| BTC below 50d (842) | 2.56 | 2.41 | 0.15 | 1.52 | 0 | 72% |
| **BTC below 50d, trend MIXED (343), today** | **6.29** | 5.92 | 0.37 | 3.73 | 1.5 | 35% |
| BTC trend DOWN (499) | 0 | 0 | 0 | 0 | 0 | 100% |

The live universe is about half the panel (177 liquid coins on MEXC volume, 449 with research volume, vs 827), and the open cap then binds, which is why the replay delivers 1.87 per week, not 3.7.

## 5. Options for more tradeable alerts without new edges

Extra alerts per week are from the 30 day replays unless stated.

| option | extra per week | risk to expectancy | verdict |
|---|---|---|---|
| **(e) Measure the liquidity floor like the research** (scan floor and DS $0.5M / DBF $2M on Bybit turnover, or MEXC x the coin's Binance/MEXC ratio) | DS+DBF unique signals 4.4 to 13.3 per week detected; **tradeable stays 1.87 because the open cap then binds from 8 Oct**; combined with (f): about +4 to +5 | None by construction: this is the universe the DS/DBF numbers were measured on (DS full period n 778, PF 2.01, +0.312R incl. small and delisted coins; delisted only +0.191R). Shorts.md V7 (turnover >= $5M, listed >= 180d) was +0.110R OOS but failed in sample selection, so smaller coins may be a little weaker. | **Do it** (fidelity fix). |
| **(f) Open cap counts taken trades (or only tradeable alerts younger than N days), paper rows keep tracking** | base +0.7; with (e) +5.4 before the basket cap (23 unique in 30d), roughly +4 after it (8 and 12 Oct were 6 and 7 signal days) | Per trade none. Portfolio risk up: DS signals cluster (forensics: 26/27 Oct book corr 0.58, beta to BTC about 2). Keep the basket cap 3/day and the $125 open risk cap on TAKEN trades. | **Do it**, with the basket cap kept. |
| (a) "Watch" tier, shorts only: validated DS/DBF blocked by a soft gate (open cap, top_n, basket cap, drift, stop cap), sent as FYI with the reason, not tradeable | base about 1 per week (4 unique in 30d); with (e) about 10 per week (45 unique); 7d with (e): 14 | Zero if not traded. Behavioural risk: he trades FYIs (his stated failure mode). Label hard and never include sizing. | Yes, as a once a day digest, not per signal. |
| (a') Watch tier for blocked longs | 3,549 unique validated longs in 30d (about 830 per week) | These are the exact longs that lost about -26R; FYI longs in a falling market invite revenge entries. | **No.** At most one line a day: "N long setups blocked by the long gate". |
| (b) More scan times (7 a day instead of 3) | **0.0** (same 8 alerts, same 4 watch shorts) | none | No value on daily bars. A 00:05 UTC only arm (shorts.md T9) is the better change for entry quality. |
| (c) Full Bybit perp universe | +47 coins (9% of 523) have no MEXC perp: about +0.2 per week. bybit_perps.json is from 10 Oct; newer listings are invisible. | none (same rules) | Cheap: refresh the saved list weekly; use Bybit turnover if a non US host is ever available. |
| (d) 25% stop cap interplay | DS cap (50%) removed 0 signals in 30d; DBF cap 25% removed 2 unique in 30d (only with research volume) | Raising DBF's cap is untested. For DS, shorts.md: 25 to 50% stops OOS +0.217R vs +0.422R for tight stops, PF 1.91 (25% cap, n 440) vs 2.01 (50%, n 778). | Leave as is. |

**Recommended package:** (e) + (f) + a shorts only watch digest. Expected in this regime: about **4 to 6 tradeable short alerts per week** (DS, occasional DBF), most weeks with at least one, plus a daily digest of 1 to 2 blocked shorts. Still 0 when BTC trend is DOWN; that is the research, not a bug. Before switching, run `research/trade_flow.py replay_binvol` with Bybit turnover once a Bybit reachable host exists, and keep paper tracking every fire.

## 6. "Your setup" paper tier (design only; the edge is tested by another agent)

Pattern (his description: a coin that ran up hard rolling over, shorted back to its MA): coin up >= 20% in 24h or >= 40% in 7d, peak >= 3 ATR above BOTH the 1h and 4h EMA20 (`utils/overext.measure`), and the 1h close crosses back below the 1h EMA20 under the peak. One per coin per 48h.

Frequency on the scanned universe, last 30 days: **2.8 per week** with 20d turnover >= $2M (MEXC volume, 12 hits, a hit on 33% of days), **6.8 per week** at >= $0.5M (29 hits, 57% of days); last 7 days 2 (QNT 26 Oct, NIL 27 Oct). Cap 3 per day (never bound).

Prior evidence to put in the footer: research/overext REPORT (37,615 pump episodes, 769 coins): every fade variant lost, PF 0.67 to 0.90; the best (OI +30%, funding > 0, BTC turning) PF 1.14, t 1.72, below the 3.21 bar; new_edges.md: 1h/4h stops cost 0.07 to 0.12R in fees.

Message (Telegram, separate tag, no Bybit block, no size; prices below are illustrative, not a real signal):

```
🧪 YOUR SETUP (paper, not a system trade): NIL rolling over
Ran +63% in 24h, peaked 4.1 ATR above the 4h 20 EMA, 1h just closed back under its 20 EMA.
Paper plan: short 0.4120, stop 0.4420 (above the 12h high), target 4h EMA20 0.3610, time stop 48h.
Your rule: trail 5% once 3 to 4% in profit.
Tracked as paper so we learn if your read beats the tested fades (PF 0.67 to 1.14 so far).
1 of max 3 today.
```

Paper rows: own label ("Your setup"), excluded from the open cap, the basket cap and the system record; weekly line in the record: n, win rate, R per trade, vs the same coins' DS/DBF.

## 7. Caveats

* Data proxy: MEXC perp candles and OKX funding (what the live US host sees); the research equivalent volume uses each coin's Binance/MEXC ratio over 7 to 26 Oct (median 13.4x), held constant.
* The replay counts every fire as an open position from the warm up on (track_from not reset); live reset tracking on 8 Oct and DS was approved only on 18 Oct, so the live book is emptier than the replay's.
* Not modelled: the macro deployment score gate (regime_score < 45 arms nothing). Forensics found replay and ledger agree scan by scan, so it did not bind for shorts.
* Momentum labels during the 40 open gate scans were blocked by decay as of today; on the real dates some were still active (that was the burst).

Reproduce: `TRADE_FLOW_CACHE=... python research/trade_flow.py refresh && ... funding && ... replay && ... replay_binvol && ... replay_hourly && ... report` (about 25 min per 30 day replay, 60 min for the hourly one).
