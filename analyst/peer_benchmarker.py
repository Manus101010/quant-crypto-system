"""
Peer benchmarking: fetch fundamentals for sector peers and
compute percentile ranks for the target ticker.
"""
from __future__ import annotations
import numpy as np
from config import PEER_GROUPS
from utils.logger import get_logger

log = get_logger(__name__)

_METRICS = [
    "gross_margin", "operating_margin", "net_margin",
    "cfo_ni_ratio", "debt_equity",
]


def get_peer_group(sector: str) -> list[str]:
    return PEER_GROUPS.get(sector, [])


def benchmark(target_data: dict, n_peers: int = 5) -> dict:
    """
    Returns dict of {metric: {value, peer_median, peer_mean, percentile_rank}}.
    """
    from analyst.data_fetcher import fetch

    sector = target_data.get("sector", "Unknown")
    peers = [p for p in get_peer_group(sector) if p != target_data["ticker"]][:n_peers]

    if not peers:
        return {"peer_group": [], "rankings": {}}

    peer_data: list[dict] = []
    for p in peers:
        try:
            pd_ = fetch(p)
            peer_data.append(pd_)
        except Exception as exc:
            log.warning("Peer fetch failed %s: %s", p, exc)

    if not peer_data:
        return {"peer_group": peers, "rankings": {}}

    rankings: dict[str, dict] = {}
    ttm_target = target_data.get("ttm", {})

    for metric in _METRICS:
        target_val = ttm_target.get(metric)
        peer_vals = [
            p["ttm"].get(metric) for p in peer_data
            if p.get("ttm", {}).get(metric) is not None
        ]
        peer_vals = [v for v in peer_vals if v is not None]

        if not peer_vals or target_val is None:
            rankings[metric] = {
                "value": target_val,
                "peer_median": None,
                "peer_mean": None,
                "percentile_rank": None,
            }
            continue

        all_vals = peer_vals + [target_val]
        pct_rank = float(np.sum(np.array(peer_vals) < target_val) / len(peer_vals) * 100)

        # For debt_equity, lower is better — invert
        if metric == "debt_equity":
            pct_rank = 100.0 - pct_rank

        rankings[metric] = {
            "value": target_val,
            "peer_median": float(np.median(peer_vals)),
            "peer_mean": float(np.mean(peer_vals)),
            "percentile_rank": round(pct_rank, 1),
        }

    return {
        "peer_group": peers,
        "sector": sector,
        "rankings": rankings,
    }
