# Strategy intake

A safe way to test outside strategy ideas (TradingView scripts, Stonehill Forex,
QuantConnect, Quantpedia, X posts) without fooling yourself.

Testing 50 strategies and picking the best one mostly finds luck. This pipeline
fixes that by (1) running every idea through the same costs, universe and pass
rules as the scanner's own setups, and (2) raising the bar as more ideas are
tried: the t-stat needed grows with the number of strategies on the leaderboard.

## Use

In Claude Code: paste the Pine script or link and say "test this strategy" (the
`strategy-intake` skill does the rest), or by hand:

```
./venv/bin/python research/families/fetch_perps.py /tmp/perps.pkl     # all MEXC crypto perps, daily
cp research/strategies/_template.py research/strategies/my_idea.py     # fill it in
./venv/bin/python research/intake/run.py my_idea /tmp/perps.pkl
```

Output: `results/<slug>.md` plus a row per variant in `leaderboard.csv`.

## Verdicts

| verdict | meaning |
|---|---|
| REJECT | fails PF > 1, n >= 50, PF > 1 in both halves, or expectancy R > 0 |
| WATCH | passes the basic bar but not the strict checks |
| CANDIDATE | also clears the multiple-testing t-stat, survives removing crowded days, and most neighbouring variants agree |

Costs are tiered: 0.36% round trip for coins with >= $2M daily volume, 0.80% for
thinner coins. Only coins listed today are in the data (survivorship), which
flatters longs and understates shorts.
