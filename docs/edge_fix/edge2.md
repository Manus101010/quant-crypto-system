# Edge round 2: "who is paying?" ideas (8 Nov 2026)

Prompted by Ruuj's quant roadmap post (29 Oct 2026): an edge needs a reason someone pays for it. Pre-register a few variants, apply a multiple testing haircut, beat a random baseline, and confirm out of sample. Three helpers each tested one structural or behavioural idea. In sample (IS) is 2023-01 to 2025-07 and out of sample (OOS) is 2025-07 to 2026-10. Data is Binance USDT-M 1h with delisted coins included. Costs are taker, 0.36% round trip. Results are reported for Pionex coins. Code and pre-registrations are in research/edge2/.

| Idea | Variants | Verdict | Key numbers |
|---|---|---|---|
| Forced trading: extreme funding short | 2 | FAIL | Single print: IS PF 1.67, but 2024 mania only. OOS PF 0.94. Persistent crowding (3 prints >= 0.05%): small positive edge every half year, but OOS t 0.69. Retest Nov 2027. |
| Forced trading: negative funding long, OI flush long | 3 | FAIL | Flush longs lose, though less than random longs. A flush supports "do not short here", not "buy here". |
| DS + flush filter | 1 | Irrelevant | Only 2 to 7 cases. DS rebuilt on Binance OI coins: OOS PF 1.92, t 2.91. **Independent confirmation of the live edge.** |
| New listings drift down | 6 | FAIL | Median listing falls (-21% at 30d), but squeezes and wide stops leave avg R near 0. OOS t below 1 for every variant, and a random seasoned alt short on the same dates did better. |
| Short the day's top gainers 1 to 3 days | 6 | FAIL, wrong sign | Shorting the top 5 gainers: PF 0.80 IS, 0.88 OOS, worse than random. **On tradeable coins, gainers keep rising 1 to 3 days (momentum)**, in line with Zaremba et al. Reversal only shows up in coins too illiquid to trade. |

## Used in the system
* The movers board and morning brief now tell him that shorting top gainers lost in testing.
* Nothing new goes live as an alert.

## Logged for later
* Persistent crowded funding short (V2): retest in 6 to 12 months on new data.
* Listings with a tighter structural stop, or a listing short hedged by an alt basket: not tested, needs its own pre-registration.
* Alts bled against BTC over 2023 to 2026. A random seasoned alt short earned 0.20 to 0.36R OOS on listing dates. That is market beta, not a setup.
