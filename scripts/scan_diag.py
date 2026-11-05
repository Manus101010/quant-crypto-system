"""Why does the cloud scan find 0 candidates? Fetch the universe like the scan does,
report coverage, fetch errors, and what the live setup rules see. Read only."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402
from utils import exchange as X  # noqa: E402
from skills import new_setups as N  # noqa: E402
from config import LIVE_VOLUME_FACTOR  # noqa: E402

N.QV_SOURCE_FACTOR = float(LIVE_VOLUME_FACTOR)
tk = X.list_perp_symbols("pionex")
print("DIAG universe:", len(tk), "geo:", sorted(X._geo_blocked))
print("DIAG mexc perp map size:", sum(1 for k in X._perp_info if k.startswith("mexc:")))
ohlc = X.get_ohlcv_batch(tk, timeframe="1d", limit=400, exchange="pionex")
got = {k: v for k, v in ohlc.items() if v is not None and not v.empty}
print("DIAG candles for:", len(got), "of", len(tk))
print("DIAG fetch fail reasons:", dict(X._perp_fail.most_common(5)))
lens = Counter(min(len(v) // 100 * 100, 400) for v in got.values())
print("DIAG bar counts (floored to 100):", dict(sorted(lens.items())))
miss = [t for t in tk if t not in got][:15]
print("DIAG sample missing:", miss)
btc = got.get("BTC-USD")
print("DIAG BTC rows:", None if btc is None else len(btc), "last:", None if btc is None else str(btc.index[-1]))
hits = Counter()
recent = []
for t, d in got.items():
    try:
        if "quote_volume" not in d:
            d = d.assign(quote_volume=d["volume"] * d["close"])
        x = N.detect(d, btc["close"] if btc is not None else None)
        lab = x["label"].iloc[-15:]
        for ts, l in lab.dropna().items():
            hits[l] += 1
            recent.append((t, str(ts.date()), l))
    except Exception as exc:  # noqa: BLE001
        hits["ERR " + type(exc).__name__ + ": " + str(exc)[:60]] += 1
print("DIAG setup hits in last 15 daily bars:", dict(hits))
print("DIAG recent:", sorted(recent, key=lambda r: r[1])[-20:])
try:
    from triggers import db
    print("DIAG deactivated (raw):", db.get_deactivated())
    from triggers.scan import effective_deactivated
    print("DIAG deactivated (effective):", effective_deactivated())
except Exception as exc:  # noqa: BLE001
    print("DIAG deactivated check failed:", exc)
try:
    from backtesting.crypto_validation import validated_labels
    print("DIAG validated labels:", validated_labels())
except Exception as exc:  # noqa: BLE001
    print("DIAG validation failed:", exc)
