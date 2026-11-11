# Pairs mean reversion (walk-forward, market neutral)

'expR' and 'totR' are mean / total % return per trade on the capital used.

| variant | n | PF | win | expR | totR | maxDD R | PF 1st half | PF 2nd half | verdict |
|---|---|---|---|---|---|---|---|---|---|
| corr>=0.7 entry |z|>=2.0 | 716 | 0.85 | 56% | -0.406 | -290 | -320 | 0.91 | 0.79 | fail |
| corr>=0.7 entry |z|>=2.5 | 466 | 0.98 | 57% | -0.060 | -28 | -168 | 1.07 | 0.89 | fail |
| corr>=0.8 entry |z|>=2.0 | 566 | 0.92 | 57% | -0.185 | -105 | -202 | 1.03 | 0.83 | fail |
| corr>=0.8 entry |z|>=2.5 | 365 | 0.99 | 56% | -0.020 | -7 | -148 | 1.08 | 0.91 | fail |