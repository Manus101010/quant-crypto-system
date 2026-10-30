# Daily movers, tested the way you trade them (30 Oct 2026)

Code: `research/movers/run.py`. Data: Binance USDT-M 1h, delisted coins included, Aug 2021 to Oct 2026, coins trading >= $10M a day. A "mover" is a coin up >= 25% or down >= 20% over the last 24h. Each signal is compared with random entries on the same mover list using the same stop and target, so we can tell whether the timing adds anything beyond picking the list.

| State | Trade | 2023-25 PF (maker) | 2025-26 PF | 2021-22 PF | Random on same list |
|---|---|---|---|---|---|
| Gainer rolling over (stretched >= 3 ATR, bars shrinking to <= 0.7x, SAR flips down) | short to the 1h midline | 0.84 (n 36) | too few | too few | 1.07 / 1.09 |
| Same, skipping fresh 90 day breakouts | short to midline | 0.64 (n 21) | too few | too few | 1.20 / 1.12 |
| Gainer still running (SAR up, no midline touch 12h) | long, 5% trail | 0.92 | 0.83 | 0.59 | 0.82 / 0.86 |
| Same, with the 4h trend up | long, 5% trail | 1.31 | 0.98 | 0.32 | 0.89 / 0.99 |
| Loser turning up (mirror of the rollover) | long to midline | 0.18 (n 22) | too few | too few | 1.44 / 0.25 |
| Loser still dumping (SAR down, no midline touch 12h) | short, 5% trail | **1.36** (n 120) | **1.35** (n 186) | 0.91 | 1.32 / 1.34 |

Read:
* The overextension fade back to the midline is right often (39% hit the midline before the stop), but the stops cost more than the midline pays. Both the rollover fade and the bounce long lose on 1h bars.
* Shorting coins that keep dumping is the only state that made money in both the 2023-25 and 2025-26 periods. It failed in the 2021-22 bull. Random shorts on the same loser list did about as well, so the list (and a bear market) is the edge, not the exact trigger. t is about 1.1 to 1.3, which is below the bar for a live setup. It goes on paper, only while BTC is below its 50 day.
* Limitation: 1h bars only. You read 15m. A 15m version needs 15m history, which can be fetched for a follow up.

Live: `desk/movers.py`, used by `/movers` in Telegram, the morning brief and the web app's Movers page. Every board is stored as `movers:<time>` in app_state so the states can be graded against what price did next.
