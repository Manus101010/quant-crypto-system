"""
Score Blender
60% quantitative composite + 40% Claude fundamental composite.
Re-ranks candidates and flags rank changes of ≥3 positions.
"""
from __future__ import annotations
from config import QUANT_WEIGHT, CLAUDE_WEIGHT
from utils.logger import get_logger

log = get_logger(__name__)

_RANK_FLAG_THRESHOLD = 3


def blend_scores(candidates: list[dict]) -> list[dict]:
    """
    Each candidate dict must have:
      - ticker
      - quant_score (0-100)
      - claude_result (output from analyzer.analyze)

    Returns candidates sorted by blended score with rank metadata.
    """
    scored = []
    for c in candidates:
        quant = float(c.get("quant_score", 50))
        claude_res = c.get("claude_result", {})
        claude_composite = float(claude_res.get("composite_score", 5.0))
        # Normalize Claude composite from 1-10 scale to 0-100
        claude_norm = (claude_composite - 1) / 9 * 100

        blended = QUANT_WEIGHT * quant + CLAUDE_WEIGHT * claude_norm

        scored.append({
            **c,
            "quant_score": round(quant, 1),
            "claude_norm": round(claude_norm, 1),
            "blended_score": round(blended, 1),
            "claude_composite_raw": round(claude_composite, 2),
            "consistency_rating": claude_res.get("consistency_rating", "N/A"),
            "bull_case": claude_res.get("bull_case", ""),
            "bear_case": claude_res.get("bear_case", ""),
            "key_risks": claude_res.get("key_risks", []),
            "reasoning_summary": claude_res.get("reasoning_summary", ""),
            "dimension_scores": claude_res.get("scores", {}),
        })

    # Sort by blended score descending
    scored.sort(key=lambda x: x["blended_score"], reverse=True)

    # Assign ranks and detect rank changes
    for i, c in enumerate(scored):
        c["rank"] = i + 1
        prev_rank = c.get("prev_rank")
        if prev_rank is not None:
            delta = prev_rank - c["rank"]  # positive = improved
            c["rank_delta"] = delta
            c["rank_flag"] = abs(delta) >= _RANK_FLAG_THRESHOLD
        else:
            c["rank_delta"] = 0
            c["rank_flag"] = False

    return scored


def compute_quant_score(fundamentals: dict) -> float:
    """
    Simple rules-based quantitative composite (0-100) from yfinance data.
    Used as the 60% quant leg before Claude analysis.
    """
    score = 50.0
    ttm = fundamentals.get("ttm", {})
    ratios = fundamentals.get("ratios", {})

    # Margin quality (+/- 20 pts)
    gm = ttm.get("gross_margin")
    if gm is not None:
        score += (gm - 0.30) * 50  # >30% gross margin adds pts

    om = ttm.get("operating_margin")
    if om is not None:
        score += (om - 0.10) * 60

    # Cash flow quality (+/- 15 pts)
    cfo_ni = ttm.get("cfo_ni_ratio")
    if cfo_ni is not None:
        if cfo_ni > 1.2:
            score += 10
        elif cfo_ni > 0.8:
            score += 5
        elif cfo_ni < 0.5:
            score -= 10

    # Balance sheet (+/- 10 pts)
    de = ttm.get("debt_equity")
    if de is not None:
        if de < 0.5:
            score += 8
        elif de > 2.0:
            score -= 10

    cr = ratios.get("current_ratio")
    if cr is not None:
        if cr > 2.0:
            score += 5
        elif cr < 1.0:
            score -= 8

    # Growth (+/- 10 pts)
    rev_growth = ratios.get("revenue_growth_yoy")
    if rev_growth is not None:
        score += rev_growth * 20  # 20% growth -> +4 pts

    # AR/Revenue divergence (earnings quality penalty)
    ar_div = ratios.get("ar_rev_divergence")
    if ar_div is not None and ar_div > 0.10:
        score -= 8  # AR growing much faster than revenue = bad

    from numpy import clip
    return float(clip(score, 0, 100))
