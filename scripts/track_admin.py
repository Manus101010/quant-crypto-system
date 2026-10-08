"""
Track record admin, run by .github/workflows/track-admin.yml (needs the Supabase
secrets, which only GitHub Actions has).

  python scripts/track_admin.py export   → writes track_export.json: every trigger
                                            row plus the current tracking start
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
    rows = []
    for st in ("active", "fired", "expired", "cancelled", "invalidated"):
        rows += tdb.get_triggers(st, limit=100000)
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


if __name__ == "__main__":
    {"export": export, "reset": reset}[sys.argv[1]]()
