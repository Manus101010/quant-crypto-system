# Signal features (night build, 2026-10-27)

Owner: SIGNAL FEATURES agent. New package `features/`, tests `tests/test_features.py`,
research `research/features_eval.py`. No existing file was edited; the integration
patch is at the end of this document for the lead to apply.

Purpose: attach positioning / flow / hype readings to every signal as **logged
features**, so the paper ledger can later tell us whether any of them adds edge.
Nothing here gates or issues a trade.

## 1. What each source gives

| Module | Source | Key | Works from US host (GitHub runner, sandbox)? | Fields |
|---|---|---|---|---|
| `features/coinalyze.py` | Coinalyze API v1 (PRIMARY when key set) | `COINALYZE_API_KEY` (free) | Yes (401 without key, so reachable). **Not live-tested: no key in env tonight** | funding (current, 7d/30d percentile, 7d avg), predicted funding, OI USD + 1h/4h/24h change (native units), OI aggregate Bybit+Binance, liquidations long/short 1h/24h + skew, L/S ratio + 4d pct + 24h chg, taker buy/sell 1h/24h (from `bv`) on the **Bybit market** |
| `features/derivs.py` | OKX public v5, then MEXC contract, then Bybit public v5 | none | OKX yes, MEXC yes, Bybit **403** (host remembered blocked 1h) | same canonical fields: `funding_rate, funding_8h, funding_interval_h, funding_pct_7d, funding_pct_30d, funding_avg_7d_8h, oi_usd, oi_chg_1h/4h/24h, ls_ratio, ls_pct_4d, ls_chg_24h, taker_ratio_1h/24h` |
| `features/hyperliquid.py` | Hyperliquid `POST /info metaAndAssetCtxs` | none | Yes | `hl_funding_8h` (hourly x8), `hl_oi_usd`, `hl_premium`, `hl_vol_24h` (one call covers all coins, cached 2 min) |
| `features/dex.py` | DEX Screener | none | Yes | `dex_pairs, dex_liq_usd, dex_vol_h1/h6/h24, dex_vol_exp_1h/6h` (vs 24h pace), buys/sells h1, `dex_buy_ratio_h1/h6/h24`, price change, `dex_age_days`, `dex_boosted`; plus `latest_boosts()` / `latest_profiles()` for a hype watch list |
| `features/coinglass.py` | CoinGlass v4 | `COINGLASS_API_KEY` ($29 Hobbyist) | Yes (401 without key) | `cg_funding_oiw(+pct)`, `cg_oi_usd`, `cg_oi_chg_4h/24h`, `cg_liq_long/short_24h`, `cg_liq_skew`, `cg_ls_ratio(+pct)`, `cg_taker_ratio_24h`. Uses 4h interval (Hobbyist minimum), 28 req/min limiter, 30 min cache |
| `features/whales.py` | Whale Alert | `WHALE_ALERT_API_KEY` | REST yes | `whale_to_exch_usd, whale_from_exch_usd, whale_netflow_usd, whale_n` |
| `features/snapshot.py` | merges all of the above | | | flat dict + flags + `alert_line()` |

Endpoint paths verified tonight:

* OKX: `/api/v5/public/funding-rate`, `/public/funding-rate-history` (limit 100, history only ~3 months), `/rubik/stat/contracts/open-interest-history` (per instId; rows `[ts, oi_contracts, oi_coin, oi_usd]`), `/rubik/stat/contracts/long-short-account-ratio-contract`, `/rubik/stat/taker-volume-contract` (rows `[ts, sell, buy]`). The per-ccy endpoints named in the brief (`open-interest-volume`, `long-short-account-ratio`, `taker-volume`) also work but aggregate all contract types; the per-instId ones match the USDT perp. All rubik calls return max 100 rows per call.
* CoinGlass v4 (from docs.coinglass.com reference pages via curl): `/api/futures/funding-rate/oi-weight-history`, `/api/futures/open-interest/aggregated-history`, `/api/futures/liquidation/aggregated-history`, `/api/futures/global-long-short-account-ratio/history`, `/api/futures/aggregated-taker-buy-sell-volume/history`. CoinGlass funding values are in percent units; the client divides by 100. (WebFetch of docs.coinglass.com was blocked by the permission prompt; content was read with curl instead.)
* Coinalyze (OpenAPI spec embedded in api.coinalyze.net/v1/doc): `/future-markets`, `/funding-rate`, `/predicted-funding-rate`, `/funding-rate-history`, `/open-interest-history`, `/liquidation-history`, `/long-short-ratio-history`, `/ohlcv-history`; `from`/`to` in UNIX seconds, history ascending, 40 calls/min, intraday keeps 1,500-2,000 points. The spec does not state whether funding is percent or fraction, so `coinalyze.funding_scale()` detects it from the median magnitude (tested both ways). Bybit market symbols are resolved at runtime from `/future-markets` (exchange "Bybit", `symbol_on_exchange` = `<BASE>USDT`), so no exchange code is hardcoded.
* Whale Alert (developer.whale-alert.io via curl; WebFetch blocked): the old `api.whale-alert.io/v1/transactions` now returns 404. REST lives at `https://leviathan.whale-alert.io/{chain}/transactions?start_height=&symbol=` with `?api_key=`, and needs the **Enterprise plan ($699/mo)**. The $14.95 Alerts plan has **no API**; the $29.95 developer Alerts API is a **WebSocket stream** (min $100k per alert, 100 alerts/h), not a query. `whales.get()` implements the Enterprise REST path; `whales.summarise_alerts()` takes the WebSocket/archive alert schema so a listener or the free archive (`whale-alerts-archive.json.gzip`, 40 MB, ~635 MB JSON) can feed the same features. Recommendation: stay optional, do not buy until the free archive shows an edge.

Rate limits respected: per-host spacing limiter (OKX rubik 4 per 2 s, OKX public 8 per 2 s, MEXC 10 per 2 s, DEX search 250/min, DEX boosts 50/min, CoinGlass 28/min, Coinalyze 38/min). Caches: derivs/dex/coinalyze 5 min, CoinGlass 30 min, Hyperliquid 2 min, instrument lists 6-24 h.

### Source priority in `snapshot()`

Positioning fields come from Coinalyze (Bybit market) when `COINALYZE_API_KEY` is set; any field it leaves None is filled from OKX, then MEXC, then Bybit public. `pos_src` records which source supplied funding. When Coinalyze is primary, OKX readings are kept as `okx_funding_8h`, `okx_oi_chg_24h`, `okx_ls_ratio` for cross-venue comparison. Hyperliquid, DEX, CoinGlass and Whale Alert fields are added alongside. All sources run in parallel threads under a 6 s budget; a timed-out or failed source leaves its fields None. `snapshot()` never raises (tested with a crashing and a hanging source).

### Derived flags (1.0 / 0.0 / None)

| Flag | Rule |
|---|---|
| `crowded_longs` | funding pct 7d > 90 AND L/S pct 4d > 90 AND funding_8h > 0.0105% (strictly above the +0.01% clamp) |
| `crowded_shorts` | funding pct 7d < 10 AND L/S pct 4d < 10 AND funding < 0 |
| `oi_spike` | OI +5% in 1h, or +10% in 4h, or +25% in 24h (coin units) |
| `dex_hype` | DEX 1h volume >= 3x its 24h pace with >= 55% buy txns and >= $100k 24h volume, or token paid-boosted |
| `squeeze_risk` | funding < 0 and pct 7d <= 20 with OI 24h >= +5%, or crowded_shorts |
| `flush_risk` | crowded_longs with OI 24h >= +5% |

The clamp condition matters. Live tonight, BTC funding is p91 and SOL p96 over 7 days while sitting exactly at the +0.01%/8h default, because funding has been at or below the clamp all week. Without the clamp rule both would read "crowded" on L/S alone.

Funding units: everything is a fraction per interval (`0.0001` = 0.01%). `funding_8h` normalises 1h/4h funding coins to an 8h equivalent (WIF and ORDI are on 4h at OKX tonight).

## 2. Live sample output (2026-10-27 ~04:30 AEDT, no paid keys, so pos_src = okx)

Snapshot latency: 2.0 to 2.6 s cold, 0 ms cached (5 calls to OKX, 1 to MEXC/OKX ticker for the DEX price check, 1-3 to DEX Screener, 1 to Hyperliquid).

**BTC-USD**
```
funding_8h 0.0001 (8h) pct7d 90.9 pct30d 96.2 | oi_usd 2.53B oi_chg 1h -0.57% 4h -0.60% 24h +4.69%
ls_ratio 2.07 pct4d 45.5 | taker 1h 0.99 24h 0.97 | HL funding_8h 0.0001 oi 3.39B premium -0.04%
dex: 17 matching pairs (wrapped BTC), vol24 $563k, exp1h 2.8x, buy ratio 0.41 | flags all 0
Pos: fund +0.010% (p91) · OI 24h +4.7% · L/S 2.07 (p46) · taker 0.97 · DEX vol 2.8x
```

**SOL-USD**
```
funding_8h 0.0001 pct7d 95.5 | oi_usd 315M oi_chg 24h +2.43% | ls 2.92 pct4d 60.5 | taker 24h 1.00
HL oi 561M | dex 19 pairs, vol24 $16.1M, exp1h 1.26x, buy 0.50 | flags all 0
Pos: fund +0.010% (p96) · OI 24h +2.4% · L/S 2.92 (p60) · taker 1.00 · DEX vol 1.3x
```

**WIF-USD (small cap)**
```
funding 0.0000174 per 4h -> funding_8h 0.000035 pct7d 46.5 | oi_usd 3.75M oi_chg 24h -1.18%
ls 2.15 pct4d 54.5 | taker 1h 0.48 (sellers) 24h 0.89 | HL oi 4.70M
dex: 2 price-matched pairs (Solana WIF pairs filtered out by the search ranking; only $191 24h vol matched) | flags all 0
Pos: fund +0.004% (p46) · OI 24h -1.2% · L/S 2.15 (p54) · taker 0.89
```

**1000PEPE-USD (multiplier mapping)**
```
maps to OKX PEPE-USDT-SWAP, HL kPEPE, DEX PEPE at the 1-PEPE price
funding_8h 0.0001 pct7d 70.5 | oi_usd 32.4M oi_chg 4h +1.91% 24h +1.13% | ls 3.01 pct4d 72.5
dex 9 pairs, vol24 $1.99M, exp1h 1.2x, buy 0.42 | flags all 0
Pos: fund +0.010% (p70) · OI 24h +1.1% · L/S 3.01 (p72) · taker 0.96 · DEX vol 1.2x
```

Known DEX limitation: `/latest/dex/search` returns at most 30 pairs ranked by DEX Screener, so for majors and older memes the real main pool (e.g. WIF on Raydium) may not be in the 30 and only thin bridged pairs match. The price check stops impostors but cannot add missing pools. DEX features are most useful for newer small caps where the token's own pools dominate the search. A follow-up could map the coin's canonical token address once (`/token-pairs/v1/{chain}/{address}` works, tested on WIF) and store it in a small JSON map.

## 3. Evaluation

### 3.1 Ledger join (forward test)

`python research/features_eval.py ledger` joins `triggers.features_json` (the snapshot stored at fire time, see patch) with `triggers.r_multiple` from triggers/outcomes.py and prints expectancy R, PF and n per bucket for each flag (0/1) and terciles of funding pct, funding_8h, OI change, L/S pct, taker ratio and DEX expansion. A missing feature gets its own row. Tonight: **no snapshots exist yet** (the column does not exist until the patch lands), so the ledger mode has nothing to evaluate. It needs a few dozen closed signals before any bucket is readable.

### 3.2 Historical backtest (OKX + MEXC history)

BACKTEST_PLACEHOLDER

## 4. Integration patch (for the lead)

Three small edits. All wrapped so a feature failure can never block an alert.

### 4.1 Schema: one new column

`triggers/db.py`, add to `_OUTCOME_COLS` (it is ALTER-migrated on connect):
```python
                 ("taken", "INTEGER"),
                 ("features_json", "TEXT")]   # features.snapshot at fire time
```
Supabase:
```sql
alter table triggers add column if not exists features_json text;
```
`set_outcome()` filters by `_OUTCOME_COLS`, so `tdb.set_outcome(id, {"features_json": ...})` then works on both stores with no other change.

### 4.2 Take the snapshot when the signal FIRES (monitor.py)

Fire time is the right moment: it is the entry the paper trade is measured from (arm time can be hours earlier). In `monitor.py` `poll_once()`, inside `if verdict == "fire":` before `_alert_text`:

```python
        if verdict == "fire":
            snap = None
            try:
                from features.snapshot import snapshot, alert_line, to_json
                snap = snapshot(t["symbol"], t.get("direction"), budget=5.0)
            except Exception as exc:                   # noqa: BLE001 — features never block alerts
                log.debug("features snapshot failed: %s", exc)
            text = _alert_text(t, ind["price"], reason)
            if snap:
                line = alert_line(snap)
                if line:
                    text += f"\n<code>{line}</code>"
            delivered = telegram.send_message(text)
            if delivered or not telegram.is_configured():
                tdb.mark_fired(t["id"], ind["price"], note=reason)
                if snap:
                    try:
                        tdb.set_outcome(t["id"], {"features_json": to_json(snap)})
                    except Exception as exc:           # noqa: BLE001
                        log.debug("features store failed: %s", exc)
                ...
```

Cost: one snapshot per fired signal (max ~5 per scan), ~2-3 s each cold. Inside the 15 min relay that is negligible.

### 4.3 Optional: also snapshot at ARM time (triggers/scan.py)

To study arm-to-fire drift, add `features_json=to_json(snapshot(r["ticker"], direction))` to the `tdb.add_trigger(...)` call at `triggers/scan.py` ~line 462. That needs `features_json` added as a keyword to `add_trigger` in both `triggers/db.py` and `triggers/supastore.py` (and to `_COLS`). Fire time alone is enough for the evaluation, so this is optional; if done, use a different column (`features_arm_json`) so the fire snapshot is not overwritten.

### 4.4 Telegram line

`alert_line(snap)` gives one compact line, empty when nothing is known, e.g.
```
Pos: fund +0.010% (p96) · OI 24h +2.4% · L/S 2.92 (p60) · taker 1.00 · DEX vol 1.3x
Pos: fund +0.060% (p97) · OI 24h +12.3% · L/S 3.10 (p96) · taker 1.10  ⚠ crowded longs, flush risk
```
Liquidations (`liq 24h L $xM / S $yM`) and whale netflow appear when Coinalyze / Whale Alert keys are set.

### 4.5 Env / workflow

Add to `.github/workflows/monitor.yml` env (all optional): `COINALYZE_API_KEY`, `COINGLASS_API_KEY`, `WHALE_ALERT_API_KEY`. Without any key the snapshot runs on OKX + MEXC + Hyperliquid + DEX Screener, all of which answered 200 from this US sandbox tonight. No new requirements (uses `requests`, already pinned).

## 5. Tests

`python -m pytest tests/test_features.py -q` : TESTS_PLACEHOLDER. All HTTP is mocked through a fake session (no network). Covered: symbol/multiplier mapping, percentile, geo-block memory (Bybit 403 not retried), never-raise on connection errors, OKX full path, 4h funding normalisation, MEXC fallback, Bybit path, total outage, caching, Coinalyze market resolution + features in both funding unit conventions, CoinGlass with/without key (header and 4h interval asserted), DEX impostor filtering / hype / boost / liquidity floor / outage, Whale Alert disabled, alert and Enterprise schemas, Hyperliquid incl. kPEPE, flag rules incl. the clamp case, snapshot merge with Coinalyze primary, snapshot timeout and crash isolation, alert line, ledger join, no-lookahead in historical features, backtest filter maths.

## 6. Unfinished / caveats

* Coinalyze not live-tested (no key). Funding units auto-detected; if Coinalyze sends funding per Bybit interval for 1h/4h coins, `funding_8h` from Coinalyze will understate those coins (documented in code; `funding_interval_h` stays None when Coinalyze is primary).
* Whale Alert: no affordable query API. Optional module kept; free archive backtest not run tonight.
* DEX search caps at 30 pairs (see section 2).
* Bybit public works only from a non-US host; code tries it last and remembers the 403 for an hour. If the Supabase Sydney bridge from research_tools.md lands, Bybit public could become the primary free source.
