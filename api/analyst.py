from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from api import log_store as L

router = APIRouter()

_last_results: list[dict] = []


@router.get("/analyze/stream")
async def analyze_stream(tickers: str, force: bool = False):
    """SSE stream — yields progress events then final blended results."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    async def generator():
        from analyst.data_fetcher import fetch
        from analyst.peer_benchmarker import benchmark
        from analyst.analyzer import analyze
        from analyst.blender import blend_scores, compute_quant_score

        L.info(f"Analyst pipeline started for {', '.join(ticker_list)}")
        raw = []

        for ticker in ticker_list:
            try:
                yield _sse({"status": "fetching", "ticker": ticker, "step": "fundamentals"})
                L.info(f"Fetching fundamentals: {ticker}")
                fund = await asyncio.to_thread(fetch, ticker, force)

                yield _sse({"status": "fetching", "ticker": ticker, "step": "peers"})
                peer = await asyncio.to_thread(benchmark, fund)

                yield _sse({"status": "fetching", "ticker": ticker, "step": "claude"})
                L.info(f"Sending {ticker} to Claude…")
                claude_res = await asyncio.to_thread(analyze, ticker, fund, peer, force)
                quant = compute_quant_score(fund)

                raw.append({
                    "ticker": ticker,
                    "name": fund.get("name", ticker),
                    "sector": fund.get("sector", "Unknown"),
                    "quant_score": quant,
                    "claude_result": claude_res,
                    "fundamentals": fund,
                    "peer": peer,
                })
                L.ok(f"✓ {ticker} analyzed — composite={claude_res.get('composite_score', '?')}")
                yield _sse({"status": "done", "ticker": ticker})

            except Exception as exc:
                L.err(f"Analyst error {ticker}: {exc}")
                yield _sse({"status": "error", "ticker": ticker, "error": str(exc)})

        global _last_results
        # Inject prev_rank from last run so deltas are meaningful
        prev_rank_map = {c["ticker"]: c["rank"] for c in _last_results if "rank" in c}
        for item in raw:
            if item["ticker"] in prev_rank_map:
                item["prev_rank"] = prev_rank_map[item["ticker"]]

        blended = blend_scores(raw)
        _last_results = blended
        L.ok(f"Analyst complete — {len(blended)} tickers ranked")
        yield _sse({"status": "complete", "results": blended})

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/latest")
async def latest_results():
    return {"candidates": _last_results}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"
