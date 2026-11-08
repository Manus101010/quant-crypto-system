Pre-registration, written 2026-11-08 BEFORE any result was computed. Six variants, no others.

Common: Binance USDT-M 1h (core.load), universe core.universe_symbols(), liquid if dvol30 >= core.MIN_DVOL (10M) at signal bar.
Signal from bar i data only (bar i closed), entry at close[i] (core.sim convention), funding from bar i+1 on.
One open trade per coin per variant. Stop distance must be within 1% to 8% (else skip).
Costs: taker 0.36% RT (headline), maker 0.11% also reported. IS 2023-01-01..2025-07-01, OOS 2025-07-01..2026-10-26.
Funding normalised to 8h equivalent: rate * 8 / interval_hours (interval inferred from print spacing).
Pass rule: IS t >= 2 AND OOS t >= 2 AND beats random baseline (mean of 20 random sets) in both; Bonferroni note: 6 variants,
one sided alpha 0.05/6 -> t >= 2.40 needed for "survives deflation".

H1 funding
 V1 FUND_SHORT: funding print (8h equiv) >= +0.10%. Short at that bar close. Stop entry + 3 x ATR14(1h). TP 2R, time exit 72h.
 V2 FUND_SHORT_PERSIST: last 3 prints all >= +0.05% (8h equiv), fire on the 3rd consecutive. Short, same exits as V1.
 V3 FUND_LONG_NEG: funding print (8h equiv) <= -0.10% AND BTC prior daily close > BTC 50 day SMA. Long, stop entry - 3 x ATR14(1h). TP 2R, 72h.

H2 open interest (Binance 5 min metrics, value at each 1h close; top 150 coins by mean quote volume 2023..2026)
 V4 FLUSH_LONG_72: 24h return <= -10% AND 24h OI change <= -15%, first bar of condition (re arm after 24h without it).
    Long, stop = min low last 24h - 0.5 x ATR14(1h). TP 2R, time exit 72h.
 V5 FLUSH_LONG_24: same signal and stop, TP 2R, time exit 24h.
 V6 DS_NOFLUSH filter: Distribution Short (skills/new_setups.detect, daily bars from Binance 1h, BTC trend from BTCUSDT),
    exits per live rule (stop 3.5 ATR, trail 3.5 ATR, TP 2R, 60 days, no stop width cap). Compare DS entries WITH a flush
    (V4 condition true at any 1h bar in the 72h before the DS daily close) vs WITHOUT. Filter passes if excluded group
    avg R is lower than kept group in IS and OOS and kept PF > all DS PF in both.
Random baseline: for each signal, a random liquid bar in the same coin and same period (IS/OOS), same stop formula and exits; 20 repeats.
