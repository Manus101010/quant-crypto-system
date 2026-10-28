# Edge fix: production changes (28 Oct 2026)

Implementation of docs/edge_fix/shorts.md section 6 and the forensics.md bug list, plus the basket risk guard and forward test logging. Tests: `tests/test_edge_fix.py` (26 offline tests). Full suite: 127 passed (101 existing + 26 new). No network in any test.

## Deploy note (Supabase)

Run `docs/edge_fix/SUPABASE_MIGRATION.sql` once in the Supabase SQL editor (`alter table public.triggers add column if not exists tp double precision;`). Until it runs nothing breaks: `triggers/supastore.py` drops the `tp` column from writes after the first "Could not find the 'tp' column" error (one warning in the log) and the take profit is also stored in `condition_json`, which `triggers/outcomes.trade_tp` reads as the fallback. Any other Supabase error still raises as before.

## 1. Distribution Short 2R take profit, end to end

| File: function | Before | After |
|---|---|---|
| skills/new_setups.py: `detect` | no take profit column | new column `tp_r`: 2.0 on Distribution Short rows (`DIST_TP_R`), NaN on every other row |
| skills/new_setups.py: `latest` | returned label, stop, target, trail_atr, max_hold, atr | also returns `tp_r` and `close` (the signal close) |
| skills/new_setups.py: `restop` (new) | | pure helper: stop = entry + trail_atr x ATR (short), tp = entry minus tp_r x risk. Returns (None, None) when the plan has no ATR multiple (Downtrend Bounce Fade) |
| skills/scanner.py: `new_setup_trade` | plan = {stop, target, trail_atr, max_hold, atr}; target text "no fixed target" | plan also carries numeric `entry`, `signal_close`, `signal_stop`, `tp_r`, `tp`; card says "take profit $X (2R) while you trail a 3.5x ATR stop"; rr "2.0:1" |
| triggers/scan.py: `_armed_plan` | plan stop as fixed from the signal close | returns `tp`, `tp_r`, `atr`, `trail_atr`, `signal_close`, `drift_pct`, `drift_blocked` |
| triggers/scan.py: `run_scan_and_arm` | enter_now_short condition {entry, stop, target, max_drift} | condition also stores `signal_close`, `atr`, `trail_atr`, `tp_r`, `tp`, `max_drift_up`, `max_stop_pct` |
| triggers/outcomes.py: `_simulate` | trailing trades had no take profit | after the stop/trail check: if the bar reaches `tp` the trade closes as "target" at the TP price (stop still checked first, conservative) |
| triggers/outcomes.py: `trade_tp`, `_cond` (new) | | tp from the `tp` column, else from `condition_json` |
| triggers/db.py: `_OUTCOME_COLS` | | `("tp", "REAL")` added (auto ALTER on SQLite) |
| triggers/db.py and triggers/supastore.py: `mark_fired` | (id, price, note) | optional `extra` limited to `stop`, `tp`, `condition_json` (the fire time plan). Supabase writes go through `_update_tolerant`; `set_outcome` accepts `tp` |
| monitor.py: `_alert_text` | trailing setups said "no fixed target" | "Take profit: $X (minus Y%, +2x your risk) for the whole position", then "Until then a trailing stop..." |
| monitor.py: `_bybit_block` | stop + trailing stop | adds "Take-profit: trigger $X (2R), trigger by Last price, Market close, whole position (set it with the trailing stop)" |

## 2. Trail from the stored signal ATR

* config.py: `BYBIT_TRAIL["Distribution Short"] = {"k_atr": 3.5, "activate_r": 0.0}`. Before: no entry, so paper tracking trailed at the live stop distance (equal to 3.5 ATR only when entry equals the signal close).
* triggers/outcomes.py `_simulate`: trail distance = k_atr x the ATR stored on the trigger (`condition_json["atr"]`, the signal ATR); falls back to the old `risk / stop_mult` for triggers without it.
* monitor.py `_bybit_block`: the trailing distance shown to the trader uses the same stored ATR.

## 3. Entry and stop alignment, upper drift bound

* Restop: Distribution Short is the only live setup whose stop was fixed from the signal close as an ATR multiple. Its stop is now re-anchored, keeping 3.5 ATR, at arm time (`scanner.new_setup_trade`, `scan._armed_plan`) and again at fire time (`monitor._fire_plan`, persisted with `mark_fired(extra=...)`). The armed stop is kept in `condition_json["stop_armed"]`. Downtrend Bounce Fade keeps its level stop (7 day high + 0.25 ATR), as researched. Generic setups already set their stop from the arm time price (`_armed_plan`), so they were not changed.
* Drift bounds (monitor.py `_evaluate`, kind enter_now_short): measured from the SIGNAL close (`signal_close`), not the arm price. Invalidate if price fell more than 3% (unchanged rule, new reference) or bounced more than 3% (new). Also invalidate if the re-anchored stop would exceed the setup's stop cap (50% for DS). Triggers armed before this change have no `signal_close`: they use their arm price and get the 3% upper bound by default.
* Arm time (triggers/scan.py): a candidate outside the same bounds gets status `drifted` and is not armed.
* Bound choice, config `ENTRY_DRIFT_UP_MAX_PCT = 3.0` (and `ENTRY_DRIFT_DOWN_MAX_PCT = 3.0`): neither study tested an upper bound directly, so this is a consistency bound, not a tuned edge. Evidence used: (a) shorts.md T9 shows that with the stop recomputed, entries 6 to 20 hours after the close keep the edge (OOS +0.295R to +0.322R vs +0.309R at the close), and that model already rejected moves larger than 3% the other way, so 3% symmetric keeps live inside the tested envelope; (b) forensics.md: live DS entries ranged from 1.3% below to 2.7% above the signal close, and the one bounce entry (BLESS, +2.7%) was the loss, armed only because the bounce shrank its stop under the old 25% cap. A bounce larger than 3% on a coin "slipping to the bottom of its range" is a sign the setup is failing; on a typical DS coin (daily ATR about 7.5%) it is about 0.4 ATR. Not done: a check that price is still below the 20 day range midpoint at fire (would need the midpoint stored on the plan).

## 4. Breakdown Short (55d low) retired

* config.py: `RETIRED_SETUPS = {"Breakdown Short (55d low)"}`.
* triggers/scan.py `run_scan_and_arm`: subtracted from the validated set with the deactivations, so it is never armed; it stays visible in `watch_only` with `retired: True` and in `gated_out_setups`.
* backtesting/crypto_validation.py `validated_setups` skips retired labels whatever their stats; `validated_labels` subtracts them from the saved list (covers revalidate.py too).
* data/crypto_validation.json: removed from `validated`. The scanner still labels it for display.

## 5. Validation entry for Distribution Short

`data/crypto_validation.json stats["Distribution Short"]` replaced. Before: hand edited, internally impossible (n 40, PF 1.754, expectancy minus 0.415R, exits summing to 62). After, recomputed from `sh/short_trades.parquet` of the shorts study (reproduces shorts.md T1 exactly): n 778, PF 2.01, expectancy +0.312R, win 53.5% (base exit); `avg_win` 1.299 / `avg_loss` minus 0.664 in R under the live exit (2R take profit, full period), flagged `avg_unit: "R"`; `oos_tp2r` n 292, PF 2.36, +0.427R, halves +120.3R / +4.4R, gate PASS; `oos_base` n 292, PF 1.98, +0.309R, halves +97.6R / minus 7.3R, gate fail; `full_tp2r` n 778, PF 2.25, +0.386R; `y2026_closed` n 109, PF 0.28, minus 0.376R (minus 0.369R with TP); plus a `note` with source, method and date. `median_bars_held` and `exits` were left out (not comparable to the old per bar model). monitor.py `_projection_line` now reads R unit stats correctly (typical winner = avg_win R, losers = avg_loss R) instead of treating avg_win/avg_loss as percent returns. The `recommended` block (computed by the old run) was not touched.

## 6. Forensics bugs

| Bug | File: function | Before | After |
|---|---|---|---|
| B5 forming candle | skills/scanner.py: `_run_from_bybit`, new `_drop_forming` | generic setups (Momentum Runner, RSL, Breakdown Short...) classified with price, SMAs, RSI, Donchian and volume including today's forming bar | all indicators and the label use the last CLOSED daily bar (same rule as `new_setups.latest`). The row `price` stays the live price (where an entry fills) and the trade plan is priced from it; new field `close_price` = last closed close |
| B7 no base | skills/scanner.py: `_SETUP_BASE` | DS and DBF scored base 25, below every long and outside the 60 row list | Distribution Short 74 (just above the trend longs at 71 to 73, from n 778 PF 2.01 and OOS 2R TP PF 2.36), Downtrend Bounce Fade 66 (level with the provisional shorts, thin OOS edge n 261 PF 1.32) |
| B8 $ in close alerts | triggers/outcomes.py: `_close_text`, new `planned_position`; monitor.py: `_sizing_line`, `_projection_line` | close alerts said R x $12.50 although integer leverage meant e.g. $9.45 (BTC DS, 9% stop, 2x) | one sizing rule (`planned_position`, the alert's own rule) gives the position, leverage and the $ a stop out loses; close alerts report R x that actual $ ("on the $9.00 the sized position risked at 2x"); the projection line uses it too. Sizing itself is unchanged |
| B9 sub cent round trip | skills/scanner.py: `_fmt_p`, `_run_from_bybit`; triggers/scan.py: `_armed_plan` | entry parsed back from "Short near $0.000012" and the row price rounded to 6 dp, several % off for coins under $0.0001 | plan carries the numeric entry; `price` is unrounded; `_fmt_p` keeps at least 4 significant digits ($0.00001234) so text parsed for generic setups is within 0.05% |

## 7. Basket risk guard

* config.py: `FIRE_CAP_PER_DIR_PER_DAY = 3`.
* monitor.py `poll_once`, new `_fired_today_counts`, `_basket_cap_text`: counts NEW tradeable fires per Sydney day (guard.ledger.sydney_day) per direction, all setups. A fire past the cap is still marked `fired` (paper tracked like any other, never re-statused, forensics B1), with `condition_json["basket_cap"] = true` and note "basket cap: ...". Instead of the trade alert the trader gets a short notice: "not a trade today (basket cap) ... N new short signals have already been sent today (Sydney day). Your cap is 3 per direction per day ... tracked as a paper trade only. Do not place it." No desk review and no guard ledger issue for capped fires. Fails open if the count cannot be read.
* triggers/outcomes.py: `is_basket_capped`; `live_stats` keeps every fired signal in `total` and `by_setup` and adds `tradeable` (alerted only) and `basket_cap` totals; `_close_text` labels capped rows "paper trade (basket cap, was not a tradeable alert)".
* triggers/scan.py: capped open rows still block their coin but do not use a MAX_OPEN_POSITIONS slot.

## 8. Forward test flags (logging only, no gating)

* skills/scanner.py: new `fwd_flags` per row, from closed bars: `turnover20_usd`, `listed_days_min` (lower bound: the scan fetches 400 daily bars), `liquid_5m_180d` (20d turnover >= $5M and listed >= 180 days, shorts.md V7), `btc_below_50d` (BTC closed daily bars).
* triggers/scan.py: stored in `condition_json["fwd"]` on every armed trigger (all setups).
* features/derivs.py: new `oi_change_okx(symbol, hours=72)`: OKX open interest in coin units, % change over 72 hours (the closest live proxy for the study's "OI 3d rising"; the study measured the 3 days before the signal close).
* monitor.py: new `_fwd_flags`; at fire `condition_json["fwd"]` gains `oi_chg_72h` and `oi_3d_rising`, and the same keys are copied as `fwd_*` into the features snapshot stored in app_state (`features:{id}`).
* Not done: the new listing ORB72 short as a paper only watch (new_edges.md C7). It needs its own scanner (Bybit listings in the last 30 days, 1h/4h candles, the first 72h range, a 4h close check every 4 hours) and its own trigger kind and exit (2R or 14 days). That is not cheap and it is post hoc, so it is left for a separate change.

## Chosen not to do (and why)

* B6 (momentum labels fire at ref x 1.005) and B10/B11: not in this brief; the long side is gated and the momentum setups are deactivated, and B10/B11 change validated behaviour without a re-validation.
* Restop for generic breakout/breakdown triggers: their stop is already set from the arm time live price, not the signal close.
* Making the weekly revalidation reproduce the shorts study (`research/edge_fix/shorts_signals.run_symbol`) and an audited overrides file for the edge gate (forensics B2 "better" fix): larger refactor. Note `backtesting/crypto_optimize` can still overwrite `crypto_validation.json` if run with save; `revalidate.py` does not save.
* Arming new setups only at the 00:05 close scan: shorts.md says recomputing the stop recovers most of the gap; the drift bounds cover the rest.
* OI filter gating, BTC 50d gating, liquidity gating: logged only, per the study (not selected in sample or post hoc).
