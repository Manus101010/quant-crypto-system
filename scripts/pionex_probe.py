"""Does Pionex's public futures API answer from a US GitHub runner? Read only."""
import json
import urllib.request

B = "https://api.pionex.com/api/v1"
for path in ("/common/symbols?type=PERP", "/market/tickers?type=PERP",
             "/market/klines?symbol=BTC_USDT_PERP&interval=1D&limit=500"):
    try:
        with urllib.request.urlopen(B + path, timeout=20) as r:
            d = json.load(r)
        data = d.get("data") or {}
        n = len(data.get("symbols") or data.get("tickers") or data.get("klines") or [])
        print("PIONEX", path, "HTTP", r.status, "result", d.get("result"), "items", n)
    except Exception as exc:  # noqa: BLE001
        print("PIONEX", path, "FAILED", type(exc).__name__, str(exc)[:200])
