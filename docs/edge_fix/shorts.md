# Shorts decay study (28 Oct 2026)

Owner: SHORTS DECAY agent. Code: `research/edge_fix_shorts.py` (tables), `research/edge_fix/shorts_core.py` (panel, detectors, 1h simulator), `research/edge_fix/shorts_signals.py` (signals and variant sims), `research/edge_fix/shorts_oi.py` (OI at signal), `research/edge_fix/shorts_fetch_binance_um.py` (data). No production file was edited. Proposed code changes are in section 6.

## 1. Verdict per setup

| Setup | Recommendation | Out of sample evidence (2025-07 to 2026-10, untouched) |
|---|---|---|
| Distribution Short | **KEEP with rule change**: add a 2R take profit (V5), pin the trail to 3.5 ATR of the signal, recompute the stop at arm time. Keep the 50% stop cap. | Base OOS n 292, PF 1.98, +0.309R, but 2nd OOS half closed at -7.3R (fails gate). With V5: n 292, PF 2.36, +0.427R, halves +120.3R / +4.4R, **passes gate**; delta +0.118R (p 0.00, Holm p 0.10). |
| Downtrend Bounce Fade | **KEEP as is** (thin edge, watch it) | n 261, PF 1.32, +0.077R, halves +10.1R / +9.9R, passes gate. No fix improved OOS. 2026 +0.073R (95% CI -0.12 to +0.22). |
| Breakdown Short (55d low) | **RETIRE** | Live rule (falling knife guard first, so only non oversold breakdowns, stop <= 25%) produced 10 trades in 58 months on 827 coins: untestable. The full rule (incl. oversold) has no edge: n 920, PF 1.04, +0.014R (CI -0.19 to +0.21). |

Is the 2026 Distribution Short weakness significant? On **closed** trades yes: 2026 n 109, PF 0.28, -0.376R (95% week-block CI -0.52 to -0.18) vs 2022 to 2025 +0.424R; difference -0.80R (CI -1.07 to -0.47, p < 0.001). But it is one regime episode, not steady decay: 102 of the 109 losses were stops/trails on signals from Jul, Aug, Sep 2026 (-6.5R, -17.6R, -16.4R) while BTC rallied from 58.6k to 84k and the share of coins above their 50d went from 16% to 71% (a broad alt rally from below the 200d). The 46 DS signals from 29 Aug to 25 Oct that are **still open** are marked to market at **+0.70R average, 89% in profit (+32.0R)**. Closed plus open, 2026 is about -9R on 155 signals (-0.06R). Downtrend Bounce Fade's 2026 dip vs prior years is not significant (diff -0.13R, CI -0.50 to +0.26).

The 25 Oct wide-stop rule: **not overfit and only mildly survivor biased, but no longer an improvement**. On the survivor-free universe the 25 to 50% stop bucket is n 338, PF 2.16, +0.329R (CI +0.12 to +0.52) over 2022 to 2026 (survivors only: PF 2.30, +0.357R, so survivor bias is about 0.03R; the claimed PF 2.71 included 2020 to 2021 and a survivor-only universe). In sample it beat tight stops (+0.431R vs +0.247R) but out of sample it trailed them (+0.217R vs +0.422R; undoing the rule, V9, OOS delta +0.113R, p 0.13, not significant, and it was worse in sample so it is not selected). In 2026 every stop bucket lost the same (about -0.37R). The rule did not cause the 2026 losses; keep it.

## 2. Data and method

* **Universe:** data.binance.vision archive of Binance USDT-M perpetuals, which keeps delisted contracts. 900 symbols listed, 827 with >= 60 days of 1h data after removing stablecoins, index and TradFi perps; **157 delisted** before 20 Oct 2026 (LUNA, FTT, SRM and many small caps). 1h klines from 2021-06 to 2026-10-26 (daily and 4h are resampled from 1h, UTC days), funding prints to 2026-09-30 (the current month is not archived yet, so October funding is 0 in the P&L and the funding veto uses the last September print), OI in coin units from the 5m metrics archive (from 2021-12, 1805 of 1809 DS/DBF signals covered). Binance listings are close to Bybit's; MEXC's long tail of tiny coins is not covered.
* **Detectors:** the live code. `skills/new_setups.detect` unchanged for DS and DBF. Breakdown Short = `skills/scanner.classify_setup` rule (close <= prior 55d low, SMA50 < SMA200, close < SMA200) and, because the falling knife guard returns first, only when NOT oversold; "BDS incl. oversold" is the full rule.
* **Live filters:** stop distance cap (DS 50%, others 25%), funding veto (skip when the last print <= -0.05%), one open trade per coin per setup.
* **Exits on 1h bars:** stop first each hour (a gap through the stop fills at the open), then target, then the trail ratchets off the best low (Bybit native and what `triggers/outcomes.py` does). Entry at the signal day close. Costs 0.36% round trip plus real funding. A trade open when a delisted coin's data ends is closed at its last price (kept, not dropped). 108 trades still open on live coins at the data end are excluded from the stats (MTM shown above).
* **Split:** in sample 2022-01 to 2025-06 (choose), out of sample 2025-07 to 2026-10 (test once). Selection rule fixed in advance: selected if the IS expectancy lift has a one sided week-block bootstrap p < 0.10 and IS n >= 25. All OOS p values are Holm adjusted over **38 variants** tried (24 planned, 7 added after the forensics note, V10, V11, V16 added after seeing results and labelled post hoc). Bootstraps resample whole calendar weeks because alt shorts fire in clusters.
* **Edge gate:** PF > 1, n >= 25, positive total R in both halves of the OOS period.

## 3. Forensics items (lead's note) answered

1. **Exit model for DS.** Bybit style trail off the best low every hour (what paper tracking does) vs the research model (`crypto_optimize._simulate`: daily close + 3.5 ATR). IS +0.314R vs +0.328R; **OOS +0.309R vs +0.273R; 2026 -0.376R vs -0.469R** (V12, not selected). Recommend the Bybit native intrabar trail at **3.5 x signal ATR**, which the trader can set on the exchange. Today paper tracking trails at the live stop distance (`risk`), which equals 3.5 ATR only when entry equals the signal close; pin it (section 6).
2. **Entry and stop misalignment (T9).** Modelled the live flow: scan h hours after the close, fire at the then price, stop fixed from the signal close, rejected only if price is > 3% below the signal close. DS OOS: research entry +0.309R; live as is +0.245R (+6h), +0.205R (+12h), +0.246R (+20h); **stop recomputed at arm time (price + 3.5 ATR): +0.322R, +0.295R, +0.296R**. Recomputing the stop recovers most of the gap; arming at the daily close scan is best. IS shows little difference (+0.304 to +0.337R), so this is a robustness fix, not an edge. DBF: delay cost is small and mixed (+0.077R at the close vs +0.055 to +0.111R).
3. **The SMA50 > SMA200 branch (BLESS, SPX).** Dropping it (V14, need +50% in 120 days) leaves IS +0.339R vs +0.314R but OOS falls to +0.144R (delta -0.165R). Allowing the branch only above the 200d (V15) is worse in sample (-0.072R) and only +0.051R OOS (p 0.17). Keep the branch as is.
4. **The hand edited validation entry.** Recomputed here on the survivor-free universe with the live rules: DS 2022 to 2026 n 778, PF 2.01, +0.312R, win 53%; 2026 n 109, PF 0.28, -0.376R. The JSON entry (n 40, PF 1.754, expectancy -0.415R) should be replaced (section 6).
5. **DBF fired 0 of 54 replayed scans, BDS 0.** Consistent: DBF needs BTC MIXED (its 2026 signals clustered in Jan, Apr, Aug), and live BDS produced 10 trades in 58 months in this study.
6. **Live losses were Momentum Runner longs.** Noted; nothing here depends on the 8 to 27 Oct ledger.

## 4. What was tried and rejected (OOS, see T7)

* Pre-registered OI rules: DS "OI 3d rising" selected IS (+0.089R, p 0.03) but OOS lift only +0.034R (p 0.32) on 111 trades, 2026 -0.282R. DBF "skip OI 7d >= +10%" selected IS (+0.055R, p 0.07), OOS +0.001R. Keep logging both on the ledger, do not gate.
* 4h / 1h confirmation entries (close below the signal day low): DS OOS +0.319R / +0.236R vs base +0.309R; DBF turns negative (-0.009R / -0.001R). Not worth the missed trades.
* Tighter time stops: DS 20d -0.280R OOS; DBF 5d -0.019R.
* BTC below its 4h EMA50: DS OOS +0.202R (worse than base), DBF too few trades.
* Liquidity and listing age (turnover >= $5M, listed >= 180 days): DS OOS +0.110R (Holm p 0.00) but it did not pass the IS selection (+0.015R, p 0.10), so by the rule it is not adopted; it is the strongest candidate for the next forward check.
* Skipping FOMC/CPI windows: no effect (DS +0.006R, DBF -0.019R).
* Post hoc (formulated after seeing 2026, OOS not clean): setup decay gate (last 20 closed trades mean R > 0) fails OOS gate; breadth not rising helps DS OOS (+0.147R) but loses in 2026 (-0.571R, n 28); BTC below its 50d SMA (V16): DS IS +0.366R (lift +0.052R, p 0.37), OOS n 86, PF 3.32, +0.589R, halves +28.2R / +22.5R, but no 2026 trade closed under it and 41 of the 46 profitable open October signals fired with BTC above its 50d. Not adopted; log it.

## 5. Current regime notes (2026)

* DS lost when BTC was above its 50d (all 109 closed 2026 trades) during the Jul to Sep alt rally; DS has worked best historically with BTC below its 50d (+0.43R full, +0.59R OOS) and when BTC is above its 200d (+0.37R vs -0.08R below).
* DBF is weakest when breadth is under 30% (OOS -0.11R, n 23) and with negative coin funding (OOS -0.04R, n 48).
* Portfolio effect not modelled: the study counts every signal; live caps at 10 open and 5 armed per scan, and the 50% per setup ceiling in `triggers/scan.py` limits the Jul to Sep style cluster losses.

## 6. Proposed code changes (not applied)

1. **DS 2R take profit while trailing (V5).**
   * `skills/new_setups.py:detect`: add column `tp_r` (NaN by default), set `out.loc[d, "tp_r"] = 2.0` for Distribution Short. `latest()` returns `"tp_r": None if pd.isna(row["tp_r"]) else float(row["tp_r"])`.
   * `triggers/scan.py:_armed_plan`: in the `if plan and entry:` branch keep `trailing = target is None` and add `"tp": entry - plan["tp_r"] * (stop - entry)` for shorts (mirror for longs) when `plan.get("tp_r")`, recomputed after any stop change (item 3).
   * `triggers/outcomes.py:_simulate`: after the stop/trail check and before the trail ratchet, `if t.get("tp") and ((short and l <= tp) or (not short and h >= tp)): return _closed(t, "target", tp, ...)`. The existing `trailing = ... and not t.get("target")` stays, because `tp` is a separate field (add `("tp", "REAL")` to `triggers/db.py:_OUTCOME_COLS`).
   * `monitor.py` alert text for DS: "trail 3.5 ATR, take profit at 2R (price X)" so the trader places the TP on Bybit.
2. **Pin the DS trail to 3.5 ATR of the signal.** `config.py:BYBIT_TRAIL`: add `"Distribution Short": {"k_atr": 3.5, "activate_r": 0.0}`. `triggers/outcomes.py:_simulate` line ~99: use `atr_e = float(t["atr"])` when the trigger carries the signal ATR (store `plan["atr"]` on the trigger at arm time), else the current `risk / stop_mult`.
3. **Recompute the stop at arm/fire time.** `monitor.py` `enter_now_short` branch: on "fire", when the trigger carries `atr` and `trail_atr`, set the stop to `price + trail_atr * atr` (short) and the TP from item 1, and persist them before alerting; keep the stop-hit and target checks against the original levels for invalidation. Alternative with the same effect: run the new setups scan within the first hour after 00:00 UTC (11:00 AEDT) so the fire price is the close.
4. **Retire Breakdown Short (55d low).** `config.py`: `RETIRED_SETUPS = {"Breakdown Short (55d low)"}`; `triggers/scan.py:scan_and_arm`: skip candidates whose `setup_label` is in it (before the stop/crowding checks around line 335) and `backtesting/crypto_validation.validated_setups`: exclude them. Keep the label in the scanner for display.
5. **Replace the hand edited validation entry.** `data/crypto_validation.json` `stats["Distribution Short"]`: n 778, profit_factor 2.01, expectancy_r 0.312, win_rate 0.53, with a note "survivor-free Binance UM 2022-01 to 2026-10, 1h Bybit-style trail, docs/edge_fix/shorts.md; 2026 closed n 109 PF 0.28 -0.376R". Better: make `backtesting/crypto_validation` call `research/edge_fix/shorts_signals.run_symbol` for the new setups so the weekly revalidation stops using the close trail model.
6. **Leave as is:** the 50% DS stop cap (`MAX_STOP_PCT_BY_SETUP`), the SMA50 > SMA200 branch, DBF rules, the funding veto.
7. **Tests to add offline:** `tests/test_outcomes.py` cases for a short that hits `tp` before the trail, a trail using stored `atr`, and the restop at fire; `tests/test_new_setups.py` asserting `tp_r` is 2.0 on DS rows and NaN otherwise.

Reproduce: `python research/edge_fix/shorts_fetch_binance_um.py DATA && python research/edge_fix/shorts_signals.py DATA OUT && python research/edge_fix/shorts_oi.py OUT && python research/edge_fix_shorts.py OUT` (about 45 min download, 2 min signals, 3 min OI, 10 min tables).

# Tables (generated by research/edge_fix_shorts.py)

Universe: 827 Binance USDT-M perps with >= 60 days of data, 157 of them delisted before 20 Oct 2026. Signals 2022-01-01 to 2026-10-26: 5138 raw (all filters off), 108 still open at data end on live coins (excluded).

## T1 Headline, live versions, full period 2022-01 to 2026-10

| Setup | n | PF | exp R | win | 95% CI exp R (week bootstrap) | survivors only: n / PF / exp R | delisted coins only: n / exp R |
|---|---|---|---|---|---|---|---|
| DS | 778 | 2.01 | +0.312 | 53% | +0.08 to +0.53 | 645 / 2.15 / +0.337 | 133 / +0.191 |
| DBF | 639 | 1.49 | +0.148 | 68% | -0.06 to +0.36 | 557 / 1.50 / +0.143 | 82 / +0.186 |
| BDS | 10 | 3.98 | +0.507 | 70% | -0.10 to +1.09 | 9 / 3.35 / +0.445 | 1 / +1.067 |
| DS old cap 25% | 440 | 1.91 | +0.299 | 52% | -0.01 to +0.58 | 357 / 2.04 / +0.322 | 83 / +0.203 |
| BDS incl. oversold | 920 | 1.04 | +0.014 | 41% | -0.19 to +0.21 | 808 / 1.02 / +0.007 | 112 / +0.067 |

## T2 By quarter (live versions): n, PF, exp R

| Quarter | DS n | DS PF | DS expR | DBF n | DBF PF | DBF expR | BDS n | BDS PF | BDS expR |
|---|---|---|---|---|---|---|---|---|---|
| 2022Q1 | 14 | 70.97 | +0.91 | 19 | 0.72 | -0.16 | 0 |  |  |
| 2022Q2 | 1 | 0.00 | -0.80 | 12 | 6.83 | +0.51 | 0 |  |  |
| 2022Q3 | 1 | 0.00 | -0.99 | 29 | 2.51 | +0.30 | 0 |  |  |
| 2022Q4 | 5 | 2.08 | +0.33 | 2 | inf | +0.60 | 0 |  |  |
| 2023Q1 | 6 | 2.80 | +0.31 | 36 | 0.13 | -0.77 | 0 |  |  |
| 2023Q2 | 97 | 3.55 | +0.59 | 3 | inf | +0.32 | 0 |  |  |
| 2023Q3 | 15 | 4.98 | +0.51 | 6 | 1.33 | +0.11 | 0 |  |  |
| 2023Q4 | 34 | 0.11 | -0.39 | 48 | 0.21 | -0.65 | 1 | 0.00 | -0.67 |
| 2024Q1 | 72 | 0.06 | -0.74 | 0 |  |  | 0 |  |  |
| 2024Q2 | 90 | 1.44 | +0.17 | 0 |  |  | 0 |  |  |
| 2024Q3 | 8 | 1.26 | +0.05 | 64 | 3.74 | +0.91 | 0 |  |  |
| 2024Q4 | 20 | 2.37 | +0.28 | 13 | 4.86 | +0.30 | 0 |  |  |
| 2025Q1 | 113 | 26.87 | +1.07 | 6 | inf | +0.58 | 0 |  |  |
| 2025Q2 | 10 | 0.14 | -0.27 | 140 | 3.92 | +0.38 | 0 |  |  |
| 2025Q3 | 151 | 4.11 | +0.68 | 0 |  |  | 0 |  |  |
| 2025Q4 | 32 | 14.86 | +0.87 | 3 | inf | +0.41 | 1 | inf | +1.24 |
| 2026Q1 | 3 | 8.67 | +1.11 | 73 | 2.92 | +0.26 | 0 |  |  |
| 2026Q2 | 15 | 0.72 | -0.16 | 91 | 0.82 | -0.06 | 5 | 16.96 | +0.89 |
| 2026Q3 | 86 | 0.12 | -0.47 | 94 | 1.25 | +0.06 | 3 | 1.08 | +0.02 |
| 2026Q4 | 5 | 0.19 | -0.31 | 0 |  |  | 0 |  |  |

## T3 By year with 95% week-block bootstrap CI of exp R

| Setup | Year | n | PF | exp R | win | 95% CI |
|---|---|---|---|---|---|---|
| DS | 2022 | 21 | 4.59 | +0.596 | 76% | +0.10 to +0.99 |
| DS | 2023 | 152 | 2.32 | +0.353 | 59% | +0.03 to +0.61 |
| DS | 2024 | 190 | 0.67 | -0.169 | 33% | -0.50 to +0.26 |
| DS | 2025 | 306 | 6.80 | +0.817 | 74% | +0.58 to +1.04 |
| DS | 2026 | 109 | 0.28 | -0.376 | 19% | -0.52 to -0.18 |
| DBF | 2022 | 62 | 1.75 | +0.211 | 69% | -0.25 to +0.67 |
| DBF | 2023 | 93 | 0.22 | -0.613 | 23% | -0.74 to -0.20 |
| DBF | 2024 | 77 | 3.79 | +0.805 | 71% | +0.09 to +1.21 |
| DBF | 2025 | 149 | 4.18 | +0.388 | 87% | +0.16 to +0.64 |
| DBF | 2026 | 258 | 1.30 | +0.073 | 72% | -0.12 to +0.22 |
| BDS | 2023 | 1 | 0.00 | -0.669 | 0% | n/a |
| BDS | 2025 | 1 | inf | +1.236 | 100% | n/a |
| BDS | 2026 | 8 | 5.35 | +0.563 | 75% | -0.11 to +1.30 |

## T4 Is 2026 different from 2022 to 2025? (difference in exp R, week-block bootstrap)

| Setup | pre-2026 n / exp R | 2026 n / exp R | diff | 95% CI of diff | p(2026 not worse) |
|---|---|---|---|---|---|
| DS | 669 / +0.424 | 109 / -0.376 | -0.801 | -1.07 to -0.47 | 0.000 |
| DBF | 381 / +0.199 | 258 / +0.073 | -0.126 | -0.50 to +0.26 | 0.253 |
| BDS | 2 / +0.284 | 8 / +0.563 | +0.279 | -1.10 to +1.68 | 0.639 |

## T5 Regime splits (live versions). Cells: n / PF / exp R. Full = 2022-01 to 2026-10, OOS = 2025-07 to 2026-10

| Split | Bucket | DS full | DS OOS | DBF full | DBF OOS | BDS full | BDS OOS |
|---|---|---|---|---|---|---|---|
| BTC vs 50d | BTC < 50d | 285 / 2.70 / +0.43 | 86 / 3.32 / +0.59 | 19 / 7.89 / +0.37 | 3 / inf / +0.41 | 4 / inf / +1.18 | 4 / inf / +1.18 |
| BTC vs 50d | BTC > 50d | 493 / 1.71 / +0.24 | 206 / 1.57 / +0.19 | 620 / 1.46 / +0.14 | 258 / 1.30 / +0.07 | 6 / 1.21 / +0.06 | 5 / 1.99 / +0.20 |
| BTC vs 200d | BTC < 200d | 97 / 0.79 / -0.08 | 68 / 0.45 / -0.26 | 290 / 1.19 / +0.05 | 179 / 1.18 / +0.05 | 8 / 5.35 / +0.56 | 8 / 5.35 / +0.56 |
| BTC vs 200d | BTC > 200d | 681 / 2.24 / +0.37 | 224 / 2.78 / +0.48 | 349 / 1.73 / +0.23 | 82 / 1.82 / +0.14 | 2 / 1.85 / +0.28 | 1 / inf / +1.24 |
| BTC trend label | DOWN |  |  |  |  | 4 / inf / +1.18 | 4 / inf / +1.18 |
| BTC trend label | MIXED | 391 / 1.79 / +0.25 | 163 / 1.45 / +0.16 | 639 / 1.49 / +0.15 | 261 / 1.32 / +0.08 | 5 / 0.48 / -0.18 | 4 / 0.79 / -0.05 |
| BTC trend label | UP | 387 / 2.24 / +0.38 | 129 / 2.99 / +0.49 |  |  | 1 / inf / +1.24 | 1 / inf / +1.24 |
| BTC 4h vs EMA50 | BTC 4h < EMA50 | 375 / 2.27 / +0.34 | 139 / 1.59 / +0.20 | 71 / 1.81 / +0.14 | 47 / 1.88 / +0.14 | 6 / 6.82 / +0.74 | 6 / 6.82 / +0.74 |
| BTC 4h vs EMA50 | BTC 4h > EMA50 | 403 / 1.83 / +0.29 | 153 / 2.39 / +0.41 | 568 / 1.47 / +0.15 | 214 / 1.25 / +0.06 | 4 / 1.70 / +0.17 | 3 / 5.78 / +0.44 |
| Breadth (coins > 50d) | breadth 30 to 60% | 224 / 3.25 / +0.57 | 110 / 2.42 / +0.41 | 110 / 1.49 / +0.11 | 83 / 1.85 / +0.16 | 5 / 3.01 / +0.42 | 5 / 3.01 / +0.42 |
| Breadth (coins > 50d) | breadth <30% | 410 / 1.62 / +0.21 | 112 / 1.72 / +0.24 | 46 / 1.43 / +0.11 | 23 / 0.71 / -0.11 | 5 / 5.48 / +0.60 | 4 / inf / +0.92 |
| Breadth (coins > 50d) | breadth >60% | 144 / 1.66 / +0.21 | 70 / 1.81 / +0.26 | 483 / 1.49 / +0.16 | 155 / 1.24 / +0.06 |  |  |
| Coin funding (last 3) | funding 0..0.01% | 363 / 2.23 / +0.36 | 180 / 1.97 / +0.30 | 338 / 1.80 / +0.19 | 178 / 1.17 / +0.04 | 3 / 4.44 / +0.87 | 3 / 4.44 / +0.87 |
| Coin funding (last 3) | funding < 0 | 94 / 1.78 / +0.23 | 55 / 1.71 / +0.23 | 94 / 1.17 / +0.05 | 48 / 0.86 / -0.04 | 4 / inf / +0.55 | 4 / inf / +0.55 |
| Coin funding (last 3) | funding >= 0.01% | 321 / 1.86 / +0.29 | 57 / 2.28 / +0.41 | 207 / 1.29 / +0.12 | 35 / 5.32 / +0.42 | 3 / 1.31 / +0.10 | 2 / 4.44 / +0.48 |
| OI 3d (coin units) | OI 3d 0..+10% | 312 / 2.29 / +0.38 | 102 / 2.14 / +0.34 | 151 / 1.51 / +0.19 | 58 / 1.13 / +0.03 |  |  |
| OI 3d (coin units) | OI 3d <= 0 | 415 / 1.78 / +0.25 | 181 / 1.90 / +0.29 | 460 / 1.54 / +0.15 | 193 / 1.36 / +0.08 |  |  |
| OI 3d (coin units) | OI 3d > +10% | 47 / 2.21 / +0.40 | 9 / 2.05 / +0.43 | 28 / 0.94 / -0.03 | 10 / 1.83 / +0.17 |  |  |

## T6 Distribution Short by stop distance (funding veto on, no stop cap)

| Stop % | all 2022 to 2026: n / PF / exp R | survivors only: n / PF / exp R | IS 2022 to 2025-06 | OOS 2025-07 to 2026-10 | 2026 only |
|---|---|---|---|---|---|
| 0 to 15 | 98 / 1.44 / +0.163 | 82 / 1.66 / +0.223 | 82 / 1.32 / +0.122 | 16 / 2.20 / +0.373 | 5 / 0.13 / -0.518 |
| 15 to 25 | 342 / 2.07 / +0.338 | 275 / 2.17 / +0.351 | 227 / 1.90 / +0.292 | 115 / 2.45 / +0.429 | 45 / 0.30 / -0.363 |
| 25 to 35 | 259 / 2.15 / +0.334 | 220 / 2.35 / +0.375 | 148 / 2.50 / +0.399 | 111 / 1.77 / +0.247 | 38 / 0.23 / -0.403 |
| 35 to 50 | 79 / 2.19 / +0.315 | 68 / 2.13 / +0.298 | 29 / 5.56 / +0.597 | 50 / 1.44 / +0.151 | 21 / 0.36 / -0.322 |
| 50 to max | 16 / 1.05 / +0.016 | 13 / 1.62 / +0.178 | 5 / 1.01 / +0.005 | 11 / 1.06 / +0.022 | 6 / 0.45 / -0.242 |
| 0 to 25 | 440 / 1.91 / +0.299 | 357 / 2.04 / +0.322 | 309 / 1.72 / +0.247 | 131 / 2.42 / +0.422 | 50 / 0.28 / -0.379 |
| 25 to 50 | 338 / 2.16 / +0.329 | 288 / 2.30 / +0.357 | 177 / 2.77 / +0.431 | 161 / 1.66 / +0.217 | 59 / 0.27 / -0.374 |
| 0 to 50 | 778 / 2.01 / +0.312 | 645 / 2.15 / +0.337 | 486 / 2.03 / +0.314 | 292 / 1.98 / +0.309 | 109 / 0.28 / -0.376 |

25 to 50% bucket exp R 95% CI (week bootstrap): +0.115 to +0.523; PF 2.16, n 338.

## T7 Candidate fixes: chosen on IS (2022-01 to 2025-06), tested untouched on OOS (2025-07 to 2026-10)

Cells: n / PF / exp R. delta = variant exp R minus live base exp R on the same period; p one sided week-block bootstrap. Holm p corrects over every variant tried (all setups).

| Setup | Variant | IS n/PF/expR | IS delta (p) | selected | OOS n/PF/expR | OOS delta (p, Holm p) | OOS halves R | 2026 n/expR | OOS edge gate |
|---|---|---|---|---|---|---|---|---|---|
| DS | BASE (live) | 486 / 2.03 / +0.314 | | | 292 / 1.98 / +0.309 | | +97.6 / -7.3 | 109 / -0.376 | fail |
| DS | V1 OI 3d rising (pre-registered) | 252 / 2.36 / +0.403 | +0.089 (0.03) | YES | 111 / 2.13 / +0.343 | +0.034 (0.32, 1.00) | +41.0 / -2.9 | 47 / -0.282 | fail |
| DS | V2 entry: 4h close below signal-day low (48h) | 214 / 3.14 / +0.417 | +0.103 (0.24) | no | 151 / 2.35 / +0.319 | +0.010 (0.44, 1.00) | +48.1 / +0.1 | 48 / -0.325 | PASS |
| DS | V3 entry: 1h close below signal-day low (24h) | 180 / 2.78 / +0.399 | +0.085 (0.32) | no | 119 / 1.82 / +0.236 | -0.073 (0.77, 1.00) | +27.7 / +0.3 | 42 / -0.399 | PASS |
| DS | V4 time stop 20d | 486 / 1.53 / +0.153 | -0.161 (1.00) | no | 292 / 1.11 / +0.030 | -0.280 (0.99, 1.00) | +8.0 / +0.6 | 109 / -0.272 | PASS |
| DS | V5 add 2R take profit | 486 / 2.18 / +0.361 | +0.047 (0.04) | YES | 292 / 2.36 / +0.427 | +0.118 (0.00, 0.10) | +120.3 / +4.4 | 109 / -0.369 | PASS |
| DS | V6 only when BTC below 4h EMA50 | 236 / 2.87 / +0.420 | +0.105 (0.24) | no | 139 / 1.59 / +0.202 | -0.107 (0.78, 1.00) | +35.8 / -7.6 | 44 / -0.517 | fail |
| DS | V7 turnover >= $5M and listed >= 180d | 472 / 2.10 / +0.329 | +0.015 (0.10) | no | 229 / 2.48 / +0.419 | +0.110 (0.00, 0.00) | +61.8 / +34.2 | 62 / -0.379 | PASS |
| DS | V8 skip FOMC/CPI in next 48h | 445 / 2.16 / +0.347 | +0.033 (0.10) | no | 258 / 2.01 / +0.315 | +0.006 (0.50, 1.00) | +82.8 / -1.6 | 86 / -0.448 | fail |
| DS | V9 stop cap 25% (undo 25 Oct rule) | 309 / 1.72 / +0.247 | -0.067 (0.81) | no | 131 / 2.42 / +0.422 | +0.113 (0.13, 1.00) | +57.1 / -1.8 | 50 / -0.379 | fail |
| DS | V12 exit: research close trail (close + 3.5 ATR, daily) | 486 / 1.99 / +0.328 | +0.014 (0.34) | no | 286 / 1.78 / +0.273 | -0.036 (0.83, 1.00) | +77.4 / +0.8 | 103 / -0.469 | PASS |
| DS | V13 arm 12h after close at live price, stop recomputed | 424 / 1.91 / +0.290 | -0.024 (0.72) | no | 238 / 1.92 / +0.295 | -0.014 (0.60, 1.00) | +78.8 / -8.6 | 95 / -0.342 | fail |
| DS | V14 drop the sma50 > sma200 branch (need +50% in 120d) | 120 / 2.14 / +0.339 | +0.025 (0.40) | no | 78 / 1.44 / +0.144 | -0.165 (0.93, 1.00) | +13.6 / -2.3 | 28 / -0.417 | fail |
| DS | V15 sma50 > sma200 branch only above the 200d | 278 / 1.74 / +0.242 | -0.072 (0.84) | no | 201 / 2.19 / +0.360 | +0.051 (0.17, 1.00) | +64.5 / +7.9 | 69 / -0.406 | PASS |
| DS | V10 (post hoc) setup decay gate: last 20 closed trades mean R > 0 | 224 / 4.03 / +0.573 | +0.259 (0.06) | YES | 75 / 1.94 / +0.279 | -0.030 (0.55, 1.00) | +24.3 / -3.4 | 36 / -0.085 | fail |
| DS | V11 (post hoc) breadth not rising: breadth50 <= its value 20d ago | 304 / 1.93 / +0.297 | -0.017 (0.57) | no | 163 / 2.67 / +0.456 | +0.147 (0.08, 1.00) | +47.2 / +27.1 | 28 / -0.571 | PASS |
| DS | V16 (post hoc) only when BTC below its 50d SMA | 199 / 2.43 / +0.366 | +0.052 (0.37) | no | 86 / 3.32 / +0.589 | +0.280 (0.04, 1.00) | +28.2 / +22.5 | 0 / +nan | PASS |
| DBF | BASE (live) | 378 / 1.57 / +0.197 | | | 261 / 1.32 / +0.077 | | +10.1 / +9.9 | 258 / +0.073 | PASS |
| DBF | V1 skip OI 7d >= +10% (pre-registered) | 288 / 1.78 / +0.252 | +0.055 (0.07) | YES | 207 / 1.33 / +0.078 | +0.001 (0.53, 1.00) | +5.9 / +10.3 | 206 / +0.075 | PASS |
| DBF | V2 entry: 4h close below signal-day low (48h) | 165 / 1.84 / +0.161 | -0.037 (0.69) | no | 114 / 0.95 / -0.009 | -0.086 (0.92, 1.00) | -0.8 / -0.3 | 112 / -0.012 | fail |
| DBF | V3 entry: 1h close below signal-day low (24h) | 146 / 2.10 / +0.196 | -0.001 (0.52) | no | 96 / 0.99 / -0.001 | -0.078 (0.86, 1.00) | -1.9 / +1.8 | 93 / -0.007 | fail |
| DBF | V4 time stop 5d | 378 / 1.59 / +0.174 | -0.024 (0.66) | no | 261 / 1.26 / +0.058 | -0.019 (0.70, 1.00) | +0.3 / +14.8 | 258 / +0.054 | PASS |
| DBF | V5 breakeven at +0.5R | 378 / 1.37 / +0.093 | -0.104 (0.93) | no | 261 / 1.24 / +0.048 | -0.028 (0.76, 1.00) | +6.2 / +6.4 | 258 / +0.044 | PASS |
| DBF | V6 only when BTC below 4h EMA50 | 24 / 1.70 / +0.143 | -0.055 (0.53) | no | 47 / 1.88 / +0.138 | +0.061 (0.40, 1.00) | +5.6 / +0.9 | 44 / +0.120 | PASS |
| DBF | V7 turnover >= $5M and listed >= 180d | 334 / 1.39 / +0.131 | -0.066 (0.94) | no | 158 / 1.56 / +0.124 | +0.047 (0.09, 1.00) | +17.6 / +2.0 | 155 / +0.119 | PASS |
| DBF | V8 skip FOMC/CPI in next 48h | 369 / 1.57 / +0.199 | +0.002 (0.41) | no | 242 / 1.25 / +0.057 | -0.019 (0.81, 1.00) | +6.1 / +7.8 | 239 / +0.053 | PASS |
| DBF | V13 arm 12h after close at live price, stop recomputed | 249 / 1.18 / +0.078 | -0.119 (1.00) | no | 222 / 1.45 / +0.111 | +0.034 (0.35, 1.00) | +27.6 / -3.1 | 220 / +0.105 | fail |
| DBF | V10 (post hoc) setup decay gate: last 20 closed trades mean R > 0 | 254 / 2.15 / +0.262 | +0.064 (0.35) | no | 138 / 1.28 / +0.069 | -0.008 (0.62, 1.00) | +21.1 / -11.6 | 135 / +0.061 | fail |
| DBF | V11 (post hoc) breadth not rising: breadth50 <= its value 20d ago | 20 / 0.97 / -0.008 | -0.206 (0.82) | no | 11 / 2.63 / +0.301 | +0.224 (0.12, 1.00) | +2.9 / +0.4 | 9 / +0.305 | fail |
| BDS | BASE (live) | 1 / 0.00 / -0.669 | | | 9 / 6.54 / +0.638 | | +4.1 / +1.6 | 8 / +0.563 | fail |
| BDS | V2 entry: 4h close below signal-day low (48h) | 1 / 0.00 / -0.691 | -0.023 (1.00) | no | 8 / 14.83 / +0.635 | -0.003 (0.55, 1.00) | +3.5 / +1.6 | 7 / +0.596 | fail |
| BDS | V3 entry: 1h close below signal-day low (24h) | 1 / 0.00 / -0.693 | -0.025 (1.00) | no | 8 / 14.95 / +0.659 | +0.021 (0.48, 1.00) | +3.6 / +1.7 | 7 / +0.623 | fail |
| BDS | V4 time stop 20d | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 9 / 6.95 / +0.685 | +0.047 (0.38, 1.00) | +3.6 / +2.5 | 8 / +0.616 | fail |
| BDS | V5 add 2R take profit | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 9 / 7.94 / +0.799 | +0.161 (0.11, 1.00) | +4.6 / +2.6 | 8 / +0.650 | fail |
| BDS | V6 only when BTC below 4h EMA50 | 0 | +nan (nan) | no | 6 / 6.82 / +0.735 | +0.097 (0.31, 1.00) | +4.2 / +0.2 | 6 / +0.735 | fail |
| BDS | V7 turnover >= $5M and listed >= 180d | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 2 / inf / +0.411 | -0.227 (0.76, 1.00) | +nan / +nan | 2 / +0.411 | fail |
| BDS | V8 skip FOMC/CPI in next 48h | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 6 / inf / +1.055 | +0.417 (0.09, 1.00) | +4.4 / +1.9 | 5 / +1.019 | fail |
| BDS | V12 exit: research close trail (close + 3.5 ATR, daily) | 1 / 0.00 / -0.852 | -0.183 (1.00) | no | 9 / 4.86 / +0.526 | -0.112 (1.00, 1.00) | +3.7 / +1.0 | 8 / +0.455 | fail |
| BDS | V13 arm 12h after close at live price, stop recomputed | 1 / 0.00 / -0.767 | -0.099 (1.00) | no | 6 / 8.09 / +0.747 | +0.109 (0.23, 1.00) | +4.4 / +0.1 | 5 / +0.643 | fail |
| BDS | V10 (post hoc) setup decay gate: last 20 closed trades mean R > 0 | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 9 / 6.54 / +0.638 | +0.000 (1.00, 1.00) | +4.1 / +1.6 | 8 / +0.563 | fail |
| BDS | V11 (post hoc) breadth not rising: breadth50 <= its value 20d ago | 1 / 0.00 / -0.669 | +0.000 (1.00) | no | 5 / inf / +1.192 | +0.553 (0.02, 0.62) | +3.5 / +2.4 | 4 / +1.180 | fail |

Variants tried: 38 (plus the base per setup). No other variants were run.

## T9 Entry timing: research (enter at the daily close) vs how live arms (scan h hours later, fire at the then price)

Live as is: stop fixed from the signal close, paper trail at the live stop distance, rejected if price is > 3% below the signal close or at the stop. Restop: same entry, stop recomputed as live price + 3.5 ATR (DS, BDS; DBF keeps its 7d-high stop). Cells n / PF / exp R.

| Setup | Model | IS | OOS | 2026 |
|---|---|---|---|---|
| DS | research: enter at daily close | 486 / 2.03 / +0.314 | 292 / 1.98 / +0.309 | 109 / 0.28 / -0.376 |
| DS | research exits (close trail) | 486 / 1.99 / +0.328 | 286 / 1.78 / +0.273 | 103 / 0.23 / -0.469 |
| DS | live as is, scan +6h | 454 / 2.12 / +0.337 | 272 / 1.75 / +0.245 | 104 / 0.29 / -0.363 |
| DS | live as is, scan +12h | 424 / 1.97 / +0.310 | 238 / 1.60 / +0.205 | 95 / 0.32 / -0.352 |
| DS | live as is, scan +20h | 393 / 1.83 / +0.269 | 222 / 1.76 / +0.246 | 92 / 0.36 / -0.317 |
| DS | restop at arm, scan +6h | 454 / 1.98 / +0.304 | 272 / 2.03 / +0.322 | 104 / 0.32 / -0.341 |
| DS | restop at arm, scan +12h | 424 / 1.91 / +0.290 | 238 / 1.92 / +0.295 | 95 / 0.32 / -0.342 |
| DS | restop at arm, scan +20h | 393 / 1.79 / +0.259 | 222 / 1.94 / +0.296 | 92 / 0.36 / -0.315 |
| DBF | research: enter at daily close | 378 / 1.57 / +0.197 | 261 / 1.32 / +0.077 | 258 / 1.30 / +0.073 |
| DBF | live as is, scan +6h | 292 / 1.48 / +0.188 | 246 / 1.31 / +0.073 | 244 / 1.28 / +0.066 |
| DBF | live as is, scan +12h | 249 / 1.18 / +0.078 | 222 / 1.45 / +0.111 | 220 / 1.42 / +0.105 |
| DBF | live as is, scan +20h | 215 / 1.13 / +0.056 | 204 / 1.21 / +0.055 | 203 / 1.20 / +0.054 |
| BDS | research: enter at daily close | 1 / 0.00 / -0.669 | 9 / 6.54 / +0.638 | 8 / 5.35 / +0.563 |
| BDS | research exits (close trail) | 1 / 0.00 / -0.852 | 9 / 4.86 / +0.526 | 8 / 3.97 / +0.455 |
| BDS | live as is, scan +6h | 1 / 0.00 / -0.753 | 8 / 7.00 / +0.621 | 7 / 5.26 / +0.505 |
| BDS | live as is, scan +12h | 1 / 0.00 / -0.786 | 6 / 8.21 / +0.696 | 5 / 5.94 / +0.573 |
| BDS | live as is, scan +20h | 0 | 6 / 8.76 / +0.928 | 6 / 8.76 / +0.928 |
| BDS | restop at arm, scan +6h | 1 / 0.00 / -0.739 | 8 / 6.43 / +0.606 | 7 / 4.96 / +0.505 |
| BDS | restop at arm, scan +12h | 1 / 0.00 / -0.767 | 6 / 8.09 / +0.747 | 5 / 6.08 / +0.643 |
| BDS | restop at arm, scan +20h | 0 | 6 / 4.21 / +0.602 | 6 / 4.21 / +0.602 |

## T8 Selected combination per setup (IS-selected rules AND-ed, post hoc V10/V11 left out), OOS result

| Setup | Rules | IS n/PF/expR | OOS n/PF/expR | OOS halves R | 2026 n/expR | OOS edge gate |
|---|---|---|---|---|---|---|
| DS | V1 + V5 | 252 / 2.48 / +0.440 | 111 / 2.46 / +0.445 | +49.1 / +0.2 | 47 / -0.260 | PASS |
| DBF | V1 | 288 / 1.78 / +0.252 | 207 / 1.33 / +0.078 | +5.9 / +10.3 | 206 / +0.075 | PASS |
| BDS | none selected on IS | | | | | |
