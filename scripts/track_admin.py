"""
Track record admin, run by .github/workflows/track-admin.yml (needs the Supabase
secrets, which only GitHub Actions has).

  python scripts/track_admin.py export   → writes track_export.json: every trigger
                                            row plus the current tracking start
  python scripts/track_admin.py scan     → runs a full scan and arm right now,
                                            exactly like the scheduled ones (Telegram
                                            summary included)
  python scripts/track_admin.py reset    → starts a new tracking period NOW.
                                            Nothing is deleted: older signals stay
                                            in the database as history and are just
                                            left out of the live record.
"""
from __future__ import annotations
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from triggers import db as tdb  # noqa: E402


def export(path: str = "track_export.json") -> None:
    # Every row, whatever its status (too_extended etc. included): it is a backup.
    rows = tdb.get_triggers(None, limit=10_000_000)
    seen, uniq = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    out = {"exported_at": datetime.datetime.utcnow().isoformat(),
           "track_from": tdb.get_state("track_from"), "triggers": uniq}
    Path(path).write_text(json.dumps(out, default=str))
    print(f"exported {len(uniq)} triggers to {path}")


def reset() -> None:
    now = datetime.datetime.utcnow().isoformat()
    prev = tdb.get_state("track_from")
    tdb.set_state("track_from", now)
    print(f"tracking period reset: {prev} -> {now}")


def scan() -> None:
    from triggers.autoscan import run_scan
    res = run_scan("manual")
    print(f"scan done: {res.get('actionable', 0)} valid, {len(res.get('armed') or [])} armed")
    from collections import Counter
    print("candidates by setup and status:")
    for (lab, st, d), n in Counter((c.get("setup_label"), c.get("_status"), c.get("direction"))
                                   for c in res.get("candidates") or []).most_common():
        print(f"  {n:3d}  {d:5s} {lab}  [{st}]")
    print("long gate blocked:", res.get("btc_below_200d"), res.get("long_gate_reason"))
    print("skipped wide stop:", res.get("wide_stop_excluded"))
    for a in res.get("armed") or []:
        print(" ", a["direction"], a["symbol"], a["setup_label"], a.get("stop_pct"))


if __name__ == "__main__":
    {"export": export, "reset": reset, "scan": scan}[sys.argv[1]]()
