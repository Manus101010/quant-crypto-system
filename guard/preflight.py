"""
Pre-trade guard: pure functions that ACCEPT or REJECT a proposed Bybit trade
against Manus's hard rules, listing every failed rule with a concrete fix.

Rules (defaults from config where present):
  * margin >= $50 (POSITION_MARGIN_USD)
  * a stop exists and sits on the correct side; for a futures grid Bybit only
    accepts a stop BEYOND the range edge (short: stop >= range top; long: stop <= range bottom)
  * loss at the stop <= 25% of margin (MAX_LOSS_PCT_OF_MARGIN); grids use the
    fully filled worst case (every rung filled on the way to the stop)
  * liquidation at least 2x further from entry than the stop
  * grids: leverage >= 3
  * open risk (other open stops + this one) <= $125 (MAX_PORTFOLIO_RISK_USD)
  * daily realised loss cap $125 (25% of sleeve): shut once hit, and this stop
    may not push the day past it
  * optional $ cap (`max_loss_usd`): the ledger sets it to 1R after a stop out

Model (isolated margin, matches desk/gridplan.py's worst case):
  Arithmetic grid with N cells between lo and hi (N+1 lines, equal qty per cell).
  Short grid: cells below the launch price are opened at launch (at the entry
  price); cells above fill at their sell line as price rises. Long grid mirrors.
  Liquidation of a position (qty Q, avg entry A, margin M, maintenance rate m):
     short: M - Q(P - A) = m Q P   ->  P = (M + Q A) / (Q (1 + m))
     long:  M - Q(A - P) = m Q P   ->  P = (Q A - M) / (Q (1 - m))
  Quantity per cell = deploy_ratio x (investment x leverage) / sum(cell fill prices).
  deploy_ratio = 1 is conservative (Bybit holds part of the investment back, so its
  real cells are usually smaller); infer_deploy_ratio() calibrates it from a live bot.
  The maintenance RATE (`mmr`) is per instrument tier; implied_mmr() calibrates it
  from the app's own liquidation price. NOTE: the "MMR %" Bybit shows on a running
  bot is the account maintenance margin RATIO (MM / equity), not this rate.

Signal only: nothing here places or modifies orders.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

try:                                            # config is optional for pure use
    import config as _cfg
except Exception:                               # noqa: BLE001
    _cfg = None

ACCEPT, REJECT = "ACCEPT", "REJECT"


def _c(name: str, default):
    return getattr(_cfg, name, default) if _cfg is not None else default


MIN_MARGIN = float(_c("POSITION_MARGIN_USD", 50.0))
MAX_LOSS_PCT = float(_c("MAX_LOSS_PCT_OF_MARGIN", 25.0))
OPEN_RISK_CAP = float(_c("MAX_PORTFOLIO_RISK_USD", 125.0))
DAILY_LOSS_CAP = float(_c("SLEEVE_USD", 500.0)) * 0.25
DEFAULT_MMR = float(_c("GRID_MMR", 0.005))
MIN_GRID_LEVERAGE = 3
LIQ_MULT = 2.0
PLAIN_FEE_PCT = float(_c("SIZING_FEE_PCT", 0.15))    # round trip, % of notional
GRID_CLOSE_FEE_PCT = 0.06                            # taker close of the whole grid position


# ── helpers ────────────────────────────────────────────────────────────────────
def _decimals(tick: float) -> int:
    s = f"{tick:.12f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def round_tick(px: float, tick: float | None, mode: str = "nearest") -> float:
    """Round to the instrument tick. mode: nearest | up | down."""
    if not tick:
        return px
    n = px / tick
    k = math.floor(n + 1e-9) if mode == "down" else math.ceil(n - 1e-9) if mode == "up" else round(n)
    return round(k * tick, _decimals(tick))


@dataclass
class Verdict:
    verdict: str
    failures: list[dict] = field(default_factory=list)   # {rule, detail, fix}
    metrics: dict = field(default_factory=dict)
    suggestion: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == ACCEPT

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "failures": self.failures,
                "metrics": self.metrics, "suggestion": self.suggestion}


def _fail(out: list, rule: str, detail: str, fix: str = "") -> None:
    out.append({"rule": rule, "detail": detail, "fix": fix})


def liq_price(direction: str, qty: float, avg_entry: float, margin: float,
              mmr: float = DEFAULT_MMR) -> float:
    """Isolated liquidation price (fees ignored)."""
    if qty <= 0:
        return 0.0 if direction == "long" else math.inf
    if direction == "short":
        return (margin + qty * avg_entry) / (qty * (1 + mmr))
    return max(0.0, (qty * avg_entry - margin) / (qty * (1 - mmr)))


# ── grid geometry ──────────────────────────────────────────────────────────────
def grid_fill_prices(mode: str, lo: float, hi: float, grids: int, entry: float) -> list[float]:
    """Fill price of each cell in the fully filled worst case."""
    step = (hi - lo) / grids
    lines = [lo + step * i for i in range(grids + 1)]
    if mode == "short":    # each cell sells at its upper line; cells at/below entry open at entry
        return [max(lines[i + 1], entry) if lines[i + 1] > entry else entry for i in range(grids)]
    return [min(lines[i], entry) if lines[i] < entry else entry for i in range(grids)]


def initial_cells(mode: str, lo: float, hi: float, grids: int, entry: float) -> int:
    """Cells opened at launch (short: below entry; long: above entry)."""
    step = (hi - lo) / grids
    if mode == "short":
        return max(0, min(grids, int(math.floor((entry - lo) / step + 1e-9))))
    return max(0, min(grids, int(math.floor((hi - entry) / step + 1e-9))))


def infer_qty_per_grid(mode: str, lo: float, hi: float, grids: int, mark: float,
                       position_qty: float) -> float | None:
    """Qty per cell from a live bot. A grid's position is a function of price (to within
    one cell): a short holds every cell below the mark, a long every cell above it."""
    n = initial_cells(mode, lo, hi, grids, mark)
    return abs(position_qty) / n if n else None


def infer_deploy_ratio(mode: str, lo: float, hi: float, grids: int, entry: float,
                       investment: float, leverage: float, position_qty: float,
                       mark: float | None = None) -> float | None:
    """Live qty per cell / naive (investment x leverage / sum of fills). Bybit keeps part
    of the investment as margin, so this is usually < 1. Carry it into relaunch maths."""
    q = infer_qty_per_grid(mode, lo, hi, grids, mark or entry, position_qty)
    if not q:
        return None
    naive = investment * leverage / sum(grid_fill_prices(mode, lo, hi, grids, entry))
    return q / naive


def implied_mmr(direction: str, qty: float, avg_entry: float, margin: float, liq: float) -> float:
    """Maintenance rate that reproduces the exchange's own liquidation price
    (absorbs fees/margin details we don't model). Inverse of liq_price()."""
    if direction == "short":
        return (margin + qty * avg_entry) / (qty * liq) - 1
    return 1 - (qty * avg_entry - margin) / (qty * liq)


def grid_worst_case(mode: str, lo: float, hi: float, grids: int, entry: float,
                    investment: float, leverage: float, stop: float,
                    qty_per_grid: float | None = None, mmr: float = DEFAULT_MMR,
                    fee_pct: float = GRID_CLOSE_FEE_PCT, deploy_ratio: float = 1.0) -> dict:
    """Fully filled position, its loss at `stop`, and its liquidation price."""
    fills = grid_fill_prices(mode, lo, hi, grids, entry)
    if qty_per_grid is None:
        qty_per_grid = deploy_ratio * investment * leverage / sum(fills)
    q = qty_per_grid
    Q = q * grids
    avg = sum(fills) / grids
    if mode == "short":
        loss = q * sum(stop - c for c in fills)
    else:
        loss = q * sum(c - stop for c in fills)
    loss += Q * stop * fee_pct / 100
    liq = liq_price(mode, Q, avg, investment, mmr)
    return {"qty_per_grid": q, "qty_full": Q, "avg_entry": avg, "notional_full": Q * avg,
            "loss_at_stop": loss, "liq_full": liq, "effective_leverage": Q * avg / investment}


# ── grid preflight ─────────────────────────────────────────────────────────────
def check_grid(mode: str, lo: float, hi: float, grids: int, leverage: float,
               investment: float, stop: float | None, entry: float, *,
               deploy_ratio: float = 1.0, mmr: float = DEFAULT_MMR,
               tick: float | None = None, open_risk_usd: float = 0.0,
               daily_realised_pnl: float = 0.0, max_loss_usd: float | None = None,
               stop_buffer_pct: float = 0.5, live_liq: float | None = None) -> Verdict:
    """Evaluate a Bybit futures grid. `entry` = launch price (current price for a new bot).
    `deploy_ratio` (infer_deploy_ratio on a live bot) scales qty per cell to what Bybit really
    deployed; `mmr` should be the exchange's maintenance RATE (implied_mmr calibrates it).
    `live_liq` (the app's liq for the CURRENT position) is reported alongside, not used for rules."""
    mode = mode.lower()
    f: list[dict] = []
    m: dict = {"type": "grid", "mode": mode, "lo": lo, "hi": hi, "grids": grids,
               "leverage": leverage, "investment": investment, "entry": entry, "stop": stop}
    if mode not in ("short", "long"):
        return Verdict(REJECT, [{"rule": "mode", "detail": f"mode {mode!r}", "fix": "short or long"}], m)
    if not (0 < lo < hi) or grids < 2:
        return Verdict(REJECT, [{"rule": "range", "detail": "need 0 < lo < hi and grids >= 2",
                                 "fix": ""}], m)
    short = mode == "short"
    pct_cap = investment * MAX_LOSS_PCT / 100
    loss_cap = min(pct_cap, max_loss_usd) if max_loss_usd is not None else pct_cap
    m["loss_cap_usd"] = round(loss_cap, 2)

    if investment < MIN_MARGIN:
        _fail(f, "min_margin", f"investment ${investment:.2f} < ${MIN_MARGIN:.0f}",
              f"invest at least ${MIN_MARGIN:.0f}")
    if leverage < MIN_GRID_LEVERAGE:
        _fail(f, "min_grid_leverage", f"{leverage:g}x < {MIN_GRID_LEVERAGE}x",
              f"use at least {MIN_GRID_LEVERAGE}x")
    if realised_loss := max(0.0, -daily_realised_pnl):
        m["daily_realised_loss"] = round(realised_loss, 2)
    if realised_loss >= DAILY_LOSS_CAP:
        _fail(f, "daily_loss_cap", f"realised loss today ${realised_loss:.2f} >= ${DAILY_LOSS_CAP:.0f}",
              "guard is shut until the Sydney day rolls over")

    # Stop: required, and Bybit only takes it beyond the range edge.
    eval_stop = stop
    if stop is None or stop <= 0:
        suggested = (round_tick(hi * (1 + stop_buffer_pct / 100), tick, "up") if short
                     else round_tick(lo * (1 - stop_buffer_pct / 100), tick, "down"))
        _fail(f, "no_stop", "grid has no stop loss",
              f"set SL {'>=' if short else '<='} {'range top' if short else 'range bottom'}, "
              f"e.g. {suggested:g}")
        eval_stop = suggested                    # measure the risk as if stopped just past the edge
    elif short and stop < hi:
        _fail(f, "stop_inside_range", f"short grid SL {stop:g} < range top {hi:g} (Bybit rejects it)",
              f"SL >= {hi:g}")
    elif not short and stop > lo:
        _fail(f, "stop_inside_range", f"long grid SL {stop:g} > range bottom {lo:g} (Bybit rejects it)",
              f"SL <= {lo:g}")
    m["eval_stop"] = eval_stop

    wc = grid_worst_case(mode, lo, hi, grids, entry, investment, leverage, eval_stop,
                         deploy_ratio=deploy_ratio, mmr=mmr)
    loss = wc["loss_at_stop"]
    stop_dist = abs(eval_stop - entry) / entry
    liq = wc["liq_full"]
    liq_dist = abs(liq - entry) / entry if math.isfinite(liq) else math.inf
    m.update({"loss_at_stop": round(loss, 2), "loss_pct_margin": round(loss / investment * 100, 2),
              "stop_dist_pct": round(stop_dist * 100, 2), "liq_full": liq,
              "liq_dist_pct": round(liq_dist * 100, 2),
              "liq_over_stop": round(liq_dist / stop_dist, 2) if stop_dist else None,
              "deploy_ratio": deploy_ratio, "qty_per_grid": wc["qty_per_grid"], "qty_full": wc["qty_full"],
              "avg_entry_full": wc["avg_entry"], "effective_leverage": round(wc["effective_leverage"], 2)})
    if live_liq:
        m["live_liq"] = live_liq
        m["live_liq_dist_pct"] = round(abs(live_liq - entry) / entry * 100, 2)

    sugg: dict = {}
    if loss > loss_cap + 1e-9:
        top = max_range_edge(mode, lo, hi, grids, leverage, investment, entry, loss_cap,
                             deploy_ratio=deploy_ratio, mmr=mmr, tick=tick,
                             stop_buffer_pct=stop_buffer_pct)
        lev = max_grid_leverage(mode, lo, hi, grids, leverage, investment, entry, eval_stop,
                                loss_cap, deploy_ratio=deploy_ratio, mmr=mmr)
        fixes = []
        if top:
            sugg["range_edge"] = top
            fixes.append(f"{'range top' if short else 'range bottom'} {top['edge']:g} with SL "
                         f"{top['stop']:g} (loss ${top['loss']:.2f})")
        if lev >= MIN_GRID_LEVERAGE:
            sugg["max_leverage"] = lev
            fixes.append(f"leverage {lev}x")
        else:
            fixes.append(f"leverage cannot fix it (max {lev}x < {MIN_GRID_LEVERAGE}x)")
        why = (f"${loss:.2f} = {loss / investment * 100:.1f}% of ${investment:.2f}"
               + (f" (> 1R lock ${max_loss_usd:.2f})" if max_loss_usd is not None and loss_cap == max_loss_usd
                  else f" (> {MAX_LOSS_PCT:.0f}% = ${pct_cap:.2f})"))
        _fail(f, "loss_cap", why, "; or ".join(fixes))
    if liq_dist < LIQ_MULT * stop_dist:
        lev2 = max_grid_leverage(mode, lo, hi, grids, leverage, investment, entry, eval_stop,
                                 math.inf, deploy_ratio=deploy_ratio, mmr=mmr)
        _fail(f, "liq_distance", f"fully filled liq {liq:g} is {liq_dist * 100:.1f}% away vs stop "
              f"{stop_dist * 100:.1f}% (need >= {LIQ_MULT:g}x)",
              f"max leverage {lev2}x at this range, or tighten the range edge")
    if open_risk_usd + loss > OPEN_RISK_CAP + 1e-9:
        _fail(f, "open_risk_cap", f"open risk ${open_risk_usd:.2f} + ${loss:.2f} > ${OPEN_RISK_CAP:.0f}",
              f"this stop may lose at most ${max(0.0, OPEN_RISK_CAP - open_risk_usd):.2f}")
    if realised_loss < DAILY_LOSS_CAP and realised_loss + loss > DAILY_LOSS_CAP + 1e-9:
        _fail(f, "daily_loss_room", f"realised ${realised_loss:.2f} + stop ${loss:.2f} > ${DAILY_LOSS_CAP:.0f}",
              f"this stop may lose at most ${DAILY_LOSS_CAP - realised_loss:.2f} today")
    return Verdict(REJECT if f else ACCEPT, f, m, sugg)


def max_grid_leverage(mode, lo, hi, grids, leverage, investment, entry, stop, loss_cap, *,
                      deploy_ratio=1.0, mmr=DEFAULT_MMR, cap: int = 50) -> int:
    """Highest integer leverage meeting the loss cap and the 2x liq rule."""
    stop_dist = abs(stop - entry) / entry
    for L in range(cap, 0, -1):
        wc = grid_worst_case(mode, lo, hi, grids, entry, investment, L, stop,
                             deploy_ratio=deploy_ratio, mmr=mmr)
        ld = abs(wc["liq_full"] - entry) / entry if math.isfinite(wc["liq_full"]) else math.inf
        if wc["loss_at_stop"] <= loss_cap + 1e-9 and ld >= LIQ_MULT * stop_dist:
            return L
    return 0


def max_range_edge(mode, lo, hi, grids, leverage, investment, entry, loss_cap, *,
                   deploy_ratio=1.0, mmr=DEFAULT_MMR, tick=None, stop_buffer_pct=0.5) -> dict | None:
    """Furthest range top (short) / bottom (long) whose stop just beyond the edge
    loses <= loss_cap and keeps liq >= 2x the stop distance. Keeps lo/hi on the
    other side, grid count, leverage, investment (a relaunch: Bybit re-sizes each
    cell from investment x leverage, scaled by deploy_ratio)."""
    short = mode == "short"

    def stop_for(edge: float) -> float:
        return (round_tick(edge * (1 + stop_buffer_pct / 100), tick, "up") if short
                else round_tick(edge * (1 - stop_buffer_pct / 100), tick, "down"))

    def ok(edge: float) -> tuple[bool, float]:
        a, b = (lo, edge) if short else (edge, hi)
        if b <= a:
            return False, 0.0
        s = stop_for(edge)
        wc = grid_worst_case(mode, a, b, grids, entry, investment, leverage, s,
                             deploy_ratio=deploy_ratio, mmr=mmr)
        sd = abs(s - entry) / entry
        ld = abs(wc["liq_full"] - entry) / entry if math.isfinite(wc["liq_full"]) else math.inf
        return wc["loss_at_stop"] <= loss_cap + 1e-9 and ld >= LIQ_MULT * sd, wc["loss_at_stop"]

    # Edge must stay beyond entry; search between entry and the original edge.
    near, far = (entry, hi) if short else (entry, lo)
    if ok(far)[0]:
        e = far
    else:
        good, bad = near, far
        if not ok(near * (1.0001 if short else 0.9999))[0]:
            return None
        for _ in range(80):
            mid = (good + bad) / 2
            good, bad = (mid, bad) if ok(mid)[0] else (good, mid)
        e = good
    e = round_tick(e, tick, "down" if short else "up")
    while tick and not ok(e)[0]:
        e = round_tick(e - tick if short else e + tick, tick)
        if (short and e <= entry) or (not short and e >= entry):
            return None
    return {"edge": e, "stop": stop_for(e), "loss": ok(e)[1]}


# ── plain position preflight ───────────────────────────────────────────────────
def check_plain(direction: str, entry: float, stop: float | None, leverage: float,
                margin: float, *, mmr: float = DEFAULT_MMR, tick: float | None = None,
                fee_pct: float = PLAIN_FEE_PCT, open_risk_usd: float = 0.0,
                daily_realised_pnl: float = 0.0, max_loss_usd: float | None = None) -> Verdict:
    direction = direction.lower()
    f: list[dict] = []
    short = direction == "short"
    m: dict = {"type": "plain", "direction": direction, "entry": entry, "stop": stop,
               "leverage": leverage, "margin": margin}
    pct_cap = margin * MAX_LOSS_PCT / 100
    loss_cap = min(pct_cap, max_loss_usd) if max_loss_usd is not None else pct_cap
    m["loss_cap_usd"] = round(loss_cap, 2)
    if margin < MIN_MARGIN:
        _fail(f, "min_margin", f"margin ${margin:.2f} < ${MIN_MARGIN:.0f}", f"use at least ${MIN_MARGIN:.0f}")
    realised_loss = max(0.0, -daily_realised_pnl)
    if realised_loss >= DAILY_LOSS_CAP:
        _fail(f, "daily_loss_cap", f"realised loss today ${realised_loss:.2f} >= ${DAILY_LOSS_CAP:.0f}",
              "guard is shut until the Sydney day rolls over")
    notional = margin * leverage
    qty = notional / entry
    liq = liq_price(direction, qty, entry, margin, mmr)
    m.update({"notional": notional, "qty": qty, "liq": liq,
              "liq_dist_pct": round(abs(liq - entry) / entry * 100, 2)})
    if stop is None or stop <= 0:
        _fail(f, "no_stop", "position has no stop loss",
              "set a stop; max distance for 25% of margin = "
              f"{(MAX_LOSS_PCT / 100 / leverage - fee_pct / 100) * 100:.2f}%")
        return Verdict(REJECT, f, m)
    if (short and stop <= entry) or (not short and stop >= entry):
        _fail(f, "stop_side", f"{direction} stop {stop:g} is on the wrong side of entry {entry:g}", "")
        return Verdict(REJECT, f, m)
    sd = abs(stop - entry) / entry
    loss = notional * (sd + fee_pct / 100)
    ld = abs(liq - entry) / entry
    m.update({"stop_dist_pct": round(sd * 100, 3), "loss_at_stop": round(loss, 2),
              "loss_pct_margin": round(loss / margin * 100, 2),
              "liq_over_stop": round(ld / sd, 2)})
    sugg: dict = {}
    if loss > loss_cap + 1e-9:
        L = max_plain_leverage(direction, entry, stop, margin, loss_cap, mmr=mmr, fee_pct=fee_pct)
        far = loss_cap / notional - fee_pct / 100
        tight = (round_tick(entry * (1 + far), tick, "down") if short
                 else round_tick(entry * (1 - far), tick, "up")) if far > 0 else None
        sugg.update({"max_leverage": L, "tightest_ok_stop": tight})
        _fail(f, "loss_cap", f"${loss:.2f} = {loss / margin * 100:.1f}% of margin > ${loss_cap:.2f}",
              (f"leverage <= {L}x" if L >= 1 else "even 1x is too much: widen nothing, skip")
              + (f", or stop at {tight:g} at {leverage:g}x" if tight else ""))
    if ld < LIQ_MULT * sd:
        L2 = max_plain_leverage(direction, entry, stop, margin, math.inf, mmr=mmr, fee_pct=fee_pct)
        _fail(f, "liq_distance", f"liq {liq:g} is {ld * 100:.1f}% away vs stop {sd * 100:.1f}% "
              f"(need >= {LIQ_MULT:g}x)", f"leverage <= {L2}x")
    if open_risk_usd + loss > OPEN_RISK_CAP + 1e-9:
        _fail(f, "open_risk_cap", f"open risk ${open_risk_usd:.2f} + ${loss:.2f} > ${OPEN_RISK_CAP:.0f}",
              f"this stop may lose at most ${max(0.0, OPEN_RISK_CAP - open_risk_usd):.2f}")
    if realised_loss < DAILY_LOSS_CAP and realised_loss + loss > DAILY_LOSS_CAP + 1e-9:
        _fail(f, "daily_loss_room", f"realised ${realised_loss:.2f} + stop ${loss:.2f} > ${DAILY_LOSS_CAP:.0f}",
              f"this stop may lose at most ${DAILY_LOSS_CAP - realised_loss:.2f} today")
    return Verdict(REJECT if f else ACCEPT, f, m, sugg)


def max_plain_leverage(direction, entry, stop, margin, loss_cap, *, mmr=DEFAULT_MMR,
                       fee_pct=PLAIN_FEE_PCT, cap: int = 100) -> int:
    sd = abs(stop - entry) / entry
    for L in range(cap, 0, -1):
        notional = margin * L
        liq = liq_price(direction, notional / entry, entry, margin, mmr)
        if (notional * (sd + fee_pct / 100) <= loss_cap + 1e-9
                and abs(liq - entry) / entry >= LIQ_MULT * sd):
            return L
    return 0


# ── proposal (wraps desk/gridplan) ─────────────────────────────────────────────
def propose_grid(direction: str, price: float, atr: float, *, stop: float | None = None,
                 target: float | None = None, investment: float = MIN_MARGIN,
                 tick: float | None = None, mmr: float = DEFAULT_MMR,
                 max_loss_usd: float | None = None, open_risk_usd: float = 0.0,
                 daily_realised_pnl: float = 0.0) -> dict:
    """Compliant Bybit futures grid for a signal: gridplan picks range/grids/leverage,
    then prices are snapped to tick and the result is re-checked by check_grid.
    Default stop = 2.5 ATR beyond price. Returns {ok, plan, verdict}."""
    from desk.gridplan import grid_for_signal
    short = direction == "short"
    if stop is None:
        stop = price + 2.5 * atr if short else price - 2.5 * atr
    cap = investment * MAX_LOSS_PCT / 100
    risk = min(cap, max_loss_usd) if max_loss_usd is not None else cap
    g = grid_for_signal(direction, price, stop, target, atr, risk, margin_usd=investment,
                        max_loss_pct=MAX_LOSS_PCT)
    if not g.get("ok"):
        return {"ok": False, "note": g.get("note"), "plan": g}
    lo = round_tick(g["lower"], tick, "up")
    hi = round_tick(g["upper"], tick, "down")
    st = round_tick(stop, tick, "down" if short else "up")
    if short and st < hi:
        st = hi
    if not short and st > lo:
        st = lo
    lev = max(int(g["leverage"]), MIN_GRID_LEVERAGE)       # grids: 3x floor
    plan = {"mode": "short" if short else "long", "lo": lo, "hi": hi, "grids": int(g["grids"]),
            "leverage": lev, "investment": round(investment, 2), "stop": st, "entry": price,
            "take_profit": g.get("take_profit")}
    kw = dict(mmr=mmr, tick=tick, open_risk_usd=open_risk_usd,
              daily_realised_pnl=daily_realised_pnl, max_loss_usd=max_loss_usd)

    def run() -> Verdict:
        return check_grid(plan["mode"], plan["lo"], plan["hi"], plan["grids"], plan["leverage"],
                          investment, plan["stop"], price, **kw)

    v = run()
    # Step leverage down (never under 3x) while a risk rule fails ...
    while not v.ok and plan["leverage"] > MIN_GRID_LEVERAGE and any(
            x["rule"] in ("loss_cap", "liq_distance") for x in v.failures):
        plan["leverage"] -= 1
        v = run()
    # ... then pull the stop side range edge in until the worst case fits.
    if not v.ok and any(x["rule"] in ("loss_cap", "liq_distance") for x in v.failures):
        cap_now = v.metrics.get("loss_cap_usd", risk)
        room = min(cap_now, OPEN_RISK_CAP - open_risk_usd,
                   DAILY_LOSS_CAP - max(0.0, -daily_realised_pnl))
        e = max_range_edge(plan["mode"], plan["lo"], plan["hi"], plan["grids"], plan["leverage"],
                           investment, price, room, mmr=mmr, tick=tick,
                           stop_buffer_pct=abs(st / (hi if short else lo) - 1) * 100 or 0.5)
        if e:
            if short:
                plan["hi"] = e["edge"]
            else:
                plan["lo"] = e["edge"]
            plan["stop"] = e["stop"]
            v = run()
    return {"ok": v.ok, "plan": plan, "verdict": v.as_dict()}


# ── text ───────────────────────────────────────────────────────────────────────
def format_verdict(v: Verdict, symbol: str = "") -> str:
    m = v.metrics
    head = ("✅ ACCEPT" if v.ok else "⛔ REJECT") + (f" {symbol}" if symbol else "")
    lines = [f"<b>{head}</b>"]
    if "loss_at_stop" in m:
        lines.append(f"Loss at stop ${m['loss_at_stop']:.2f} ({m['loss_pct_margin']:.1f}% of margin, "
                     f"cap ${m['loss_cap_usd']:.2f})")
    if "liq_over_stop" in m and m.get("liq_over_stop") is not None:
        lines.append(f"Liq {m.get('liq_dist_pct')}% away vs stop {m.get('stop_dist_pct')}% "
                     f"= {m['liq_over_stop']}x (need 2x)")
    for x in v.failures:
        lines.append(f"• {x['rule']}: {x['detail']}" + (f" → {x['fix']}" if x["fix"] else ""))
    return "\n".join(lines)


def parse_guard_command(arg: str) -> dict:
    """Parse '/guard short DOODUSDT grid 0.0016 0.0025 200 5x 263.86 [sl 0.00252] [@0.0021]'
    or '/guard long BTCUSDT 65000 63000 10x 50'. Entry '@price' is optional (the caller
    fills in the live price)."""
    t = arg.replace(",", " ").split()
    if len(t) < 3:
        raise ValueError("usage: /guard short SYMBOL grid LO HI GRIDS 5x INVEST [sl X] [@ENTRY]")
    out: dict = {"direction": t[0].lower(), "symbol": t[1].upper()}
    rest = t[2:]
    entry = None
    stop = None
    clean = []
    i = 0
    while i < len(rest):
        w = rest[i].lower()
        if w.startswith("@"):
            entry = float(w[1:])
        elif w in ("sl", "stop") and i + 1 < len(rest):
            stop = float(rest[i + 1]); i += 1
        else:
            clean.append(w)
        i += 1
    if clean and clean[0] == "grid":
        lo, hi, grids, lev, inv = clean[1:6]
        out.update({"type": "grid", "lo": float(lo), "hi": float(hi), "grids": int(grids),
                    "leverage": float(lev.rstrip("x")), "investment": float(inv), "stop": stop})
    else:
        e, s, lev, mar = clean[:4]
        out.update({"type": "plain", "entry": float(e), "stop": float(s),
                    "leverage": float(lev.rstrip("x")), "margin": float(mar)})
        return out
    out["entry"] = entry
    return out
