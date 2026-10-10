"""Dry-run health check for wherever this runs (use it on the cloud host).

Scans the trading universe exactly like the scheduled scan but with database
writes stubbed out — nothing is armed, cancelled or sent. Prints which venues
are geo-blocked, how many coins returned data, and what WOULD be armed.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import triggers.scan as S  # noqa: E402
from config import AUTO_SCAN_PARAMS as P  # noqa: E402
from utils import exchange as X  # noqa: E402

S.tdb.clear_active = lambda: 0
S.tdb.add_trigger = lambda **k: 0
res = S.run_scan_and_arm(top_n=P["top_n"], expiry_hours=P["expiry_hours"],
                         min_vol_usd_m=P["min_vol_usd_m"], source=P["source"],
                         max_per_setup=max(2, P["top_n"] // 3), max_stop_pct=P["max_stop_pct"])
print("CHECK geo-blocked venues:", sorted(X._geo_blocked) or "none")
print("CHECK valid setups:", res.get("actionable"), "| long gate:", res.get("long_gate_reason") or "open")
print("CHECK statuses:", dict(Counter(r.get("_status") for r in res.get("candidates", []))))
print("CHECK would arm:", [(a["symbol"], a["direction"], a["setup_label"]) for a in res.get("armed", [])])
sys.exit(0 if res.get("actionable", 0) > 0 else 1)
