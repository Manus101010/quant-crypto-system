"""Entry points used by the monitor and Telegram: review a fired signal in the
background, review a symbol on demand, review open positions."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from utils.logger import get_logger

log = get_logger(__name__)
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desk")


def enabled() -> bool:
    try:
        from config import DESK_ENABLED, ANTHROPIC_API_KEY
        return bool(DESK_ENABLED and ANTHROPIC_API_KEY)
    except Exception:                                 # noqa: BLE001
        return False


def review(symbol: str, direction: str, *, entry=None, stop=None, target=None,
           setup_label=None, trigger_id=None, llm=None, send: bool = True) -> dict:
    from desk.agents import factpack, run, report, store
    pack = factpack.build(symbol, direction, entry=entry, stop=stop, target=target,
                          setup_label=setup_label, trigger_id=trigger_id)
    res = run.run(pack, llm=llm)
    res["report"] = report.write_html(res, pack)
    if trigger_id is not None:
        try:
            store.save(trigger_id, res)
        except Exception as exc:                      # noqa: BLE001
            log.debug("desk save failed: %s", exc)
    if send:
        from utils import telegram
        telegram.send_message(report.telegram_text(res))
    return res


def review_trigger_async(t: dict, price: float) -> None:
    """Queue a desk review for a fired trigger. Never blocks or raises."""
    if not enabled():
        return
    try:
        _pool.submit(_safe_review, t, price)
    except Exception as exc:                          # noqa: BLE001
        log.debug("desk queue failed: %s", exc)


def _safe_review(t: dict, price: float) -> None:
    try:
        review(t["symbol"], t.get("direction") or "long", entry=price, stop=t.get("stop"),
               target=t.get("target"), setup_label=t.get("setup_label"), trigger_id=t["id"])
    except Exception as exc:                          # noqa: BLE001
        log.warning("desk review failed for #%s: %s", t.get("id"), exc)
