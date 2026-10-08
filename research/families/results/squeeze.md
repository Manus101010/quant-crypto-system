# Squeeze fuel: funding before breakouts

Funding history from 2025-04-16 (MEXC). Only breakouts after that date are counted.


## long fired, coil20 vol1.5 post-trend, trail (since funding exists)

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| all | 392 | 0.72 | 34% | -0.089 | -35 | -83 | 0.95 | 0.55 | fail |
| funding < 0 (crowded short) | 109 | 0.69 | 35% | -0.077 | -8 | -25 | 1.18 | 0.39 | fail |
| funding >= 0 | 283 | 0.73 | 34% | -0.093 | -26 | -60 | 0.94 | 0.59 | fail |

## long fired, coil20 vol1.5 any, trail (since funding exists)

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| all | 451 | 0.78 | 35% | -0.059 | -27 | -88 | 0.94 | 0.66 | fail |
| funding < 0 (crowded short) | 120 | 0.74 | 36% | -0.059 | -7 | -28 | 1.11 | 0.50 | fail |
| funding >= 0 | 331 | 0.79 | 34% | -0.060 | -20 | -61 | 0.92 | 0.69 | fail |

## short fired, coil20 vol1.5 post-trend, trail (since funding exists)

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| all | 105 | 2.39 | 68% | +0.343 | +36 | -18 | 1.86 | 3.07 | PASS |
| funding <= +0.01% | 102 | 2.42 | 69% | +0.360 | +37 | -18 | 1.91 | 3.11 | PASS |
| funding > +0.01% (crowded long) | 3 | 1.29 | 33% | -0.233 | -1 | -1 | 0.00 | 2.20 | fail |

## short fired, coil20 vol1.5 any, trail (since funding exists)

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| all | 291 | 1.20 | 49% | +0.106 | +31 | -64 | 0.90 | 1.58 | fail |
| funding <= +0.01% | 285 | 1.20 | 50% | +0.114 | +32 | -62 | 0.93 | 1.54 | fail |
| funding > +0.01% (crowded long) | 6 | 0.97 | 33% | -0.244 | -1 | -2 | 0.00 | 5.69 | fail |