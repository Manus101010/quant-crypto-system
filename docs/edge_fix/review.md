# Independent review: production diff 6d7ffda..HEAD (28 to 29 Oct 2026)

Scope: `git diff 6d7ffda HEAD -- . ':!research' ':!docs'` (monitor.py, triggers/*, skills/scanner.py, skills/new_setups.py, config.py, backtesting/crypto_validation.py, features/derivs.py, desk/agents/llm.py, data/crypto_validation.json). Live safety came first. The reviewer wrote none of the original change.

Verdict: **safe to merge once the fixes below are in** (they are applied in the working tree, not committed). Tests: 130 passed (127 before plus 3 new, with 1 test rewritten). All touched modules parse under Python 3.11, the version the workflows run.

## Fixes applied by the reviewer (every change)

| # | File: function | Change | Why |
|---|---|---|---|
| F1 | config.py (new `DECAY_WATCH_MANUAL_ONLY = {"Distribution Short"}`), revalidate.py `run_revalidation`, `_notify` | When a setup in that set fails the weekly decay watch, the action is recorded as `warned` and it is never auto deactivated. A Telegram notice ("Decay watch failed a research-validated setup") lists it, with PF and n. The result dict gains `manual_review`. | See H1. |
| F2 | monitor.py `_fired_today_counts` | `fired_at` is parsed with `pd.Timestamp(str(fa))` instead of `fromisoformat(str(fa)[:26])`. | See M1. |
| F3 | triggers/scan.py `_armed_plan` and the `enter_now_short` condition; monitor.py `_evaluate` | The 3% upper drift bound now applies only to re-stopped (ATR multiple) plans, which today means Distribution Short. The scan stores `max_drift_up` only when the plan has `atr` and `trail_atr`. The monitor applies it only when the key is set: there is no default for older triggers or DBF. | See M2. |
| F4 | skills/new_setups.py `restop` | Returns (None, None) unless entry, atr and trail_atr are all finite and > 0, and casts them to float. | See L1. |
| F5 | triggers/supastore.py `_update_tolerant` | The missing column check also looks at `exc.message`, not just `str(exc)`. | Hardening. With postgrest 2.33, `str(APIError)` does contain `'tp'` (checked), but that depends on the library version. |
| T | tests/test_edge_fix.py | `test_evaluate_old_trigger_without_signal_close_gets_upper_bound` is replaced by `test_evaluate_upper_bound_only_for_restopped_plans`. New: `test_restop_rejects_non_finite`, `test_fired_today_counts_parses_trimmed_microseconds`, `test_revalidate_never_auto_deactivates_research_setup`. | |

## Findings, severity ordered

### H1 (fixed, F1): the weekly decay watch would switch off Distribution Short using the old harness
* revalidate.py runs weekly, Sunday 04:00, from launchd or the VPS timer, not from GitHub Actions. It re-tests every armable setup with `backtesting.crypto_optimize.validate_per_setup(save=False)`. For DS that is the old daily per-bar model: 3.5 ATR trail on daily closes, no 2R TP, no 50% cap, no funding, MEXC survivors. That is the same harness that produced the old, inconsistent n 40 entry.
* The band comes from the FRESH n (about 40), so DS counts as "provisional" and is **deactivated on the first failing run** (or warned first when PF is in [0.95, 1.0)). With 2026 DS negative, a failing run is likely. The research decision (keep DS with a 2R TP, validated on n 778) would then be undone silently by a different harness.
* revalidate.py does NOT overwrite `data/crypto_validation.json` (`save=False`), so the new DS entry survives it. The only path that overwrites the file is the Streamlit Validation page "Run Validation" button (`validate_per_setup(save=True)`). That button replaces all `stats` (DS goes back to old harness numbers) and `validated` (DS may drop out), and drops the `avg_unit: "R"` marker. It is manual only. **Trader: do not press "Run Validation"** until the revalidation reproduces the shorts study (CHANGES.md "Chosen not to do").
* DBF is left under the normal decay watch, because its json entry (n 63, PF 2.17) came from that same harness, so the comparison is like for like. It is "established" (n >= 50), so it needs two failing runs.
* Trade off: the guard keeps DS armed even when the old harness says it is failing. The weekly Telegram notice keeps the human in the loop, and 2026 DS is negative (n 109, PF 0.28 in `y2026_closed`). The trader should still decide DS on the live and forward record.

### M1 (fixed, F2): the basket cap could undercount on Python 3.11 and let a 4th and 5th short through
Postgres or PostgREST trims trailing zeros from microseconds (`...03.12345+00:00`). With `[:26]` that becomes `...03.12345+`, which Python 3.11 `fromisoformat` rejects (verified with /usr/bin/python3.11). The row was then skipped, so it was not counted. This fails open: more tradeable alerts, never a crash. It hits about 1 row in 10 if `fired_at` is a timestamptz. The new test covers both naive and trimmed forms.

### M2 (fixed, F3): the 3% upper drift bound also invalidated Downtrend Bounce Fade and pre-change triggers
CHANGES.md argues for the bound only with DS evidence ("slipping to the bottom of its range", BLESS). But the code applied it to every `enter_now_short`, which includes DBF, at arm time (status `drifted`) and at fire time. It also applied it, by default, to triggers armed before the change. DBF's stop is a level (7 day high + 0.25 ATR). Its researched live model (`shorts_signals.py` live6/12/20) has no upper bound, only `e1 >= stop` and `e1 < entry * 0.97`. A further bounce only moves a DBF entry toward its stop, and `price >= stop` already invalidates. So the bound was an untested filter that removed DBF trades. After the fix: DS keeps both bounds. DBF keeps the downward 3% bound, measured from the signal close as in the research. Old triggers behave as before.

### M3 (not fixed, pre-existing since 25 Oct): the desk guard verdict contradicts the alert for wide stop DS
`desk/agents/factpack._sizing` always uses $50 margin and `max(1, lev)`. For stops wider than about 24.5% (allowed up to 50% for DS), the alert sizes a smaller 1x position (`planned_position`). The desk instead checks $50 at 1x: the loss exceeds $12.50 and fails, and the alert's smaller margin would fail `guard.preflight.MIN_MARGIN` ($50) anyway. Outcome: the desk can say "reject" on a wide-stop DS that the alert says to take at reduced size. This is advisory text, not a crash or a skipped alert. Fix later: have `_sizing` call `triggers.outcomes.planned_position`, and decide whether MIN_MARGIN applies to deliberately reduced positions (a trader rule decision).

### M4 (not fixed, pre-existing): one bad write in the fire block aborts the rest of the poll and re-alerts
In `poll_once`, `tdb.mark_fired` runs after `telegram.send_message`. If the Supabase write raises (anything except the tolerated missing `tp`), the exception leaves `poll_once`. The main loop catches it, but the remaining triggers are not evaluated that poll, and the same trigger re-alerts on the next poll. This was true before the change. The change makes the write larger (condition_json is rewritten on every fire), which adds a little exposure. F4 removes the one realistic new trigger (a NaN stop). Suggest a per-trigger try/except around the fire block in a follow-up.

### L1 (fixed, F4): a NaN ATR could produce a NaN stop at fire
`restop` accepted NaN (`not nan` is False, and `nan <= 0` is False). A NaN stop would go into `mark_fired`, where Supabase or httpx rejects NaN JSON *after* the alert was sent. That leads to M4's re-alert loop. The odds are low (DS needs a finite ATR to be labelled), but the guard is free.

### L2 (OK, noted): paper exit model compared with research/edge_fix/shorts_core.py
* The order within a bar matches the research: gap through the stop fills at the open, then the stop or trail, then the target/TP, then the trail ratchets off the best price. A bar that touches both stop and TP closes at the stop (conservative).
* ATR source: the SIGNAL ATR stored on the plan (`condition_json.atr`), the same as research `3.5 * det["atr"]`.
* R definition: stop = fire price + 3.5 x signal ATR, TP = fire price - 2 x that risk. This matches research `tgt0 = entry - 2 * (stop - entry)` and the `_restop` variant (`st2 = e1 + 3.5 * atr_i`).
* Hand cases (fire 100, ATR 2: stop 107, TP 86): low 85 the next day gives a target at +2.00R. A day with high 103 and low 85 after the trail moved to 102 gives a trail exit at -0.29R (stop first). A fire at 102 (stop 109, TP 88) gives +2.00R.
* Known differences (approximations, not bugs): after the fire day, paper uses daily bars, so the trail ratchets once a day, not hourly, and same-bar stop/TP ties resolve to the stop. Paper R excludes the 0.36% cost and funding.
* Backward compatibility for the 6 open live trades: they have no `tp` and no `atr` in condition_json. `trade_tp` returns None, so no retroactive TP. The trail distance falls back to `risk / stop_mult`. With the new `BYBIT_TRAIL["Distribution Short"]` k 3.5 and `_TRAIL` stop_mult 3.5, that equals `risk`, identical to the old default. Simulated outcomes for those trades are unchanged. `_close_text` handles them through `planned_position(fired_price, stop)`. Supabase rows without a `tp` key are fine (`t.get`).

### L3 (OK): restop and sizing consistency
At fire, `t_fire` (re-anchored stop and TP) feeds the alert text, the Bybit block, `_sizing_line` (`planned_position`), the guard ledger issue and the desk review. `mark_fired(extra=...)` persists the same stop and TP for paper tracking, and the armed stop is kept as `stop_armed`. `_sizing_line` refactor: `pp["margin"] < $50` is equivalent to the old `lev < 1`. The 50% cap at fire (`k * atr / price > max_stop_pct`) equals the arm-time `stop_pct` cap. It is only active when `atr` and `trail_atr` are set (DS), so DBF and generic setups are unaffected. The only inconsistency left is the desk sizing in M3.

### L4 (OK): basket cap
* Days are Sydney days via `guard.ledger.sydney_day`, with naive timestamps treated as UTC. The count is per direction. It counts only fires that were not capped, loads once per poll, and increments in memory for fires in the same poll, so there is no double count.
* Exits and close alerts (`update_open_trades`) are untouched. Capped rows still block their coin, take no `MAX_OPEN_POSITIONS` slot, issue no guard ledger entry and get no desk review.
* `live_stats.total` still includes them by design. `tradeable` and `basket_cap` partition it, and the morning brief reads only the existing keys.
* If the count read fails, the cap fails open (more alerts, not fewer).

### L5 (OK): retired setups, validated set, validation JSON
* `RETIRED_SETUPS` is enforced in `validated_setups`, `validated_labels` (so revalidate.py never checks Breakdown Short) and `run_scan_and_arm`.
* The json DS entry is internally consistent: 0.535 x 1.299 - 0.465 x 0.664 = +0.386R, which equals `full_tp2r.expectancy_r`.
* R units are read correctly by `_projection_line` (`avg_unit == "R"`). `live_stats` and `scan` read only `profit_factor` and `n`. `revalidate.py` does not read the json stats (it reads fresh stats).
* The `recommended` block still holds the old DS row (PF 0.225, suggested_base 17.2), but no production code reads it.

### L6 (OK): classification on the last closed candle
`_drop_forming` removes the bar dated today UTC (Bybit daily index is 00:00 UTC open). Labels and indicators (SMA, RSI, ATR, Donchian, volume) use closed bars. The row `price`, trigger `ref_price`, entry text and breakout/breakdown levels (`ref * 1.005` or the entry) use the live price, which is where an entry fills. `close_price` is the closed close, and new_setups `close` is the signal close used for drift. Nothing downstream needs the forming bar.

## Offline runs
* `pytest -q`: 130 passed (Python 3.13). Every changed module passes `ast.parse` under Python 3.11.
* End to end offline: the existing tests already run `run_scan_and_arm` (stubbed universe: BDS retired, a DS bounced 4% blocked) and `monitor.poll_once` (SQLite, stubbed exchange, Telegram, OKX and ledger: basket cap, restop, TP and forward flags persisted). A hand run of `outcomes._simulate` and `_close_text` on old-shape and new-shape rows is in L2.

## What the trader must do
1. Run `docs/edge_fix/SUPABASE_MIGRATION.sql` in the Supabase SQL editor (adds `tp`). It is not required for safety, since the code tolerates the missing column, but until then each process logs one warning and reads TP from condition_json.
2. Do not press "Run Validation" on the Streamlit Validation page (it would overwrite the DS validation entry with old harness numbers).
3. Expect a weekly Telegram notice if the old harness fails DS. That notice is the prompt to decide DS by hand.
