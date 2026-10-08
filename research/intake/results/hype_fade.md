# Post-hype fade short (pump, peak, volume taper, roll-over)

Source: Manus: small caps that taper off after hype make excellent shorts

Hypothesis: After an attention-driven pump, demand is exhausted while unlocks, early holders and trapped buyers keep supplying; price mean-reverts toward the pre-pump level.

Coins: 562. Tiered costs (0.36% liquid, 0.80% under $2M a day). Strategies tested so far incl. this: 22, so t-stat needed = 3.05.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | t | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| pump=1.0, taper=0.4 | 3474 | 1.11 | 60% | +0.046 | +160 | -105 | 1.18 | 1.05 | 3.71 | WATCH |
| pump=2.0, taper=0.4 | 1403 | 1.11 | 64% | +0.046 | +65 | -49 | 1.20 | 1.05 | 2.55 | WATCH |
| pump=1.0, taper=0.6 | 4035 | 1.06 | 59% | +0.029 | +116 | -129 | 1.05 | 1.06 | 2.46 | WATCH |
| pump=0.7, taper=0.4 | 5066 | 1.06 | 57% | +0.024 | +122 | -176 | 1.10 | 1.03 | 2.18 | WATCH |
| pump=1.0, taper=0.3 | 2996 | 1.13 | 60% | +0.043 | +130 | -85 | 1.28 | 1.01 | 3.28 | WATCH |

## Best variant (pump=2.0, taper=0.4) split by context

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 286 | 0.77 | 60% | +0.003 | +1 | -28 | 1.12 | 0.60 | fail |
| BTC MIXED | 654 | 1.29 | 67% | +0.074 | +49 | -45 | 1.35 | 1.25 | PASS |
| BTC UP | 463 | 1.19 | 61% | +0.034 | +16 | -41 | 0.79 | 1.81 | fail |
| liquid (>= $2M/day) | 1047 | 1.23 | 67% | +0.075 | +79 | -31 | 1.27 | 1.20 | PASS |
| small cap (< $2M/day) | 356 | 0.80 | 55% | -0.039 | -14 | -39 | 1.32 | 0.52 | fail |
| excluding crowded days (> 3 signals) | 855 | 0.85 | 58% | -0.038 | -32 | -52 | 1.11 | 0.70 | fail |

By year: 2020: n3 PF 99.00 expR +0.56 · 2021: n156 PF 0.91 expR -0.10 · 2022: n32 PF 4.97 expR +0.31 · 2023: n75 PF 1.02 expR -0.01 · 2024: n207 PF 1.57 expR +0.11 · 2025: n557 PF 1.54 expR +0.16 · 2026: n373 PF 0.67 expR -0.11
