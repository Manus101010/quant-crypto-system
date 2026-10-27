"""Phase 0 helper: export fact packs + prompts for a manual test in a Claude Project.

    python -m desk.agents.export            # currently armed triggers (up to 10)
    python -m desk.agents.export SOL:long BTC:short

Writes paper_trades/desk/phase0/: PROMPTS.md (paste into Project instructions or
files) and one <SYMBOL>_<dir>.json fact pack per setup (paste one per chat).
No API calls, no cost.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from desk.agents import factpack
from desk.agents.run import ANALYSTS, prompt

OUT = Path(__file__).resolve().parents[2] / "paper_trades" / "desk" / "phase0"
ORDER = list(ANALYSTS) + ["bull", "bear", "trader", "risk", "pm", "position_review"]


def write_prompts() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = ["# Desk prompts for a manual Claude Project test\n",
             "How to use: paste one fact pack JSON per chat, then ask each role in order: "
             "the 4 analysts, then bull and bear (each without seeing the other), then trader, "
             "risk and PM. Note where the debate reads well or where numbers look invented.\n"]
    for role in ORDER:
        parts.append(f"\n## {role}\n\n```\n{prompt(role)}\n```\n")
    p = OUT / "PROMPTS.md"
    p.write_text("".join(parts))
    return p


def main(argv: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    if argv:
        for a in argv:
            sym, _, d = a.partition(":")
            jobs.append({"symbol": sym, "direction": d or "long"})
    else:
        from triggers import db
        jobs = [{"symbol": t["symbol"], "direction": t.get("direction") or "long", "entry": t.get("entry"),
                 "stop": t.get("stop"), "target": t.get("target"), "setup_label": t.get("setup_label"),
                 "trigger_id": t["id"]} for t in db.get_triggers("active")[:10]]
    print("prompts:", write_prompts())
    for j in jobs:
        pack = factpack.build(j.pop("symbol"), j.pop("direction"), **j)
        name = f"{pack['meta']['symbol']}_{pack['meta']['direction']}.json"
        (OUT / name).write_text(json.dumps(pack, indent=1, default=str))
        print("fact pack:", OUT / name, "missing:", pack["missing"])


if __name__ == "__main__":
    main(sys.argv[1:])
