from __future__ import annotations
import asyncio
from fastapi import APIRouter
from api import log_store as L

router = APIRouter()

_SAMPLE_ROW = {
    "ticker": "BTC-USD",
    "setup_label": "Pullback to 50-SMA",
    "conviction": 87,
    "vol_usd_m": 1234.5,
    "trade": {
        "action": "BUY",
        "entry":  "$64,200",
        "target": "$71,500",
        "stop":   "$61,800",
        "rr":     "3.0:1",
    },
}


@router.post("/test")
async def test_webhook():
    """Send a sample setup alert so the user can verify their webhook config."""
    from utils import webhooks
    from utils.webhooks import _cfg
    url, fmt, secret = _cfg()
    L.info(f"Webhook test: format={fmt} signed={'yes' if secret else 'no'} "
           f"url={'set' if url else 'UNSET'}")
    try:
        delivered = await asyncio.to_thread(webhooks.send_setup_alert, _SAMPLE_ROW)
        if delivered:
            L.ok("WEBHOOK TEST — sample alert delivered")
        else:
            L.info("WEBHOOK TEST — no-op (URL unset, deduped, or non-2xx); check logs")
        return {
            "delivered": delivered,
            "format": fmt,
            "url_configured": bool(url),
            "signed": bool(secret),
        }
    except Exception as exc:
        L.err(f"Webhook test error: {exc}")
        raise
