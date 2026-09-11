from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from journal.db import add_entry, get_entries, delete_entry, update_entry

router = APIRouter()


class EntryIn(BaseModel):
    entry_type: str
    ticker: str | None = None
    direction: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    size_pct: float | None = None
    tags: str | None = None
    deploy_score: float | None = None
    regime: str | None = None
    rationale: str | None = None
    outcome: str | None = None


@router.get("/entries")
def list_entries(entry_type: str | None = None, ticker: str | None = None, limit: int = 100):
    return {"entries": get_entries(entry_type=entry_type, ticker=ticker, limit=limit)}


@router.post("/entries")
def create_entry(body: EntryIn):
    pnl = None
    if body.entry_price and body.exit_price and body.entry_price > 0:
        pnl = (body.exit_price - body.entry_price) / body.entry_price * 100
        if body.direction == "short":
            pnl = -pnl
    eid = add_entry(
        entry_type=body.entry_type,
        ticker=body.ticker,
        direction=body.direction,
        entry_price=body.entry_price,
        exit_price=body.exit_price,
        size_pct=body.size_pct,
        pnl_pct=pnl,
        tags=body.tags,
        deploy_score=body.deploy_score,
        regime=body.regime,
        rationale=body.rationale,
        outcome=body.outcome,
    )
    return {"id": eid}


@router.delete("/entries/{entry_id}")
def remove_entry(entry_id: int):
    delete_entry(entry_id)
    return {"ok": True}


@router.get("/stats")
def journal_stats():
    entries = get_entries(entry_type="trade", limit=500)
    pnls = [e["pnl_pct"] for e in entries if e.get("pnl_pct") is not None]
    wins = [p for p in pnls if p > 0]
    return {
        "total_trades": len(pnls),
        "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
        "total_pnl": round(sum(pnls), 2) if pnls else 0,
    }
