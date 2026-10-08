---
name: strategy-intake
description: Turn an outside trading idea (Pine script, TradingView/Stonehill/QuantConnect/Quantpedia link, X post, paper) into a research/strategies module and test it through research/intake/run.py with the multiple-testing bar. Use when Manus pastes a strategy, a Pine script or a link and asks to test it, or types /strategy-intake.
---

# Strategy intake

Goal: test an outside strategy honestly, on the full MEXC perp universe, with the
same costs and pass rules as every other setup, and log it so the bar rises as
more ideas are tried. Never wire anything into the live scanner from here.

## Steps

1. **Read the source.** Pine script: read the code. Link: fetch the page and
   extract the exact rules (entry, exit, stop, filters, timeframe, defaults).
   If rules are vague, write down the most literal reading and say so.
2. **Check for leaks before converting.** Reject or fix: `security(...,
   lookahead=barmerge.lookahead_on)`, `close[-1]`-style future references,
   repainting pivots/zigzag, indicators that recalculate past bars, strategy
   tester settings with zero commission/slippage. Note what you changed.
3. **Write `research/strategies/<slug>.py`** from `_template.py`:
   NAME, SOURCE (URL or file), HYPOTHESIS (who loses money to this trade and
   why it should persist), DIRECTION, MIN_BARS, MIN_QV, PARAMS, `signal`, `plan`.
   PARAMS: the published defaults first, then at most 4 neighbours (about +/-20%).
   Never sweep large grids; every variant raises the bar for all future ideas.
   Daily timeframe only for now; if the source is intraday, say the daily
   translation is an approximation.
4. **Run it** on the full universe:
   `./venv/bin/python research/intake/run.py <slug> $RESEARCH_HISTORY`
   (build the history with `research/families/fetch_perps.py` if missing).
5. **Report back** in plain words: verdict (REJECT / WATCH / CANDIDATE), n, PF,
   win rate, expectancy in R, the t-stat vs the t-stat needed, and how it did by
   BTC regime, liquidity tier and year. Point to
   `research/intake/results/<slug>.md`.
6. **Commit** the strategy module, its results file and the updated
   `research/intake/leaderboard.csv` on a research branch.

## Verdicts (set by run.py, do not override)

* REJECT: fails PF > 1, n >= 50, PF > 1 in both halves, expectancy R > 0.
* WATCH: passes those but not the stricter checks.
* CANDIDATE: also clears the Bonferroni t-stat for the number of strategies tested
  so far, survives removing crowded days, and most neighbouring variants agree.

Only CANDIDATEs may be proposed for the live scanner, and then they still go
through `backtesting/crypto_validation` and the "Took it" forward test.

## Never

* Claim a backtest number from TradingView's strategy tester as verification.
* Tune parameters after seeing results and rerun as a "new" strategy.
* Put an LLM in the live trade decision; strategies must be deterministic code.
