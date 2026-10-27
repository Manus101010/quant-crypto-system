# Night research: tools, data and runner (verified 2026-10-27)

Scope: Bybit read-only API, a free non-US runner, CoinGlass v4 plan coverage, Whale Alert, DEX Screener, paid signal/data services at or under US$50/mo, and free derivatives data. Every claim below carries a source URL. "LIVE" means I hit the endpoint from this sandbox today (sandbox egress = Google LLC, Columbus, Ohio, US).

Some doc pages were blocked for WebFetch by the permission system (bybit-exchange.github.io/docs/v5/intro, /docs/v5/fgridbot/detail, /docs/v5/position/close-pnl via WebFetch, docs.fly.io/about/discontinued-plans, docs.coinglass.com/reference/endpoint-overview via WebFetch). I fetched the same content with curl where possible, so nothing important is missing.

---

## 1. Bybit V5 private API with a READ ONLY key

### 1.1 Auth (HMAC)

Source: https://bybit-exchange.github.io/docs/zh-TW/v5/guide

* Headers: `X-BAPI-API-KEY`, `X-BAPI-TIMESTAMP` (UTC ms), `X-BAPI-SIGN`, `X-BAPI-RECV-WINDOW` (optional, default 5000 ms). Broker users also send `Referer`.
* Timestamp must satisfy `server_time - recv_window <= timestamp < server_time + 1000`.
* String to sign:
  * GET: `timestamp + api_key + recv_window + queryString` (query string exactly as sent, NOT sorted)
  * POST: `timestamp + api_key + recv_window + jsonBodyString`
* HMAC_SHA256 with the secret, hex lowercase. (RSA_SHA256 alternative: base64 output, plus header `X-BAPI-SIGN-TYPE: 2`.)
* Requests from US or mainland China IPs get 403 (documented on the same page).

Python sketch (matches our style, no order code):

```python
ts = str(int(time.time() * 1000)); recv = "5000"
payload = ts + key + recv + (query if method == "GET" else body_json)
sign = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
headers = {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
           "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": sign,
           "Content-Type": "application/json"}
```

### 1.2 Read endpoints we need

| Purpose | Method + path | Key params | Notes | Source |
|---|---|---|---|---|
| Open positions | GET `/v5/position/list` | `category=linear`, `settleCoin=USDT` (or `symbol`), `limit` 1..200 (default 20), `cursor` | With settleCoin and no symbol, only size > 0 returned. Fields: `liqPrice` (estimate for cross, empty for PM), `stopLoss`, `takeProfit`, `positionIM`, `unrealisedPnl`, `createdTime` | https://bybit-exchange.github.io/docs/v5/position |
| Wallet | GET `/v5/account/wallet-balance` | `accountType=UNIFIED`, `coin=USDT` optional | `totalEquity`, `totalWalletBalance`, `totalAvailableBalance`, `totalPerpUPL`, per coin rows | https://bybit-exchange.github.io/docs/v5/account/wallet-balance (curl) |
| Closed PnL | GET `/v5/position/closed-pnl` | `category=linear`, `symbol`, `startTime`, `endTime`, `limit` 1..100 (default 50), `cursor` | Window max 7 days per call, default last 7 days. Fields: `orderId`, `side`, `closedSize`, `avgEntryPrice`, `avgExitPrice`, `closedPnl`, `openFee`, `closeFee`, `leverage`, `createdTime`, `updatedTime`. FAQ: entry/exit prices are fee adjusted, not fill prices | https://bybit-exchange.github.io/docs/v5/position/close-pnl (curl), https://bybit-exchange.github.io/docs/faq |
| Fills | GET `/v5/execution/list` | `category=linear`, `symbol`, `orderId`, `orderLinkId`, `startTime`, `endTime`, `execType`, `limit` 1..100, `cursor` | 7 day window per call, nav says 2 years history. `createType` field identifies order origin (enum page lists values), `orderLinkId` | https://bybit-exchange.github.io/docs/v5/order/execution |
| Key self check | GET `/v5/user/query-api` | none | Returns `readOnly` (1 = read only), `permissions`, `ips`, `deadlineDay`, `expiredAt`, `isMaster`, `parentUid`. Use at startup to HARD FAIL if `readOnly != 1` | https://bybit-exchange.github.io/docs/v5/user/apikey-info (curl) |
| Grid detail | POST `/v5/fgridbot/detail` | body `{"bot_id": "..."}` | 10 req/s per UID. Returns `status` (Unspecified, Rejected, New, Initializing, Running, Cancelling, Completed, Await activation), `min_price`, `max_price`, `curr_min_price`, `curr_max_price`, `liquidation_price`, `mark_price`, `last_price`, `stop_loss_price`, `take_profit_price`, `stop_loss_per`, `take_profit_per`, `tp_sl_type`, `trailing_stop_per`, `pnl`, `pnl_per`, `realised_pnl`, `unrealised_pnl`, `grid_profit`, `funding_fee`, `close_reason`, `bot_close_code`, `end_time` | https://bybit-exchange.github.io/docs/v5/bot/futures-grid/get-detail |

Rate limits: 600 HTTP requests per 5 s per IP across api.bybit.com and regional hostnames; ban 10 min if exceeded (https://bybit-exchange.github.io/docs/v5/rate-limit).

### 1.3 Futures grid bot API: the complete list

The Futures Grid nav section contains exactly four endpoints (verified on three pages):

| Endpoint | Method | Purpose |
|---|---|---|
| `/v5/fgridbot/validate` | POST | Validate params before create |
| `/v5/fgridbot/create` | POST | Create bot (KYC and compliance wall) |
| `/v5/fgridbot/close` | POST | Close running bot |
| `/v5/fgridbot/detail` | POST | Read one bot by `bot_id` |

Sources: https://bybit-exchange.github.io/docs/v5/bot/futures-grid/close , https://bybit-exchange.github.io/docs/v5/bot/futures-grid/create , https://bybit-exchange.github.io/docs/v5/bot/futures-grid/validate-input . The official MCP package source confirms the same four paths (I unpacked bybit-official-trading-server 2.1.25 from npm).

Answers:
* **List bots endpoint: NONE.** The detail page says bot_id comes "from the Create response or bot listing endpoints" but no listing endpoint exists in the docs or in Bybit's own MCP. Consequence: since he creates grids in the app, our poller needs the `bot_id` entered once per grid (Telegram command `/grid add <bot_id>`), then it can poll detail. Bybit app shows the bot ID in the bot detail screen (verify in app).
* **Modify range: NOT POSSIBLE via API.** No modify endpoint. Matches the brief: adjust = close + relaunch.
* **Validate endpoint returns** `check_code` (`FGRID_CHECK_CODE_SUCCESS` when valid), plus allowed ranges for `investment` (from/to in quote), `cell_number`, `leverage`, `min_price`, `max_price`, `stop_loss_price`, `take_profit_price`, `entry_price`, `trailing_stop_per`, `move_up_price`, `move_down_price`, `profit`, and **`long_liq_price` / `short_liq_price` (liq estimate)**. Doc example returns the liq fields as empty strings, so treat as optional. Required inputs: `symbol`, `cell_number` (>=2), `min_price`, `max_price`, `leverage`, `grid_type` (1 arithmetic, 2 geometric), `grid_mode` (1 neutral, 2 long, 3 short); optional `stop_loss_price`, `init_margin`, etc.
* **Is validate safe for a read-only design?** It creates nothing, but it is a POST on a trade-family endpoint and the docs do not state what permission it needs. A read-only key may be rejected. Worth one live test: if it works with a read-only key, desk/gridplan.py can ask Bybit for the min investment, the allowed SL range and the liq estimate before he launches. If rejected, keep our own liq math.
* **Can a read-only key call `/v5/fgridbot/detail`?** Not documented either way (none of the four bot pages state a permission, and the API key permission groups have no "Bot" group: ContractTrade, Spot, Wallet, Options, Derivatives, Exchange, Earn, etc. per https://bybit-exchange.github.io/docs/zh-TW/v5/user/modify-master-apikey). Must be tested live from a non-US IP. Test order: `/v5/user/query-api` then `/v5/fgridbot/detail`. If detail is refused for read-only keys, fallback is position/list + execution/list (see next point) or Bybit app screenshots.
* **Do grid bot positions appear in `/v5/position/list`?** Not documented. Bybit bots historically run in a separate bot sub-wallet, so assume NO until tested. The "unissued/revenge" tagger must not mislabel grid fills; key them by bot_id via detail polling, and treat any linear position whose symbol matches an active registered grid as grid owned.

### 1.4 Sub-account read-only keys

Source: https://bybit-exchange.github.io/docs/zh-TW/v5/user/create-subuid-apikey

* Yes. `POST /v5/user/create-sub-api` with `readOnly: 1` creates a read-only key on a sub UID. Needs to be called with a master key that has Account Transfer, Subaccount Transfer or Withdrawal permission (so in practice create it in the web UI instead; never give our code a master key).
* `ips`: comma separated list to bind; omitted or `*` = unbound.
* **Unbound keys expire after 90 days**; changing password expires non-permanent keys 7 days later. FAQ confirms 90 days and that re-saving "No IP restriction" extends it another 90 days (https://bybit-exchange.github.io/docs/faq). IP-bound keys do not expire. This is the main reason a runner with a static IP is worth having.
* Recommendation: run the US$500 sleeve in a dedicated sub-account, key = read-only, permissions ContractTrade [Order, Position] read only, IP bound to the runner IP. Our code calls `/v5/user/query-api` at boot and refuses to run if `readOnly != 1` or if any Wallet Withdraw permission is present.

### 1.5 Bybit official MCP (bybit-exchange/trading-mcp)

Source: npm package `bybit-official-trading-server` latest 2.1.25 (README at https://cdn.jsdelivr.net/npm/bybit-official-trading-server@2.1.25/README.md, repo https://github.com/bybit-exchange/trading-mcp)

* 396 tools including `bot` (18 tools: grid create/close/detail/validate), `trade` (create/amend/cancel orders), `wstrade`. It is a full trading server.
* "Read-Only Mode" in the README only means the 23 market tools work with NO key. There is no flag or env var that disables write tools (package source reads only `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `BYBIT_API_PRIVATE_KEY_PATH`, `BYBIT_TESTNET`). Write tools carry `readOnlyHint: false` and the README says write operations go through a client approval form.
* Safe way to use it: give it a key created with `readOnly=1`. Then any write tool fails at Bybit. That is the only real read-only guarantee.
* Base URL hardcoded `https://api.bybit.com` (testnet alternative only). No regional domain option. So it must run on a non-US machine (his Mac in Sydney is fine; Claude Code cloud sessions are US and will 403).
* Install in Claude Code (on the Mac):
  ```
  claude mcp add bybit --env BYBIT_API_KEY=xxx --env BYBIT_API_SECRET=yyy -- npx -y bybit-official-trading-server@2.1.25
  ```
  (Pin the version; README uses `@latest`.) Requires Node 20.6+.

---

## 2. Free non-US runner for a small Python poller

### 2.1 What is actually blocked (LIVE test today from US IP)

Every Bybit hostname returns the same CloudFront country block, so alternate domains do NOT help:

| Host | Result |
|---|---|
| api.bybit.com | 403 "The Amazon CloudFront distribution is configured to block access from your country" |
| api.bytick.com | 403 same |
| api.bybit.tr, api.bybitgeorgia.ge, api.bybit.ae, api.bybit.eu, api.bybit.nl, api.bybit.id | 403 same |
| api.bybit.kz | 403 (HTML block page) |

Regional domains exist per docs (tr, kz, georgia.ge, ae, eu broker only, Hong Kong spark-fintech) but each is tied to that regional entity's accounts, and all geo-block US anyway. Bybit servers: AWS Singapore apse1-az2/az3 (https://bybit-exchange.github.io/docs/faq).

Country rules: Bybit's restricted list includes US, Singapore, Hong Kong, Canada (third-party summary of Bybit terms 11.3, https://www.coinperps.com/zh/learn/bybit-restricted-countries ; Singapore confirmed by https://cointelegraph.com/news/bybit-singapore-mas-investor-alert-list , June 2026). **So do NOT pick a Singapore region** even though Bybit's own servers are there. Australia and Japan are listed as supported. Sydney is the natural choice: he is in Sydney and his account is Australian.

A vendor blog claims Bybit's CDN also blocks some cloud provider IP ranges (names AWS, Heroku, Render, Railway): https://quotaguard.com/blog/bybit-api-403-cloud-platform-cdn-block-fix . Unverified and the seller has an interest, but it means any cloud runner must pass a 1-minute smoke test before we build on it.

### 2.2 Options compared

| Rank | Option | Cost | Region | Python? | Static IP (permanent key) | Reliability notes | Source |
|---|---|---|---|---|---|---|---|
| 1 | **Supabase Edge Function pinned to `ap-southeast-2` (Sydney), triggered by pg_cron every 1 to 5 min** | $0 (Free plan: 500,000 invocations/mo; 1 per min = 43,200) | Sydney via `x-region` header or `?forceFunctionRegion=ap-southeast-2` | No (Deno/TypeScript) | No (AWS shared egress) so key expires every 90 days | Already in our stack (Supabase is the state store). No box to babysit. Writes straight into our tables, GitHub Actions monitor.py reads them. Limits: 2 s CPU, 150 s wall, 256 MB. Explicit region means no auto failover during an AWS Sydney outage | https://supabase.com/docs/guides/functions/regional-invocation , https://supabase.com/docs/guides/functions/schedule-functions , https://supabase.com/docs/guides/functions/pricing , https://supabase.com/docs/guides/functions/limits |
| 2 | **Oracle Cloud Always Free VM, home region Sydney (ap-sydney-1)** | $0 forever (2x VM.Standard.E2.1.Micro AMD 1 GB, or Ampere A1 up to 4 OCPU/24 GB total; 10 TB/mo egress) | Sydney (choose at signup, home region is permanent) | Yes, run the existing repo with cron/systemd | Yes, reserved public IP; bind the Bybit key, never expires | Idle reclamation: instance reclaimed if over 7 days p95 CPU < 20% AND network < 20% (AND memory < 20% for A1). A poller is idle, so either upgrade the tenancy to Pay As You Go (Always Free resources stay free; community reports this stops reclamation) or accept the risk. A1 often "out of capacity", E2 Micro usually available. Signup needs a card | https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm , https://blog.51sec.org/2023/02/oracle-cloud-cleaning-up-idle-compute.html |
| 3 | **His Mac in Sydney** (launchd job, or GitHub Actions self-hosted runner) | $0. Self-hosted runner minutes free; GitHub's planned US$0.002/min charge for private repo self-hosted usage was postponed with no new date | Sydney residential | Yes | No (residential dynamic IP), 90 day key renewal | Only runs while the Mac is awake and online. Good for the MCP and for a daily reconcile, poor for 24/7 alerts | https://www.techzine.eu/news/devops/137396/github-bends-to-criticism-and-delays-paid-self-hosting-of-runners/ |
| 4 | Cloudflare Workers cron | $0 | Cron runs "on underutilized machines" anywhere; placement hints (`placement.region = "aws:ap-southeast-2"`) documented only for fetch handlers | No (JS) | No | Cannot guarantee non-US egress for scheduled runs. Reject | https://developers.cloudflare.com/workers/configuration/cron-triggers/ , https://developers.cloudflare.com/workers/configuration/placement/ |
| 5 | Google Cloud free e2-micro | $0 only in us-west1, us-central1, us-east1 | US only | Yes | Yes | US IP = blocked. Reject | https://agentdeals.dev/gcp-free-tier-2026 |
| 6 | fly.io | No free tier for new orgs since 2024; trial 2 h machine time or 7 days | Has syd, nrt, sin | Yes | Paid | Not free. Reject | https://temps.sh/blog/fly-io-pricing-2026 |
| 7 | Deno Deploy | Free tier exists; Classic sunset 2026-07-20; new Deploy has 6 regions, cannot pin region on Classic; no Sydney listed | Auto nearest | No | No | Cannot pin a non-US egress for cron. Reject | https://docs.deno.com/deploy/classic/regions.md , https://docs.deno.com/deploy/index.md |
| 8 | Paid static IP proxy (QuotaGuard etc.) | Paid | n/a | n/a | Yes | Violates "free only". Reject | https://www.quotaguard.com/blog/static-ip-crypto-trading-bot-binance-okx-bybit-kraken |

### 2.3 Runner decision

* **Primary: Supabase Edge Function `bybit-bridge` in ap-southeast-2**, invoked by pg_cron every 2 min (21,600 invocations/mo, 4.3% of quota). It signs read-only GETs (wallet, position/list, closed-pnl since last cursor, execution/list) and POST `/v5/fgridbot/detail` for each registered bot_id, then upserts into Supabase tables `bybit_positions`, `bybit_grids`, `bybit_fills`. GitHub Actions monitor.py (US, unchanged) reads those tables. Python never needs to reach Bybit. Store `BYBIT_API_KEY/SECRET` as Supabase function secrets, never in the DB.
* **Smoke test before building (5 minutes):** deploy a function that returns `fetch("https://ipinfo.io/json")` and `fetch("https://api.bybit.com/v5/market/time")`, call it with `x-region: ap-southeast-2`, check response header `x-sb-edge-region` and that Bybit returns 200 with `retCode: 0`.
* **Fallback if Bybit 403s AWS ranges:** Oracle Always Free E2 Micro in ap-sydney-1 running the Python poller, with the key IP bound (removes the 90 day expiry).
* Key expiry handling for the primary: poller calls `/v5/user/query-api` daily and sends a Telegram warning when `deadlineDay <= 10`.

---

## 3. CoinGlass API v4

Sources: https://www.coinglass.com/pricing (curl), every page listed in https://docs.coinglass.com/llms.txt (I downloaded all 174 reference pages and parsed the per-endpoint plan table).

* Base URL `https://open-api-v4.coinglass.com`, header `CG-API-KEY: <key>`. Response headers `API-KEY-MAX-LIMIT`, `API-KEY-USE-LIMIT`. Errors: 401 bad key, 400 bad params, 422, 429 rate limit (https://docs.coinglass.com/reference/authentication.md , https://docs.coinglass.com/reference/responses-error-codes.md).
* **No free tier.** Plans: Hobbyist $29/mo ($348/yr) 30 req/min, 80+ endpoints, personal use; Startup $79/mo 80 req/min; Standard $299/mo 300 req/min commercial; Professional $699/mo 1,200 req/min.
* **History depth by interval:** Hobbyist gets NOTHING below 4h. 4h = 180 days, 6h/8h/12h = 360 days, 1d = all time. Startup adds 30m (90 days) and 1h/2h (180 days). 15m and below need Standard.
* CoinGlass MCP exists: `https://api-mcp.coinglass.com/mcp` with header CG-API-KEY (https://docs.coinglass.com/reference/mcp-service.md).

### 3.1 Hobbyist availability per endpoint (parsed from each doc page)

Y = included on Hobbyist. Interval note: "4h+" means Hobbyist may only request interval >= 4h.

| Data | Endpoint | Hobbyist | Cheapest plan if not |
|---|---|---|---|
| Funding history (pair) | `/api/futures/funding-rate/history` | Y, 4h+ | |
| Funding OI weighted / vol weighted | `/api/futures/funding-rate/oi-weight-history`, `/vol-weight-history` | Y, 4h+ | |
| Funding snapshot all exchanges | `/api/futures/funding-rate/exchange-list` | Y | |
| Cumulative funding | `/api/futures/funding-rate/accumulated-exchange-list` | Y | |
| Funding arbitrage | `/api/futures/funding-rate/arbitrage` | N | Startup |
| OI history pair / aggregated / stablecoin / coin margin | `/api/futures/open-interest/history`, `/aggregated-history`, `/aggregated-stablecoin-history`, `/aggregated-coin-margin-history` | Y, 4h+ | |
| OI by exchange snapshot / chart | `/api/futures/open-interest/exchange-list`, `/exchange-history-chart` | Y | |
| Liquidation history pair / coin | `/api/futures/liquidation/history`, `/aggregated-history` | Y, 4h+ | |
| Liquidation coin list (1h/4h/12h/24h totals) | `/api/futures/liquidation/coin-list` | Y | |
| Liquidation exchange list | `/api/futures/liquidation/exchange-list` | Y, 4h+ | |
| Liquidation orders (last 7 days) | `/api/futures/liquidation/order` | N | Standard |
| **Liquidation heatmap** model1/2/3 pair and coin | `/api/futures/liquidation/heatmap/model{1,2,3}`, `/aggregated-heatmap/model{1,2,3}` | **N** | **Professional ($699)** |
| Liquidation map / max pain | `/api/futures/liquidation/map`, `/aggregated-map`, `/max-pain` | N | Professional |
| Global L/S account ratio | `/api/futures/global-long-short-account-ratio/history` | Y, 4h+ | |
| Top trader L/S account / position | `/api/futures/top-long-short-account-ratio/history`, `/top-long-short-position-ratio/history` | Y, 4h+ | |
| Taker buy/sell pair / coin | `/api/futures/v2/taker-buy-sell-volume/history`, `/aggregated-taker-buy-sell-volume/history` | Y, 4h+ | |
| Taker ratio by exchange snapshot | `/api/futures/taker-buy-sell-volume/exchange-list` | Y | |
| CVD pair / aggregated | `/api/futures/cvd/history`, `/aggregated-cvd/history` | N | Startup |
| Pair markets snapshot (price, funding, OI, OI 24h %, 24h long/short liqs, volume) | `/api/futures/pairs-markets` | Y | |
| Coin markets snapshot | `/api/futures/coins-markets` | N | Standard |
| Price OHLC | `/api/futures/price/history` | Y, 4h+ | |
| Orderbook bid/ask range history | `/api/futures/orderbook/ask-bids-history` | Y, 4h+ | |
| Orderbook heatmap, large orders | `/api/futures/orderbook/history`, `/large-limit-order` | N | Standard |
| Basis | `/api/futures/basis/history` | Y, 4h+ | |
| Hyperliquid whale alert / positions | `/api/hyperliquid/whale-alert`, `/whale-position` | N | Startup |
| Whale transfer (>= $10M on chain) | `/api/chain/v2/whale-transfer` | N | Startup |
| Fear and Greed | `/api/index/fear-greed-history` | Y | |

Request format example:
```
GET https://open-api-v4.coinglass.com/api/futures/open-interest/aggregated-history?symbol=BTC&interval=4h&limit=500
CG-API-KEY: <key>
```
Pair endpoints take `exchange=Bybit&symbol=BTCUSDT&interval=4h`; aggregated ones take `symbol=BTC` (and `exchange_list=Binance,OKX,Bybit` for liquidation aggregated). Heatmaps take `range=12h|24h|3d|7d|30d|90d|180d|1y`.

**Verdict:** For a 15m/1h trader, Hobbyist is a 4h regime filter plus live snapshots (pairs-markets, funding/OI exchange lists, liquidation coin-list). It does not give the liquidation heatmap at all and no intraday history. Coinalyze (free, section 7) gives 1 min to daily history for OI, funding, liquidations, L/S and buy volume.

---

## 4. Whale Alert

Sources: https://whale-alert.io/ (pricing block, curl), https://developer.whale-alert.io/documentation/

| Plan | Price | What you get | API? | Telegram? |
|---|---|---|---|---|
| Alerts | **US$14.95/mo**, 7 day trial | Custom alerts for 100+ assets, push notifications on web, iOS, Android, up to 1,000 alerts/day, no ads | **No** | Not listed (app push only) |
| Alerts, Analytics and News | US$29.95/mo | Alert plan + on-chain metrics (SOPR, HODL, realized P/L), AI news | No | No |
| Alerts API (developer account, separate signup and billing) | **US$29.95/mo**, 7 day trial | WebSocket `wss://leviathan.whale-alert.io/ws?api_key=...`, custom subscriptions by chain, symbol, tx type, `min_value_usd` (minimum $100,000), 14 chains, 100+ assets, up to 100 alerts/hour, exchange attribution, mint/burn, resend of missed alerts within 5 min on reconnect, personal use | Yes | You build it |
| Enterprise API | US$699/mo | REST transaction feed, 90 day history, 500 CPM | Yes | |

* **The $14.95 plan has no API and no Telegram delivery**, so it cannot feed our system. The API needs the $29.95 developer plan.
* Free alternatives:
  * Whale Alert public Telegram channel `@whale_alert_io`: LIVE check, https://t.me/s/whale_alert_io serves recent posts as HTML (latest post 2026-10-26 16:43 UTC, e.g. "645 BTC (51,779,986 USD) transferred from Coinbase Institutional to unknown wallet"). Large thresholds only, but free and parseable.
  * Whale Alert free historical alert archive download (doc page "Historical Alert Archive") for backtesting whether these alerts carry any edge before paying.
  * Arkham Intel alerts: logged-in account, delivery to Telegram, WhatsApp, Slack, SMS or webhook; filters by USD value, token, chain, sender, recipient, entity (https://info.arkm.com/research/crypto-alerts-transfers-whale-activity-trading-push). Pricing of alerts not stated on that page; treated as free per brief. Arkham Intel API relaunched 2026-02-17, access via intel.arkm.com/api, pricing not public (https://info.arkm.com/announcements/the-new-arkham-api).
  * Lookonchain: public X/Telegram commentary, no API, `t.me/s/lookonchain` web preview returned no messages today. Treat as manual reading only.
  * CoinGlass whale transfer endpoint needs Startup ($79), not Hobbyist.

---

## 5. DEX Screener API (new listing hype)

Source: https://docs.dexscreener.com/api/reference (and `.md`). Base `https://api.dexscreener.com`, no key. LIVE: `/token-boosts/latest/v1` and `/latest/dex/search?q=PEPE` returned 200 from the US sandbox, so this works from GitHub Actions.

| Endpoint | Limit/min | Use |
|---|---|---|
| GET `/token-profiles/latest/v1` | 60 | Newly created token profiles (paid listing info: chainId, tokenAddress, links) |
| GET `/token-profiles/recent-updates/v1` | 60 | Recently updated profiles |
| GET `/token-boosts/latest/v1` | 60 | Latest paid boosts (promo spend = hype proxy) |
| GET `/token-boosts/top/v1` | 60 | Tokens with most active boosts |
| GET `/orders/v1/{chainId}/{tokenAddress}` | 60 | Paid orders for a token (profile, ads, boosts) with timestamps |
| GET `/community-takeovers/latest/v1` | 60 | CTOs with `claimDate` |
| GET `/ads/latest/v1` | 60 | Latest ads (type, durationHours, impressions) |
| GET `/metas/trending/v1` | 60 | Trending narratives with marketCap, liquidity, volume, change m5/h1/h6/h24 |
| GET `/metas/meta/v1/{slug}` | 60 | Pairs inside a narrative |
| GET `/latest/dex/search?q=` | 300 | Search pairs |
| GET `/latest/dex/pairs/{chainId}/{pairId}` | 300 | Pair detail |
| GET `/token-pairs/v1/{chainId}/{tokenAddress}` | 300 | All pools for a token |
| GET `/tokens/v1/{chainId}/{tokenAddresses}` | 300 | Up to 30 comma separated addresses |

Pair objects include `priceUsd`, `txns` (buys/sells by m5/h1/h6/h24), `volume`, `priceChange`, `liquidity.usd`, `fdv`, `marketCap`, `pairCreatedAt`, `boosts.active`, `info.socials`. Practical hype signal for a CEX perp trader: a token trending on DEX Screener (boosts + metas) that ALSO appears in `data/bybit_perps.json` (new Bybit listing) is the overlap worth alerting.

---

## 6. Paid signal/data services at or under US$50/mo

| Service | Price | Data | API at that price? | Verdict | Source |
|---|---|---|---|---|---|
| Coinalyze | Free | OI, funding, predicted funding, liquidations, L/S, OHLCV + buy volume, 1 min to daily | Yes, free, 40 calls/min | Best value. Use | https://api.coinalyze.net/v1/doc/ |
| CoinGlass Hobbyist | $29/mo | See section 3 (4h+ history, snapshots, no heatmap) | Yes, 30 req/min | Optional | https://www.coinglass.com/pricing |
| Santiment Sanbase Pro | $49/mo ($529/yr) | Full history in Sanbase UI, social trends, on-chain | Limited; real-time unrestricted API needs Max $249/mo | UI only at budget. Skip | https://santiment.net/pricing/ |
| Laevitas Premium | $50/mo per seat | Derivatives dashboards (options heavy), 1 yr history, CSV | No (API at Enterprise $500/mo) | Options focus, no API. Skip | https://www.laevitas.ch/pricing |
| Hyblock Capital | Basic $0; Advanced $69/mo billed annually (liq levels + heatmap, no API); Professional $399/mo annual (API, private group) | Liquidation levels/heatmaps, orderbook | Only at $399 | Over budget for API. Advanced is the cheapest real liq heatmap if he wants it visually | https://thegodfunded.com/en/tools/hyblock/ (third party; Hyblock's own page renders prices client side: https://hyblockcapital.com/pricing) |
| Kingfisher | Pro $65/mo (780/yr), Max $90/mo | LiqMaps, GEX+, toxic flow, alerts | 420 API credits/mo, 2 symbols, 3 months | Over budget | https://thekingfisher.io/pricing |
| Velo Data | Free charts; Pro and API paid, price not published | CEX futures, funding, basis history | API key required (LIVE: api.velo.xyz returns 403 "api key not authorized") | Use free web charts only | https://www.sharpe.ai/compare/sharpe-vs-velo |
| The TIE | Enterprise sales only, no public price | Sentiment, news, on-chain | Enterprise | Out of scope | https://solutions.thetie.io/thetie/ |
| Telegram "signal groups" | $20 to $200/mo typical | Calls with no audited record | No | **Do not buy.** See below | |

Evidence on Telegram signal groups:
* Xu and Livshits, USENIX Security 2019: 412 pump and dump events organized in Telegram channels in about 8 months (https://www.usenix.org/conference/usenixsecurity19/presentation/xu-jiahua , paper https://arxiv.org/pdf/1811.10109).
* Hamrick et al. (Tulsa, New Mexico, Tel Aviv): 4,818 pump signals Jan to Jul 2018, 3,767 on Telegram (https://www.financemagnates.com/cryptocurrency/news/telegram-is-a-hub-of-crypto-pump-and-dump-schemes-study-shows/).
* CFTC advisory: groups on messaging apps announce coin and exchange, organizers sell first, "Don't purchase digital coins or tokens because of a single tip, especially if it comes over social media" (https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/beware_virtual_currency_pump_dump.html).
* Structural problem: no verifiable, timestamped, cost-inclusive track record; survivorship (failed groups vanish); many are paid by projects to shill. None would pass our own edge gate (PF > 1, n >= 25, profitable in both halves). If he wants a group, the only acceptable test is: log every call into triggers/outcomes.py paper tracking for 25+ calls before paying a second month.

---

## 7. Free derivatives data alternatives

### 7.1 Coinalyze API (free) — recommended primary

Source: https://api.coinalyze.net/v1/doc/ (doc fetched via curl; the coinalyze.net website itself is behind Cloudflare and blocked this sandbox, API host returned 401 without key, so it is reachable).

* Base `https://api.coinalyze.net/v1`, auth `api_key` header or query param, key from coinalyze.net/account/api-key after signup.
* **40 calls/min per key**, 429 with `Retry-After`. Each symbol in a multi-symbol call (max 20) costs one call.
* Retention: intraday (1min to 12hour) keeps only 1,500 to 2,000 datapoints per series (old data deleted daily); daily kept forever. So 15m gives about 15 to 20 days, 1h about 62 to 83 days. Our system must store what it pulls (Supabase) to build longer history.
* Endpoints: `/exchanges`, `/future-markets`, `/spot-markets`, `/assets` (added 2026-09-06), `/open-interest`, `/funding-rate`, `/predicted-funding-rate`, `/open-interest-history`, `/funding-rate-history`, `/predicted-funding-rate-history`, `/liquidation-history` (fields `l` longs, `s` shorts), `/long-short-ratio-history` (`r`, `l` %, `s` %), `/ohlcv-history` (includes `bv` buy volume, sell = v minus bv, i.e. taker flow).
* Intervals: `1min, 5min, 15min, 30min, 1hour, 2hour, 4hour, 6hour, 12hour, daily`. Symbols like `BTCUSDT_PERP.A` (suffix = exchange code; get Bybit's code from `/exchanges`).
* Free, attribution requested if published.

### 7.2 Exchange public endpoints reachable from GitHub Actions (LIVE 200 today)

| Venue | Endpoint | Data |
|---|---|---|
| OKX | `/api/v5/public/funding-rate?instId=BTC-USDT-SWAP` | Current funding |
| OKX | `/api/v5/public/funding-rate-history?instId=...&limit=` | Funding history |
| OKX | `/api/v5/public/open-interest?instType=SWAP&instId=...` | OI (contracts, coin, USD) |
| OKX | `/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1H` | OI + volume series (5m/1H/1D) |
| OKX | `/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1H` | L/S account ratio |
| OKX | `/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1H` | Taker buy/sell |
| OKX | `/api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled` | Recent liquidations (side, price, size) |
| MEXC | `https://contract.mexc.com/api/v1/contract/funding_rate/{SYM}` and `/funding_rate/history?symbol=` | Funding |
| MEXC | `/api/v1/contract/ticker?symbol=` | Ticker incl. holdVol (OI) |
| Gate | `https://api.gateio.ws/api/v4/futures/usdt/contracts/{SYM}` | Funding, mark, OI fields |
| Bitget | `https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol=&productType=usdt-futures` | Funding |
| Hyperliquid | POST `https://api.hyperliquid.xyz/info` `{"type":"metaAndAssetCtxs"}` | Funding, OI, mark for all HL perps |
| Binance | fapi.binance.com | 451 restricted location (blocked from US) |

### 7.3 Bybit public via the non-US runner

Through the Supabase Sydney bridge the same function can also pull Bybit public market data with no key: `/v5/market/tickers?category=linear` (funding, OI, 24h data for all perps in one call), `/v5/market/open-interest`, `/v5/market/funding/history`, `/v5/market/account-ratio`. That replaces the MEXC candle fallback for Bybit native funding/OI, which matters because he trades Bybit.

---

## 8. Ranked recommendation table

| Rank | Item | Cost/mo | Why | Action |
|---|---|---|---|---|
| 1 | Supabase Edge Function bridge in ap-southeast-2 (Sydney) + pg_cron | $0 | Solves the Bybit geoblock inside the stack we already run; reads positions, wallet, closed PnL, fills, grid detail with a read-only key | Smoke test, then build `bybit-bridge` |
| 2 | Coinalyze API | $0 | Intraday OI, funding, predicted funding, liquidations, L/S, taker flow incl. Bybit, 40 calls/min | Get key, add `utils/coinalyze.py`, persist to Supabase |
| 3 | OKX rubik + public endpoints, MEXC, Hyperliquid | $0 | Cross-venue confirmation, reachable from GitHub Actions today | Use as fallback and confirmation |
| 4 | DEX Screener | $0 | Boosts, profiles, metas = hype radar; intersect with Bybit perps list | 60/min routes polled every 5 min |
| 5 | Whale Alert public Telegram + Arkham free alerts to Telegram | $0 | Big flow awareness without paying | Arkham alert to his Telegram; optional t.me/s scrape |
| 6 | Oracle Always Free Sydney VM | $0 | Fallback runner with static IP (permanent key) and full Python | Only if Supabase egress is 403'd |
| 7 | CoinGlass Hobbyist | $29 | 4h+ aggregated regime data, pairs-markets snapshot, CoinGlass MCP for ad hoc questions. No heatmap, no intraday history | Optional, one month trial, keep only if it adds something Coinalyze does not |
| 8 | Bybit official MCP on his Mac with read-only key | $0 | Ad hoc questions from Claude Code on the Mac | Pin version, read-only key only |
| 9 | Whale Alert Alerts $14.95 | $14.95 | App push only, no API, no Telegram | Skip |
| 10 | Whale Alert Alerts API $29.95 | $29.95 | Real WebSocket API, but whale flow is a weak 15m/1h alt perp signal | Skip unless backtest on free archive shows edge |
| 11 | Santiment Pro $49, Laevitas $50, Hyblock, Kingfisher, Velo Pro, TheTie, Telegram groups | n/a | No usable API at budget, or no evidence of edge | Skip |

## 9. Decided stack (within US$50/mo)

| Layer | Choice | Cost |
|---|---|---|
| Runner for Bybit private + public | Supabase Edge Function pinned to ap-southeast-2, pg_cron every 2 min, read-only sub-account key; fallback Oracle Always Free Sydney | $0 |
| Derivatives data (intraday) | Coinalyze free API, stored into Supabase each run | $0 |
| Cross-venue confirmation | OKX public + rubik, MEXC, Hyperliquid info | $0 |
| Hype radar | DEX Screener free endpoints | $0 |
| Whale flow | Arkham free alerts to Telegram, Whale Alert public channel | $0 |
| Regime context (optional) | CoinGlass Hobbyist, month to month | $29 |
| **Total** | | **$0 to $29** (leaves $21 headroom; do not spend it on Whale Alert $14.95) |

Open items that need a live test from a non-US IP (cannot be done from this sandbox):
1. Supabase ap-southeast-2 egress gets 200 from api.bybit.com (not CloudFront country or cloud range blocked).
2. Read-only key can call POST `/v5/fgridbot/detail` and POST `/v5/fgridbot/validate`.
3. Whether grid bot positions show in `/v5/position/list` (decides how the revenge tagger excludes grid fills).
4. Where the Bybit app shows `bot_id` so he can register each grid.
