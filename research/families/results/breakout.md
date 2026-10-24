# Compression breakouts (staged) and mirrored breakdowns

Coins: 219. Costs 0.36% round trip. Daily bars.


## Control: production Donchian 55d idea under this harness

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| Donchian 55d long, trail 3.5 ATR | 917 | 1.34 | 43% | +0.167 | +154 | -70 | 1.64 | 1.06 | PASS |

## LONG variants

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| long prepos coil10 vol- post-trend trail | 474 | 0.90 | 34% | -0.016 | -7 | -87 | 0.94 | 0.85 | fail |
| long prepos coil10 vol- post-trend struct | 488 | 0.84 | 34% | -0.023 | -11 | -84 | 0.82 | 0.85 | fail |
| long fired coil10 vol1.5 post-trend trail | 526 | 1.09 | 37% | +0.093 | +49 | -57 | 1.33 | 0.84 | fail |
| long fired coil10 vol1.5 post-trend struct | 569 | 1.09 | 30% | +0.141 | +80 | -64 | 1.25 | 0.94 | fail |
| long confirmed coil10 vol1.5 post-trend trail | 468 | 0.88 | 33% | -0.006 | -3 | -67 | 1.02 | 0.75 | fail |
| long confirmed coil10 vol1.5 post-trend struct | 493 | 0.80 | 27% | -0.131 | -65 | -99 | 0.89 | 0.71 | fail |
| long prepos coil10 vol- any trail | 716 | 0.83 | 33% | -0.048 | -34 | -157 | 1.01 | 0.66 | fail |
| long prepos coil10 vol- any struct | 742 | 0.76 | 32% | -0.071 | -53 | -158 | 0.87 | 0.64 | fail |
| long fired coil10 vol1.5 any trail | 662 | 1.06 | 36% | +0.089 | +59 | -58 | 1.24 | 0.86 | fail |
| long fired coil10 vol1.5 any struct | 720 | 1.03 | 29% | +0.086 | +62 | -66 | 1.14 | 0.91 | fail |
| long confirmed coil10 vol1.5 any trail | 589 | 0.92 | 34% | +0.016 | +10 | -67 | 1.13 | 0.75 | fail |
| long confirmed coil10 vol1.5 any struct | 625 | 0.86 | 27% | -0.110 | -69 | -115 | 1.01 | 0.72 | fail |
| long fired coil10 vol2.0 post-trend trail | 415 | 1.05 | 35% | +0.082 | +34 | -50 | 1.32 | 0.79 | fail |
| long fired coil10 vol2.0 post-trend struct | 439 | 1.03 | 28% | +0.117 | +51 | -52 | 1.27 | 0.82 | fail |
| long confirmed coil10 vol2.0 post-trend trail | 362 | 0.91 | 32% | +0.003 | +1 | -53 | 1.05 | 0.78 | fail |
| long confirmed coil10 vol2.0 post-trend struct | 378 | 0.76 | 26% | -0.143 | -54 | -79 | 0.81 | 0.72 | fail |
| long fired coil10 vol2.0 any trail | 526 | 1.03 | 36% | +0.086 | +45 | -51 | 1.26 | 0.80 | fail |
| long fired coil10 vol2.0 any struct | 556 | 1.00 | 28% | +0.069 | +39 | -62 | 1.21 | 0.80 | fail |
| long confirmed coil10 vol2.0 any trail | 462 | 0.94 | 34% | +0.022 | +10 | -54 | 1.08 | 0.82 | fail |
| long confirmed coil10 vol2.0 any struct | 482 | 0.89 | 27% | -0.083 | -40 | -77 | 1.00 | 0.79 | fail |
| long prepos coil20 vol- post-trend trail | 631 | 0.76 | 33% | -0.097 | -61 | -131 | 0.90 | 0.64 | fail |
| long prepos coil20 vol- post-trend struct | 652 | 0.72 | 33% | -0.086 | -56 | -116 | 0.70 | 0.73 | fail |
| long fired coil20 vol1.5 post-trend trail | 678 | 1.04 | 36% | +0.070 | +47 | -84 | 1.56 | 0.62 | fail |
| long fired coil20 vol1.5 post-trend struct | 740 | 0.95 | 28% | +0.045 | +34 | -88 | 1.17 | 0.75 | fail |
| long confirmed coil20 vol1.5 post-trend trail | 606 | 0.95 | 33% | +0.011 | +7 | -98 | 1.37 | 0.61 | fail |
| long confirmed coil20 vol1.5 post-trend struct | 650 | 0.78 | 25% | -0.143 | -93 | -139 | 1.00 | 0.57 | fail |
| long prepos coil20 vol- any trail | 973 | 0.78 | 31% | -0.090 | -87 | -211 | 1.13 | 0.48 | fail |
| long prepos coil20 vol- any struct | 1011 | 0.74 | 32% | -0.073 | -74 | -175 | 0.99 | 0.53 | fail |
| long fired coil20 vol1.5 any trail | 898 | 1.04 | 37% | +0.079 | +71 | -89 | 1.31 | 0.76 | fail |
| long fired coil20 vol1.5 any struct | 983 | 0.95 | 28% | +0.058 | +57 | -97 | 1.05 | 0.83 | fail |
| long confirmed coil20 vol1.5 any trail | 802 | 0.96 | 35% | +0.026 | +21 | -108 | 1.36 | 0.61 | fail |
| long confirmed coil20 vol1.5 any struct | 862 | 0.85 | 27% | -0.088 | -75 | -149 | 1.15 | 0.57 | fail |
| long fired coil20 vol2.0 post-trend trail | 526 | 1.03 | 36% | +0.085 | +45 | -72 | 1.50 | 0.64 | fail |
| long fired coil20 vol2.0 post-trend struct | 562 | 0.90 | 27% | +0.030 | +17 | -71 | 1.14 | 0.70 | fail |
| long confirmed coil20 vol2.0 post-trend trail | 463 | 0.98 | 33% | +0.041 | +19 | -69 | 1.29 | 0.72 | fail |
| long confirmed coil20 vol2.0 post-trend struct | 493 | 0.74 | 25% | -0.151 | -75 | -104 | 0.87 | 0.62 | fail |
| long fired coil20 vol2.0 any trail | 704 | 0.99 | 37% | +0.085 | +60 | -77 | 1.29 | 0.70 | fail |
| long fired coil20 vol2.0 any struct | 748 | 0.89 | 28% | +0.053 | +39 | -84 | 1.04 | 0.75 | fail |
| long confirmed coil20 vol2.0 any trail | 620 | 0.98 | 35% | +0.054 | +33 | -74 | 1.35 | 0.66 | fail |
| long confirmed coil20 vol2.0 any struct | 657 | 0.87 | 27% | -0.056 | -37 | -109 | 1.15 | 0.62 | fail |

## SHORT variants

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| short prepos coil10 vol- post-trend trail | 415 | 2.66 | 60% | +0.447 | +186 | -19 | 1.75 | 3.98 | PASS |
| short prepos coil10 vol- post-trend struct | 428 | 2.50 | 56% | +0.393 | +168 | -25 | 1.60 | 3.92 | PASS |
| short fired coil10 vol1.5 post-trend trail | 250 | 1.78 | 56% | +0.163 | +41 | -26 | 0.79 | 4.06 | fail |
| short fired coil10 vol1.5 post-trend struct | 267 | 1.28 | 37% | +0.001 | +0 | -56 | 0.78 | 2.00 | fail |
| short confirmed coil10 vol1.5 post-trend trail | 187 | 1.96 | 56% | +0.146 | +27 | -16 | 0.97 | 4.15 | fail |
| short confirmed coil10 vol1.5 post-trend struct | 196 | 1.67 | 38% | +0.096 | +19 | -33 | 1.14 | 2.35 | PASS |
| short prepos coil10 vol- any trail | 1099 | 1.38 | 46% | +0.130 | +142 | -86 | 1.82 | 1.04 | PASS |
| short prepos coil10 vol- any struct | 1154 | 1.31 | 44% | +0.088 | +102 | -98 | 1.77 | 0.94 | fail |
| short fired coil10 vol1.5 any trail | 571 | 1.30 | 49% | +0.064 | +36 | -60 | 1.31 | 1.29 | PASS |
| short fired coil10 vol1.5 any struct | 625 | 1.13 | 34% | -0.023 | -14 | -129 | 1.20 | 1.07 | fail |
| short confirmed coil10 vol1.5 any trail | 463 | 1.40 | 50% | +0.075 | +35 | -49 | 1.33 | 1.48 | PASS |
| short confirmed coil10 vol1.5 any struct | 496 | 1.21 | 35% | -0.005 | -2 | -113 | 1.44 | 1.01 | fail |
| short fired coil10 vol2.0 post-trend trail | 155 | 1.52 | 55% | +0.094 | +15 | -19 | 0.81 | 3.09 | fail |
| short fired coil10 vol2.0 post-trend struct | 163 | 1.45 | 41% | +0.054 | +9 | -31 | 0.90 | 2.35 | fail |
| short confirmed coil10 vol2.0 post-trend trail | 110 | 1.86 | 55% | +0.105 | +12 | -9 | 1.20 | 2.86 | PASS |
| short confirmed coil10 vol2.0 post-trend struct | 114 | 2.05 | 43% | +0.176 | +20 | -17 | 1.60 | 2.56 | PASS |
| short fired coil10 vol2.0 any trail | 376 | 1.19 | 50% | +0.019 | +7 | -49 | 0.88 | 1.57 | fail |
| short fired coil10 vol2.0 any struct | 396 | 1.19 | 37% | -0.045 | -18 | -83 | 0.99 | 1.43 | fail |
| short confirmed coil10 vol2.0 any trail | 298 | 1.39 | 51% | +0.065 | +19 | -36 | 1.05 | 1.79 | PASS |
| short confirmed coil10 vol2.0 any struct | 310 | 1.36 | 37% | +0.012 | +4 | -79 | 1.15 | 1.59 | PASS |
| short prepos coil20 vol- post-trend trail | 538 | 2.23 | 57% | +0.370 | +199 | -30 | 1.20 | 4.08 | PASS |
| short prepos coil20 vol- post-trend struct | 552 | 2.34 | 56% | +0.342 | +189 | -29 | 1.27 | 4.18 | PASS |
| short fired coil20 vol1.5 post-trend trail | 341 | 1.73 | 56% | +0.154 | +53 | -31 | 0.76 | 3.73 | fail |
| short fired coil20 vol1.5 post-trend struct | 370 | 1.24 | 39% | +0.055 | +20 | -51 | 0.81 | 1.75 | fail |
| short confirmed coil20 vol1.5 post-trend trail | 268 | 1.82 | 56% | +0.139 | +37 | -21 | 0.82 | 4.00 | fail |
| short confirmed coil20 vol1.5 post-trend struct | 281 | 1.51 | 39% | +0.138 | +39 | -40 | 0.91 | 2.23 | fail |
| short prepos coil20 vol- any trail | 1360 | 1.28 | 45% | +0.102 | +139 | -124 | 1.52 | 1.04 | PASS |
| short prepos coil20 vol- any struct | 1405 | 1.32 | 45% | +0.091 | +128 | -110 | 1.69 | 1.00 | PASS |
| short fired coil20 vol1.5 any trail | 746 | 1.18 | 48% | +0.046 | +34 | -77 | 1.30 | 1.07 | PASS |
| short fired coil20 vol1.5 any struct | 827 | 1.06 | 34% | -0.002 | -2 | -139 | 1.20 | 0.93 | fail |
| short confirmed coil20 vol1.5 any trail | 634 | 1.27 | 49% | +0.052 | +33 | -64 | 1.29 | 1.24 | PASS |
| short confirmed coil20 vol1.5 any struct | 680 | 1.15 | 35% | +0.015 | +10 | -140 | 1.40 | 0.92 | fail |
| short fired coil20 vol2.0 post-trend trail | 232 | 1.68 | 58% | +0.131 | +30 | -24 | 0.72 | 4.30 | fail |
| short fired coil20 vol2.0 post-trend struct | 243 | 1.39 | 44% | +0.116 | +28 | -37 | 0.74 | 2.23 | fail |
| short confirmed coil20 vol2.0 post-trend trail | 170 | 1.76 | 56% | +0.110 | +19 | -19 | 0.80 | 3.97 | fail |
| short confirmed coil20 vol2.0 post-trend struct | 175 | 1.75 | 44% | +0.219 | +38 | -27 | 1.01 | 2.65 | PASS |
| short fired coil20 vol2.0 any trail | 518 | 1.21 | 50% | +0.036 | +18 | -44 | 0.96 | 1.52 | fail |
| short fired coil20 vol2.0 any struct | 546 | 1.15 | 38% | -0.011 | -6 | -81 | 0.94 | 1.40 | fail |
| short confirmed coil20 vol2.0 any trail | 422 | 1.29 | 51% | +0.047 | +20 | -44 | 0.84 | 1.89 | fail |
| short confirmed coil20 vol2.0 any struct | 437 | 1.25 | 37% | +0.020 | +9 | -92 | 0.92 | 1.61 | fail |

## Top variants split by context


### short prepos coil10 vol- post-trend trail

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 37 | 0.58 | 30% | -0.190 | -7 | -8 | 0.77 | 0.43 | fail |
| BTC MIXED | 167 | 3.25 | 66% | +0.521 | +87 | -13 | 3.88 | 2.83 | PASS |
| BTC UP | 211 | 2.90 | 61% | +0.501 | +106 | -18 | 1.08 | 8.78 | PASS |

By year: 2020: n21 PF 1.06 · 2021: n74 PF 1.70 · 2022: n24 PF 2.33 · 2023: n41 PF 1.47 · 2024: n49 PF 2.01 · 2025: n178 PF 5.82 · 2026: n28 PF 0.68


### short prepos coil10 vol- post-trend struct

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 38 | 0.58 | 29% | -0.180 | -7 | -8 | 0.54 | 0.62 | fail |
| BTC MIXED | 174 | 3.15 | 61% | +0.490 | +85 | -19 | 4.07 | 2.59 | PASS |
| BTC UP | 216 | 2.60 | 57% | +0.416 | +90 | -19 | 0.97 | 8.37 | fail |

By year: 2020: n21 PF 1.24 · 2021: n75 PF 1.57 · 2022: n24 PF 1.72 · 2023: n41 PF 1.38 · 2024: n51 PF 1.82 · 2025: n187 PF 5.13 · 2026: n29 PF 0.87


### short prepos coil20 vol- post-trend struct

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 44 | 0.97 | 45% | +0.077 | +3 | -7 | 2.05 | 0.51 | fail |
| BTC MIXED | 227 | 2.94 | 61% | +0.399 | +91 | -18 | 1.93 | 4.37 | PASS |
| BTC UP | 281 | 2.28 | 54% | +0.338 | +95 | -26 | 0.84 | 6.03 | fail |

By year: 2020: n27 PF 0.55 · 2021: n102 PF 1.37 · 2022: n27 PF 4.13 · 2023: n52 PF 1.02 · 2024: n78 PF 1.49 · 2025: n230 PF 5.45 · 2026: n36 PF 0.89


### short prepos coil20 vol- post-trend trail

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 44 | 0.76 | 39% | -0.044 | -2 | -8 | 1.59 | 0.39 | fail |
| BTC MIXED | 221 | 3.00 | 63% | +0.463 | +102 | -14 | 1.93 | 4.68 | PASS |
| BTC UP | 273 | 2.15 | 55% | +0.362 | +99 | -26 | 0.80 | 5.96 | fail |

By year: 2020: n26 PF 0.42 · 2021: n99 PF 1.42 · 2022: n27 PF 3.13 · 2023: n50 PF 0.86 · 2024: n78 PF 1.35 · 2025: n223 PF 5.62 · 2026: n35 PF 0.74


### short confirmed coil10 vol2.0 post-trend struct

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 18 | 1.19 | 33% | -0.229 | -4 | -7 | 0.35 | 2.70 | fail |
| BTC MIXED | 60 | 1.91 | 45% | +0.127 | +8 | -22 | 2.91 | 1.22 | PASS |
| BTC UP | 36 | 3.01 | 44% | +0.461 | +17 | -12 | 1.21 | 6.34 | PASS |

By year: 2020: n7 PF 0.00 · 2021: n21 PF 4.23 · 2022: n16 PF 1.19 · 2023: n10 PF 1.01 · 2024: n16 PF 0.86 · 2025: n43 PF 2.98 · 2026: n1 PF 99.00


### short confirmed coil10 vol1.5 post-trend trail

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC DOWN | 26 | 0.58 | 31% | -0.286 | -7 | -10 | 0.59 | 0.56 | fail |
| BTC MIXED | 107 | 2.29 | 60% | +0.211 | +23 | -13 | 1.58 | 3.61 | PASS |
| BTC UP | 54 | 2.59 | 59% | +0.224 | +12 | -11 | 0.51 | 11.01 | fail |

By year: 2020: n11 PF 0.11 · 2021: n28 PF 2.00 · 2022: n24 PF 1.04 · 2023: n16 PF 1.12 · 2024: n29 PF 1.08 · 2025: n77 PF 4.30 · 2026: n2 PF 99.00
