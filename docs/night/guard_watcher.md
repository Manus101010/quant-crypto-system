# Guard + Watcher (night build, 27 Oct 2026)

Signal only. Nothing here places, modifies or closes an order. The Bybit client is read only by construction.

## What was built

| File | What it does |
|---|---|
| `utils/bybit_account.py` | Bybit V5 private read only client. Signs requests with HMAC SHA256 using the `X-BAPI-API-KEY`, `X-BAPI-TIMESTAMP`, `X-BAPI-RECV-WINDOW` and `X-BAPI-SIGN` headers. It covers wallet balance (UNIFIED), positions (linear, USDT, every page), closed P&L, executions and futures grid bot detail. It refuses every non GET request, with one exception: `POST /v5/fgridbot/detail` is allowlisted, because Bybit only offers that read query as a POST. A 403 raises `BybitGeoBlocked` with the message "runner must be NON US". Base URL host allowlist: api.bybit.com, api.bytick.com, api-testnet.bybit.com. |
| `guard/preflight.py` | Pure rule engine. `check_plain()` and `check_grid()` return ACCEPT or REJECT, every failed rule, and a fix for each. `propose_grid()` wraps `desk/gridplan.grid_for_signal`, snaps prices to tick, enforces the 3x floor, pulls the stop side edge in until the worst case fits, and re-checks the result. Also includes `max_range_edge()`, `max_grid_leverage()`, `max_plain_leverage()`, `infer_deploy_ratio()`, `implied_mmr()`, `parse_guard_command()` and `format_verdict()`. |
| `guard/ledger.py` | Daily P&L on the Sydney day boundary, the issued trade registry, the 1R lock after a stop out, and the unissued (revenge) tagger. Stored in the existing `app_state` key/value table through `triggers.db.get_state/set_state`, so it works on SQLite locally and on Supabase. **No new tables.** |
| `watcher.py` | Poll loop with alerts and summaries at 07:00, 15:30 and 21:30 Sydney. Has a dry run mode that uses a fixture. |
| `guard/fixtures/dood_live.json` | Dry run fixture: your live DOOD grid plus an example HYPE short. |
| `.github/workflows/watcher.yml` | Manual dispatch only. It defaults to `runs-on: self-hosted`. |
| `tests/test_guard.py`, `tests/test_bybit_account.py`, `tests/test_watcher.py` | 41 offline tests (HTTP is mocked). All pass: `python -m pytest tests/test_guard.py tests/test_bybit_account.py tests/test_watcher.py -q`. |

### Rules enforced by preflight
- Margin must be at least $50.
- A stop must exist and be on the correct side. **A grid SL must be beyond the range edge** (short: SL >= top; long: SL <= bottom).
- The loss at the stop must be at most 25% of margin. For grids this is the fully filled worst case: every cell between launch and the stop is filled, then the stop hits, plus a 0.06% taker close. After a stop out (or an unissued trade), the ledger also applies a 1R ($12.50) cap.
- Liquidation must be at least 2x as far from entry as the stop. For grids this uses the liq price of the **fully filled** position.
- Grid leverage must be at least 3x.
- Open risk plus this trade's stop loss must be at most $125.
- Daily realised loss: once $125 is hit the guard is shut, and a new stop may not push the day past $125.

### Grid model (worth knowing)
- Arithmetic grid with N cells. For a short, cells below the launch price open at launch, and cells above fill at their sell line as price rises. A long mirrors this.
- Quantity per cell = `deploy_ratio x investment x leverage / sum(fill prices)`. `deploy_ratio=1` is conservative. For a live bot, `infer_deploy_ratio()` calibrates it from the bot's position at the current mark, because a grid's position depends only on price, to within one cell.
- Maintenance **rate**: `implied_mmr()` back-solves it from the app's own liq price. **The "MMR 14.05%" Bybit shows on the bot card is the maintenance margin RATIO (MM / equity), not the rate.** Plugging 14.05% in as a rate gives liq 0.0029366 instead of the app's 0.0031673. The implied rate that reproduces the app's figure is 5.74%.

## How to run

```bash
# offline, no keys, prints alerts and a summary from the fixture
python watcher.py --once --dry-run --summary
python watcher.py --once --fixture my_snapshot.json

# live (NON US host only), read only key
export BYBIT_API_KEY=... BYBIT_API_SECRET=...          # Bybit key with "Read-Only" ticked, no trade/withdraw
export BYBIT_BASE_URL=https://api.bybit.com            # or https://api.bytick.com
export BYBIT_GRID_BOT_IDS=123456789                    # comma separated futures grid bot ids (see note)
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
export SUPABASE_URL=... SUPABASE_KEY=...               # optional; SQLite otherwise
python watcher.py --once
python watcher.py --loop --interval 60
python watcher.py --loop --interval 60 --max-minutes 340
```

Exit code 2 means a geoblock or missing keys. The live loop also sends that to Telegram.

**Grid bot ids (registry).** Bybit's futures grid API has only validate, create, close and detail endpoints. There is **no list endpoint** (confirmed by research, docs/night/research_tools.md). The watcher therefore reads a registry: the ledger key `guard:grid_bots` (add or remove with `/addbot <id> [SYMBOL]` and `/rmbot <id>`, patch below), merged with env `BYBIT_GRID_BOT_IDS`. The Bot ID is on the bot details page in the app. Detail is `POST /v5/fgridbot/detail {"bot_id"}` and returns `detail.{min_price,max_price,cell_number,leverage,total_investment,current_position,entry_price,mark_price,liquidation_price,stop_loss_price,m_m_rate,tick_size,status,grid_mode,unrealised_pnl,...}`.

**Grid owned positions.** It's unknown whether a grid bot's position appears in `/v5/position/list`. Either way:
- If the bot detail was read, any linear position on that symbol is skipped, because the bot entry covers it.
- If the bot is registered with a symbol but detail failed, the linear position is kept as `kind="grid_position"`. Its liq and no stop alerts still run, but it is **never revenge tagged**.

**Read only key permissions.** It's also unknown whether a Read-Only key may call `fgridbot/detail`. Per bot failures are collected in `client.grid_errors` and not raised: retCodes 10003, 10004, 10005, 10007 and 10010, plus HTTP 401, are classed as `permission`. The watcher sends one Telegram alert per bot with a hint to enable bot read permission (still Read-Only). A geoblock 403 still stops the run.

**Portable poll.** `load_snapshot()` is the only I/O step. `normalise`, `metrics`, `evaluate` and `poll(snap, ledger, state_get, state_set, send, regime, now)` are pure functions over the fetched JSON (`{wallet, positions, grids, grid_errors, closed_pnl}`) plus injected callables. The logic can be ported 1:1 to a Supabase Edge Function (TypeScript) that fetches the same four payloads and uses the same `app_state` keys.

### Hosting (free, non US)
GitHub hosted runners are in the US and get a 403 from Bybit. That's why `watcher.yml` has no schedule and defaults to `self-hosted`.

The lead's runner plan, in order:
1. **Supabase Edge Function in the Sydney region (ap-southeast-2), triggered by pg_cron every minute.** This needs a TypeScript port of `poll()` (see "Portable poll"). The state keys are already in `app_state`. Secrets: `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `TELEGRAM_*`. Not built tonight.
2. **Oracle Cloud Always Free VM in Sydney.** Run `python watcher.py --loop --interval 60` under systemd.
3. The Mac options below (self hosted runner or launchd). These only work while the Mac is awake.

Avoid Singapore regions: Bybit restricts Singapore.

**Option A: your Mac as a GitHub self hosted runner.** The Mac is in Sydney, so Bybit allows it. This costs nothing.
1. Repo, Settings, Actions, Runners, New self hosted runner, macOS. Run the shown `config.sh` in `~/actions-runner`.
2. Add repo secrets: `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_BASE_URL`, `BYBIT_GRID_BOT_IDS` (the Supabase and Telegram secrets already exist).
3. Keep the runner alive with launchd. Save this as `~/Library/LaunchAgents/com.manus.actions-runner.plist`, then run `launchctl load -w` on it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.manus.actions-runner</string>
  <key>ProgramArguments</key><array><string>/Users/USERNAME/actions-runner/run.sh</string></array>
  <key>WorkingDirectory</key><string>/Users/USERNAME/actions-runner</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/USERNAME/actions-runner/launchd.log</string>
  <key>StandardErrorPath</key><string>/Users/USERNAME/actions-runner/launchd.err</string>
</dict></plist>
```

4. Start it from Actions, Watcher, Run workflow (runner `self-hosted`). To make it recurring, add `schedule: - cron: "3 */6 * * *"` to `watcher.yml` *only* while `runs-on` is self-hosted.

**Option B: skip GitHub and run the watcher directly under launchd on the Mac.** This has the fewest moving parts:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.manus.guard-watcher</string>
  <key>ProgramArguments</key><array>
    <string>/Users/USERNAME/quant-crypto-system/.venv/bin/python</string>
    <string>watcher.py</string><string>--loop</string><string>--interval</string><string>60</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/USERNAME/quant-crypto-system</string>
  <key>EnvironmentVariables</key><dict>
    <key>BYBIT_BASE_URL</key><string>https://api.bybit.com</string>
    <key>BYBIT_GRID_BOT_IDS</key><string>BOT_ID_HERE</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/guard-watcher.log</string>
  <key>StandardErrorPath</key><string>/tmp/guard-watcher.err</string>
</dict></plist>
```

Keep the keys in the repo's `.env`, which `config.py` already loads with dotenv. Don't put them in the plist. With the laptop asleep there are no alerts. For 24/7 coverage, use option 1 or 2 above.

## Integration patch (for the lead to apply)

### 1. `utils/tg_commands.py`: add a `/guard` command

Add to `_HELP`:
```
"/guard short DOODUSDT grid 0.0016 0.0025 200 5x 263.86 [sl X] [@entry] — check a setup\n"
"/guard long BTCUSDT 65000 63000 10x 50 — entry stop lev margin\n"
```

Add this function:
```python
def _guard(arg: str) -> str:
    from guard import preflight as pf
    from guard.ledger import Ledger
    from utils import exchange
    try:
        g = pf.parse_guard_command(arg)
    except (ValueError, IndexError) as exc:
        return f"Usage: /guard short DOODUSDT grid LO HI GRIDS 5x INVEST [sl X] [@ENTRY]\n({exc})"
    led = Ledger()
    day = led.day()
    ctx = dict(daily_realised_pnl=day["realised"], max_loss_usd=led.max_loss_for_next())
    try:
        from triggers.outcomes import portfolio_heat
        ctx["open_risk_usd"] = portfolio_heat()["open_risk"]
    except Exception:                                   # noqa: BLE001
        pass
    if g["type"] == "grid":
        entry = g["entry"]
        if entry is None:
            sym = g["symbol"].replace("USDT", "") + "-USD"
            entry = exchange.get_last_prices([sym]).get(sym)
        if not entry:
            return "No live price; add @ENTRY, e.g. @0.0021"
        v = pf.check_grid(g["direction"], g["lo"], g["hi"], g["grids"], g["leverage"],
                          g["investment"], g["stop"], entry, **ctx)
    else:
        v = pf.check_plain(g["direction"], g["entry"], g["stop"], g["leverage"], g["margin"], **ctx)
    txt = pf.format_verdict(v, g["symbol"])
    if ctx.get("max_loss_usd"):
        txt += f"\n🔒 1R lock active (after a stop out): this setup may lose at most ${ctx['max_loss_usd']:.2f}."
    return txt
```

And in `handle()`:
```python
    if cmd == "/guard":
        return _guard(arg)
```

Bot registry commands (Bybit has no grid list endpoint):
```python
    if cmd == "/addbot":
        from guard.ledger import Ledger
        parts = arg.split()
        if not parts:
            return "Usage: /addbot <bot_id> [SYMBOL]  (Bot ID is on the bot details page)"
        Ledger().add_grid_bot(parts[0], parts[1] if len(parts) > 1 else None)
        return f"🤖 Watching grid bot {parts[0]}."
    if cmd == "/rmbot":
        from guard.ledger import Ledger
        return "Removed." if Ledger().remove_grid_bot(arg.strip()) else "Not registered."
    if cmd == "/bots":
        from guard.ledger import Ledger
        b = Ledger().grid_bots()
        return "\n".join(f"• {k} {v.get('symbol') or ''}" for k, v in b.items()) or "No grid bots registered."
```
Add `/addbot`, `/rmbot` and `/bots` to `_HELP`. Register the symbol too (`/addbot 123 DOOD`), so a grid owned position is recognised even if the detail call is refused.

Optional, `/issued`: register a plan the guard accepted so the watcher doesn't tag it as revenge. Use `Ledger().issue({...parsed /guard dict, "type": ..., "mode"/"direction": ...})`. Simplest wiring: `/guard ... issue` re-runs the check and calls `led.issue(g | {"mode": g["direction"]})` only if `v.ok`.

### 2. `monitor.py`: register every alert the monitor fires as "issued"

At the fire site in `poll_once()`, right after `tdb.mark_fired(t["id"], ind["price"], note=reason)`:
```python
                try:
                    from guard.ledger import Ledger
                    Ledger().issue({"symbol": t["symbol"], "type": "plain",
                                    "direction": t.get("direction") or "long",
                                    "entry": ind["price"], "stop": t.get("stop"),
                                    "margin": POSITION_MARGIN_USD, "trigger_id": t["id"]})
                except Exception as exc:                  # noqa: BLE001
                    log.debug("guard issue failed: %s", exc)
```
(Import `POSITION_MARGIN_USD` from config.) If the alert also shows the grid version, also issue `{"type": "grid", "mode": ..., "lo", "hi", "grids", "investment"}` from `_grid_block`'s `g`. That's easiest if `_grid_block` returns `g` alongside the text.

In `_sizing_line` / `_grid_block`, honour the 1R lock: `risk = min(risk, Ledger().max_loss_for_next() or risk)`, and when `Ledger().day()["cap_hit"]` is true, replace the sizing with "🛑 Daily loss cap hit, guard shut until midnight Sydney".

Optionally run the watcher inside the monitor's loop when it's on a non US host: call `watcher.poll(...)` once per monitor poll, guarded by `os.getenv("BYBIT_API_KEY")`, and catch `BybitGeoBlocked` so a US runner keeps working without it.

### 3. `config.py` (optional)
```python
WATCH_LIQ_MIN_PCT = 15.0
WATCH_EDGE_WARN_PCT = 10.0
GUARD_SUMMARY_TIMES = ("07:00", "15:30", "21:30")   # Australia/Sydney
```
Right now these are constants in `watcher.py`. Point them at config if you add the settings.

Note: `GRID_MMR = 0.005` (0.5%) in config is far below what Bybit applies to small caps like DOOD. Its liq implies a 5.74% rate. For a preflight on a new small cap grid without a live liq, pass `mmr=0.05` or more (or add `GUARD_SMALLCAP_MMR = 0.05` to config). The `/guard` patch above uses the config default. Consider passing `mmr=0.05` for anything outside the top 50.

## Worked example: your live DOOD grid

Input (from the app): short 5x isolated, 200 arithmetic grids, range 0.0016 to 0.0025, investment 263.8642 USDT, entry 0.002096, position -210560 DOOD, liq 0.0031673, mark 0.0020221, "MMR 14.05%", **no SL**.

Calibration:
- Cells held at mark 0.0020221: 93 → 2,264.09 DOOD per cell. The naive model assumes the full investment x 5 is deployed; Bybit actually deploys 75.09% of that (deploy_ratio 0.7509).
- Implied maintenance rate from the app's liq: **5.74%** (the 14.05% is the margin ratio, not the rate).
- Right now: uPnL +$15.56, liq 56.63% above mark, range top 23.63% above, bottom 20.87% below.

`check_grid(short, 0.0016, 0.0025, 200, 5x, 263.8642, stop=None, entry=0.002096, deploy_ratio=0.7509, mmr=0.0574, tick=0.0000001)`

```
⛔ REJECT DOODUSDT
Loss at stop $147.76 (56.0% of margin, cap $65.97)
Liq 25.0% away vs stop 19.87% = 1.26x (need 2x)
• no_stop: grid has no stop loss → set SL >= range top, e.g. 0.0025125
• loss_cap: $147.76 = 56.0% of $263.86 (> 25% = $65.97) → range top 0.0022407 with SL 0.002252 (loss $65.95); or leverage cannot fix it (max 2x < 3x)
• liq_distance: fully filled liq 0.00261998 is 25.0% away vs stop 19.9% (need >= 2x) → max leverage 3x at this range, or tighten the range edge
• open_risk_cap: open risk $0.00 + $147.76 > $125 → this stop may lose at most $125.00
• daily_loss_room: realised $0.00 + stop $147.76 > $125 → this stop may lose at most $125.00 today
```

What this says:
1. **No stop.** Bybit will only take an SL at or above 0.0025, so the nearest legal stop is about 0.0025125 (0.5% past the top).
2. **The range is too wide for the 25% rule.** If DOOD rallies to the top, the short fills all 200 cells: about 452,817 DOOD at an average of 0.0021877, effective leverage 3.75x. Stopping just past the top then costs about **$147.76 (56% of margin)**. That's over the $65.97 cap, and on its own it exceeds the $125 open risk and daily caps.
3. **Liquidation of the fully loaded grid** sits about 0.00262. That's above the range top but only 1.26x the stop distance. The app's 0.0031673 is the liq for *today's* 210,560 DOOD position. It moves down as the grid adds shorts on the way up.
4. Adding an SL at 0.0025125 to the existing bot doesn't fix it (still REJECT: loss_cap and liq_distance). The range can't be edited on a Bybit futures grid, so the fix is **close and relaunch**.

Compliant relaunch options (same 200 grids, same $263.86, bottom 0.0016, launched at the current mark 0.0020221). Each passes every rule:

| Leverage | Range top | SL (just past top) | Worst case loss | Fully filled liq | Liq / stop distance |
|---|---|---|---|---|---|
| 5x | 0.0021639 | 0.0021748 | $65.94 (24.99%) | 0.00244345 | 2.76x |
| 4x | 0.0022097 | 0.0022208 | $65.94 | 0.00258599 | 2.84x |
| 3x | 0.0022933 | 0.0023048 | $65.96 | 0.00283460 | 2.87x |

Read: the more leverage, the tighter the range top has to be. **3x gives the most room above (top 0.0022933, about 13.4% above mark) for the same worst case.** All three use your full 25% of a $263.86 margin ($65.97), which is 5.3R in sleeve terms. If you want the $50 margin standard instead, `propose_grid("short", 0.0020221, atr, investment=50, ...)` sizes it to $12.50.

The engine's own proposal (`propose_grid`, ATR 0.00012, investment 263.86, tick 1e-7, mmr 5.74%): short 3x, 0.0016621 to 0.0022039, 10 grids, SL 0.0022328, worst case $65.95, liq/stop 2.74x → ACCEPT. That uses gridplan's ATR spaced rungs (10 grids instead of 200).

## Unfinished / caveats
- Bybit has no futures grid list endpoint, so bot ids must be registered (`/addbot` or `BYBIT_GRID_BOT_IDS`). The docs index fetch was blocked for me. The detail endpoint was confirmed from its own docs page.
- Two things are unverified until the first live run: whether a Read-Only key may call fgridbot/detail (handled gracefully with an alert), and whether grid positions show in position/list (handled both ways).
- The Supabase Edge Function port is not built. The Python poll is structured for it.
- The grid model ignores funding and grid profits already banked (`realised_pnl` / grid profit). Banked profit makes the real worst case slightly better.
- Revenge tagging: when the watcher sees an unissued item, it arms the 1R lock (by your design, no cooldown). P&L for symbols tagged unissued in the last 2 days is booked to `realised_unissued`.
- Closed P&L: one page of up to 100 rows, from the Sydney midnight start. Enough for one day at this sleeve size.
- Nothing has been run against the live API (Bybit returns 403 from this sandbox). The signing is tested against the documented V5 formula.
