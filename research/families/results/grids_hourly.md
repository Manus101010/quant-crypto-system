# Grid deployment rules (hourly price paths)

Coins: 60. 10 grids, up to 30 days, 0.05% per fill, kill one grid past either edge. 'expR' and 'totR' here are mean / total % return per grid run at 1x.


| rule | range | runs | PF | win | mean % per run | killed | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| every10 | ±2 ATR | 1075 | 0.67 | 34% | -1.27% | 79% | 0.45 | 0.96 | fail |
| every10 | ±3 ATR | 1075 | 0.92 | 47% | -0.33% | 52% | 0.79 | 1.11 | fail |
| chop | ±2 ATR | 1081 | 0.57 | 28% | -1.56% | 86% | 0.37 | 0.86 | fail |
| chop | ±3 ATR | 1081 | 0.71 | 39% | -1.31% | 62% | 0.60 | 0.86 | fail |
| chop+btcmix | ±2 ATR | 745 | 0.50 | 31% | -1.62% | 88% | 0.34 | 0.73 | fail |
| chop+btcmix | ±3 ATR | 745 | 0.58 | 35% | -1.86% | 70% | 0.59 | 0.57 | fail |
| brk->long | ±2 ATR | 603 | 0.91 | 54% | -0.32% | 92% | 0.91 | 0.92 | fail |
| brk->long | ±3 ATR | 603 | 1.03 | 59% | +0.13% | 74% | 1.15 | 0.90 | fail |
| brk->neutral | ±2 ATR | 603 | 0.82 | 34% | -0.50% | 92% | 0.68 | 1.01 | fail |
| brk->neutral | ±3 ATR | 603 | 0.93 | 38% | -0.26% | 74% | 0.85 | 1.05 | fail |
| chop->long | ±2 ATR | 1081 | 0.63 | 51% | -1.79% | 86% | 0.48 | 0.85 | fail |
| chop->long | ±3 ATR | 1081 | 0.72 | 55% | -1.54% | 62% | 0.62 | 0.85 | fail |

## By BTC regime (±3 ATR)


### every10

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 250 | 1.25 | 59% | +0.874 | +218 | -387 | 0.56 | 3.73 | fail |
| BTC MIXED | 531 | 0.85 | 44% | -0.649 | -345 | -609 | 0.87 | 0.83 | fail |
| BTC UP | 294 | 0.85 | 43% | -0.793 | -233 | -482 | 0.60 | 1.33 | fail |

### chop

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 231 | 1.55 | 61% | +1.616 | +373 | -130 | 0.96 | 2.66 | fail |
| BTC MIXED | 503 | 0.58 | 33% | -2.008 | -1010 | -1030 | 0.56 | 0.60 | fail |
| BTC UP | 347 | 0.57 | 34% | -2.241 | -778 | -778 | 0.41 | 0.75 | fail |

### chop+btcmix

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC MIXED | 745 | 0.58 | 35% | -1.859 | -1385 | -1405 | 0.59 | 0.57 | fail |

### brk->long

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 47 | 0.60 | 53% | -2.319 | -109 | -136 | 0.47 | 0.85 | fail |
| BTC MIXED | 302 | 1.01 | 59% | +0.027 | +8 | -468 | 0.98 | 1.04 | fail |
| BTC UP | 254 | 1.16 | 60% | +0.715 | +182 | -437 | 0.83 | 1.96 | fail |

### brk->neutral

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 47 | 0.82 | 38% | -0.833 | -39 | -86 | 0.82 | 0.81 | fail |
| BTC MIXED | 302 | 0.93 | 37% | -0.254 | -77 | -326 | 1.01 | 0.84 | fail |
| BTC UP | 254 | 0.96 | 39% | -0.171 | -44 | -322 | 0.70 | 1.35 | fail |

### chop->long

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 231 | 1.56 | 68% | +1.751 | +405 | -161 | 1.21 | 2.26 | PASS |
| BTC MIXED | 503 | 0.65 | 55% | -2.018 | -1015 | -1393 | 0.59 | 0.73 | fail |
| BTC UP | 347 | 0.53 | 48% | -3.053 | -1059 | -1313 | 0.25 | 1.28 | fail |