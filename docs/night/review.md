# Independent review: night/guardrails-grids-signals (57f1676..HEAD)

Reviewer: independent agent. I did not write any of this code. Tests: **87 passed** (`pytest -q`, 2.2 s).
Changes I made: one file only. `docs/night/grid_backtest.md` gets a "Reviewer re-checks" block, and the DOOD table is labelled as a $50 investment. **No code was changed.**
Scripts for every check below are in the scratchpad (`ts.py`, `nostop.py`, `hand.py`, `dbg3.py`, `res.py`, `ts1m.py`, `sel.py`, `dood.py`). They are not in the repo.

## Verdict on the grid backtest: HOLDS

**No grid family has an edge on this data, with or without the trader's stop rule.** The trader's own style loses money in every variant I tried. That holds without a stop, without a time cap, with 1m data, and after removing the coins that pumped. It wins about 60% of runs, and its losses are large. That is the "$100 to $2,000" profile: a run of wins that has not yet met its stop-outs or liquidations.

### 1. Suspected bookkeeping bug: REFUTED (high priority, now closed)
The suspicion came from a lattice test I wrote. A fee-free random walk on exact grid lines gave a mean of about 0. Adding 1e-13 relative noise moved it to about −0.85 to −2.1 USD.
- An independent re-implementation tracks only the pointer, position, and ∫pos·dx with fills at line prices, written from scratch. It matches `run_kernel` to **4e-13** over 3,000 noisy paths: mean −0.8494 vs −0.8494. The P&L accounting is exact.
- A hand-coded Bybit short-grid order book on real DOOD 5m bars matches the kernel to 4 decimals on 3 random starts. That run includes the initial taker open with slippage, maker fills, funding, the stop, and the time-cap close: +5.7282, +0.6516 and −4.7337 USD, identical in both.
- So the lattice drift is a property of that path, not an accounting error. When price lands 1e-13 short of a line, the order does not fill. The next step then crosses two lines in one leg, so the fill comes late, and the late fill pays for the reversal. Real prices never sit on line values, so this does not matter for real data.
- A fee-free GBM martingale with 240 sub-ticks per 5m bar shows the real path bias (400 paths, 7 days, 200 grids, ±20/25%):

  | sampling | neutral mean | short mean |
  |---|---|---|
  | tick | −0.38 ± 0.36 | +0.88 ± 0.92 |
  | 1m | −0.41 | +0.85 |
  | 5m OHLC | −1.50 | −0.20 |

  Tick and 1m are consistent with 0, as theory says they should be. 5m OHLC costs about $1.1 per trade, about 0.09R, on synthetic paths this volatile. That is the documented conservative bias, and it is not a bug.
- On real OKX 1m vs 5m data, using the trader's style (5x, ±20/25%, 72h, 8 coins, 839 runs each): 1m adds **+0.009R per trade at 200 grids** and +0.001R at 50 grids. The doc's "≤ +0.007R" is slightly low, but the conclusion stands. The trader-style expectancy is −0.31R per trade (−$3.89), more than 30× the bias.

**No fix was needed, so I did not rerun run.py or trader_style.py.** The results/ CSVs are unchanged and valid. I reproduced the trader_style row exactly: short_always 5x/200g gives n 4,289, PF 0.558, win 61.3%, exp −$3.89.

### 2. Bias hunt (does anything unfairly penalise grids?)
| Check | Finding | Direction |
|---|---|---|
| Fee double counting | None. The hand calculation matches: maker 0.02% per fill, taker 0.055% + 0.05% slippage only on the initial market open, the stop, the time-cap close and the take-profit exit. | fair |
| Slippage on grid fills | Not applied. Grid fills are at the line price, maker. | fair (slightly favours grids: no queue misses) |
| Initial position cost | The opening market fill pays taker + slippage on about 2/3 of the position (short ±20/25%: 45% of slots). This is real on Bybit. | fair |
| Funding sign | `pay = −pos·price·rate`: shorts receive when funding is positive. Correct. The mean funding effect was −$0.06 per trade, negligible. | fair |
| MMR 0.5% | **Optimistic.** DOOD's live liquidation implies 5.74%. Short, no stop, 7d at 5x with mmr 5%: PF falls from 0.54 to **0.43**, and liquidations rise from 14% to 20%. | favours grids |
| Liquidation loses the whole investment | Conservative but realistic for isolated margin. Only 3 of 4,289 trader-style runs were liquidated (with the stop on). | negligible |
| Stop at range edge | This is Bybit's own rule. Removing it is **worse**: PF 0.558 with the stop, 0.542 without (595 liquidations at −$50). | fair |
| 7-day time cap | Removing it is **worse**: PF 0.495, exp −$8.44. Without stop and without cap: PF 0.473, with 40% of runs liquidated. | fair |
| R normalisation | PF and win rate do not depend on R. The trader-style table is in $. | fair |
| PF per trade | One bot run = one trade, PF = gross wins / gross losses. Standard. | fair |
| 25% rejection in trader-style numbers | The rules=False rows are what is reported, and they have no rejections. The rules=True rows are 100% rejected, as stated. | fair |
| Period (Nov 2025 to Oct 2026) | Bear market: **81% of coins fell, median buy-and-hold −48%**, BTC −27%. That is the regime that *favours* short grids, and they still lost. | favours (short) grids |
| Universe = today's top MEXC volume | Survivorship *against* short grids. The coins with the most-negative totals pumped into the top-volume list: BTW +4,475% (−$2,295), BR +550%, CAP +396%. Restricting to the 57 coins listed in Nov 2025 that did not double: PF **0.69**, still below 1. | against short grids, but not decisive |
| Majors only (13 coins, n 674) | PF **1.05**, +$0.15 per trade. Breakeven, not an edge: n is small and this subset was picked after seeing the data. | — |
| Intrabar path O→L→H→C | Conservative. Bounded at about +0.01R per trade (above). | against grids, small |
| tp_exit at the bottom of a short grid | Bybit keeps a flat bot running there. Closing it banks the gain. Without tp_exit and without a cap, the bot is eventually liquidated (PF 0.32). | fair |

**Bottom line:** the biases in favour of grids (MMR, bear period, perfect maker fills) are larger than those against them (5m path, survivorship). The verdict is robust.
**Caveat to tell the trader:** grids "win often" (61 to 63%), and a $100 to $2,000 streak is entirely plausible. But about 1 run in 6 (stopped) to 1 in 7 (no stop, liquidated) gives back $37 to $50 per $50. With no stop and no time cap, 40% of runs end in liquidation. That is ruin risk, not an edge.

## 3. Guard vs simulator on the DOOD worst case: the two models AGREE. The headline figures differ because their inputs differ.
Setup: short 0.0016 to 0.0025, 200 grids, 5x, stop 0.0025125.

| model | investment | deploy | entry | loss at stop |
|---|---|---|---|---|
| guard `grid_worst_case` | 263.8642 | 1.0 | 0.002096 | **196.79** |
| sim `simulate` straight run | 263.8642 | (1.0) | 0.002096 | **198.33** (+1.5 = taker slippage on exit, maker fees on fills) |
| guard | 263.8642 | 1.0 | 0.0020221 (mark) | **223.24** ← the "$223.24" figure is measured from the mark, not the entry |
| guard | 263.8642 | 0.7509 | 0.002096 | **147.77** ← guard_watcher.md worked example |
| guard | 263.8642 | 0.7509 | 0.0020221 | 167.63 |
| sim | 50 | 1.0 | 0.0020, stop 0.002505 | **43.07** ← grid_backtest.md (investment $50, not $263.86) |

- Same inputs give the same answer to within 0.8% (the difference is exit slippage and fill fees).
- $43.07 is for a $50 bot. Scaled by 263.86/50 it is about $227, consistent with the guard's $223 to $230 at a ~0.0020 launch.
- **Which is right for the live bot:** $147.77 (deploy 0.7509, launch 0.002096). It is calibrated from the app's actual position: 210,560 DOOD across 93 cells.
- The deploy ratio is inferred from one snapshot. If Bybit really deploys the full investment × leverage, the figure is $197.
- Either way, the bot breaks the 25% rule ($65.97), the $125 open-risk cap and the daily cap.
- I labelled the doc's DOOD table as "$50 investment" so the two documents no longer look contradictory.

## 4. Integration edits (monitor.py, utils/tg_commands.py)
No crash path found. Every new block in `poll_once` and `_sizing_line` is wrapped in `try/except Exception` and logs at debug level. The alert text is built before the snapshot, and `send_message` runs whatever happens.

- **MEDIUM: the 1R lock is consumed by an alert the trader may not take.**
  - `poll_once` calls `Ledger().issue(...)` for every delivered alert, and `issue()` clears `guard:lock_1r`.
  - After a stop-out, the first alert shows "🔒 1R lock" (the text is built before `issue`), then consumes the lock.
  - If he skips that one and takes the second alert, the second carries no lock and no 1R sizing.
  - Fix before merge, or accept knowingly: `monitor.py` should register alerts without consuming the lock, for example `issue(..., consume_lock=False)`. Consume the lock only on `/took` or `/guard ... issue`.
- **LOW:** if `direction` is missing, the issued record defaults to `"long"`. A short taken later would not match and would be tagged unissued. Triggers normally carry a direction.
- **LOW: race.** `guard:issued` and `guard:day:*` are read-modify-write JSON blobs, written by both monitor (GitHub Actions) and watcher (self-hosted). Concurrent writes can drop an issued record, which produces a false "unissued" tag. This is rare at a 15-minute cadence.
- **Poll time.**
  - `snapshot()` waits at most 6 s per fired alert (`wait(timeout=budget)`). Background threads continue, and each HTTP call has a 6 s timeout.
  - Worst case is about 6 s × alerts per poll, so about 30 s at 5 alerts. Acceptable.
  - A shared 8-thread pool means hung sources from alert 1 can starve alert 2, but that alert's wait is still capped at 6 s. It just returns fewer fields.
  - `_sizing_line` adds 1 to 2 Supabase reads per alert.
- **`_sizing_line` cap_hit** replaces the sizing line with "Daily loss cap hit". That is correct and intended.
- **tg_commands.**
  - `/guard`, `/addbot`, `/rmbot` and `/bots` run inside `listen()`'s try/except, so an error replies with a message and does not crash.
  - `/guard` uses `GUARD_SMALLCAP_MMR = 0.05` for every grid, which is conservative for majors and fine.
  - `/guard ... issue` registers the setup only on ACCEPT, which is good.
  - **LOW:** `/addbot` accepts any string as a bot id, with no validation.

## 5. utils/bybit_account.py: read only, signing correct
- `_request` refuses every non-GET except `POST /v5/fgridbot/detail`, a read query that takes only a bot_id, and refuses before signing or sending.
- There is no order, cancel, close, transfer or withdrawal code. A grep found none in `bybit_account.py` or `watcher.py`.
- Hosts are allowlisted.
- Signing matches the Bybit V5 docs:
  - GET: `timestamp + api_key + recv_window + querystring`, and the signed querystring is byte-identical to the one in the URL (same `urlencode(sorted(...))`).
  - POST: `+ raw JSON body`, and the body sent is the same string that was signed.
  - Headers X-BAPI-API-KEY, -TIMESTAMP, -RECV-WINDOW and -SIGN are present, with HMAC-SHA256 hex.
- 403 is mapped to a geo-block error.
- Note: `/v5/fgridbot/detail` may need more than a "Read-Only" key permission. The code already classifies a 10005 error as a permission error and does not crash.

## 6. Test suite
`python -m pytest -q`: 87 passed. Nothing was changed in code, so no rerun was needed after edits.

## Must change before merge
1. (MEDIUM) Do not consume the 1R lock when an alert fires (monitor.py → `Ledger.issue`). Consume it on `/took` or `/guard ... issue` only.

## Should change (docs)
- grid_backtest.md: the 1m-vs-5m bias at 200 grids is about +0.009 to +0.012R, not "≤ +0.007R". The doc should also say that `MMR = 0.5%` flatters grids on small caps (at 5%, no-stop PF is 0.43). I added the key re-checks inline.
- `numba` is in requirements.txt, so the 15-minute monitor job now installs it on every run (about 40 MB) even though only research uses it. Consider a separate `requirements-research.txt`.
