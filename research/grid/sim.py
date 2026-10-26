"""
Event-driven Bybit USDT-perp futures grid simulator (research only, no orders).

Model of Bybit futures grid semantics (assumptions, see docs/night/grid_backtest.md)
-------------------------------------------------------------------------------
* N grids = N intervals between N+1 price lines L_0 < ... < L_N (arithmetic:
  equal $ step, geometric: equal % step). Every interval ("slot") trades the
  SAME base quantity q.
* The line nearest the start price P0 gets no order (Bybit leaves that gap);
  call its index k0. A pointer k ("last line touched") then moves with price.
* LONG grid: slot i buys at L_i and sells at L_{i+1}. At creation the bot opens,
  at market (taker), the long for every slot above k0 (i >= k0), cost P0, so the
  position is long (N - k) slots: fully long at the bottom, flat at the top.
* SHORT grid: mirror. Slot i sells at L_{i+1} and buys back at L_i; at creation
  it market-shorts every slot below k0 (i < k0): short k slots, flat at bottom.
* NEUTRAL grid: no initial position; slots below k0 act long, slots above act
  short, so the position is long below the start price and short above it.
* q is sized so the notional of all the grid's orders equals investment x
  leverage: for long/short that is the fully filled position (what you hold at
  the stop); for neutral the buy orders below plus the sell orders above share
  it (each open order reserves margin), so one side holds about half.
* Grid fills are maker (0.02%) at the line price; the opening market order,
  the time-cap close, stop-loss and take-profit are taker (0.055%) plus an
  adverse slippage (default 0.05%). Funding is charged on the open position at
  every settlement bar (-position x price x rate; longs pay positive rates).
* Isolated margin: bot equity = investment + realised + unrealised - fees +
  funding. Liquidation when equity <= MMR x |position| x price; on liquidation
  the whole bot equity is lost (conservative).
* Stop loss must sit beyond the range edge (short: SL >= upper, long: SL <=
  lower, neutral: one on each side), as the Bybit app enforces. Take profit is an
  optional price trigger on the profitable side.
* Intrabar path: up candles O->L->H->C, down candles O->H->L->C. Within each
  monotone leg every line crossed fills once, stop/liquidation are found at their
  exact price. Gaps between the previous close and the open fill lines at their
  price but stops/liquidations crossed in a gap execute at the open (worse).
  Oscillation inside a candle that the OHLC does not show is NOT counted, so
  grid profit for tight steps is understated (conservative for grids).

Speed: the kernel is numba-compiled when numba is installed (research/grid/run.py
needs it for the full sweep); otherwise it runs as plain Python (fine for tests).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

try:                                              # optional JIT
    from numba import njit
except Exception:                                 # noqa: BLE001
    def njit(*a, **k):                            # type: ignore[misc]
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

MAKER_FEE = 0.0002
TAKER_FEE = 0.00055
SLIPPAGE = 0.0005
MMR = 0.005

# exit reason codes
TIME, STOP_HI, STOP_LO, LIQ, END = 0, 1, 2, 3, 4
REASONS = {TIME: "time", STOP_HI: "exit_hi", STOP_LO: "exit_lo", LIQ: "liquidated", END: "data_end"}

# state vector slots
_CUR, _C, _POS, _K, _GP, _FEE, _NF, _FUND = range(8)


@njit(cache=True)
def _fill(st, levels, stype, full, cost, q, maker, j, up):
    """Price reached line j moving up (from k=j-1) or down (from k=j+1)."""
    x = levels[j]
    if up:
        i = j - 1
        if stype[i] == 1 and full[i]:            # long slot: take profit
            st[_POS] -= q
            st[_C] += q * x
            st[_GP] += q * (x - cost[i])
            full[i] = False
            st[_C] -= maker * q * x
            st[_FEE] += maker * q * x
            st[_NF] += 1
        elif stype[i] == -1 and not full[i]:     # short slot: open
            st[_POS] -= q
            st[_C] += q * x
            cost[i] = x
            full[i] = True
            st[_C] -= maker * q * x
            st[_FEE] += maker * q * x
            st[_NF] += 1
    else:
        i = j
        if stype[i] == 1 and not full[i]:        # long slot: open
            st[_POS] += q
            st[_C] -= q * x
            cost[i] = x
            full[i] = True
            st[_C] -= maker * q * x
            st[_FEE] += maker * q * x
            st[_NF] += 1
        elif stype[i] == -1 and full[i]:         # short slot: take profit
            st[_POS] += q
            st[_C] -= q * x
            st[_GP] += q * (cost[i] - x)
            full[i] = False
            st[_C] -= maker * q * x
            st[_FEE] += maker * q * x
            st[_NF] += 1
    st[_K] = j


@njit(cache=True)
def _leg(st, target, gap, levels, stype, full, cost, q, mmr, maker, exit_hi, exit_lo):
    """Move price monotonically from st[_CUR] to target. Returns (code, price);
    code -1 = no exit, else STOP_HI / STOP_LO / LIQ at that price."""
    n = levels.shape[0] - 1
    up = target >= st[_CUR]
    while True:
        k = int(st[_K])
        cur = st[_CUR]
        pos = st[_POS]
        if up:
            j = k + 1
            lv = levels[j] if j <= n else np.inf
            bound = lv if lv < target else target
            ev_px = np.inf
            ev = -1
            if exit_hi > 0.0 and cur < exit_hi <= bound:
                ev_px, ev = exit_hi, STOP_HI
            if pos < 0.0:
                a = pos * (1.0 + mmr)
                xs = -st[_C] / a
                if xs <= cur:
                    xs = cur
                if xs <= bound and xs < ev_px:
                    ev_px, ev = xs, LIQ
            if ev >= 0:
                return ev, (target if gap else ev_px)
            if lv <= target:
                st[_CUR] = lv
                _fill(st, levels, stype, full, cost, q, maker, j, True)
                continue
            st[_CUR] = target
            return -1, target
        else:
            j = k - 1
            lv = levels[j] if j >= 0 else -np.inf
            bound = lv if lv > target else target
            ev_px = -np.inf
            ev = -1
            if exit_lo > 0.0 and bound <= exit_lo < cur:
                ev_px, ev = exit_lo, STOP_LO
            if pos > 0.0:
                a = pos * (1.0 - mmr)
                xs = -st[_C] / a
                if xs >= cur:
                    xs = cur
                if xs >= bound and xs > ev_px:
                    ev_px, ev = xs, LIQ
            if ev >= 0:
                return ev, (target if gap else ev_px)
            if lv >= target:
                st[_CUR] = lv
                _fill(st, levels, stype, full, cost, q, maker, j, False)
                continue
            st[_CUR] = target
            return -1, target


@njit(cache=True)
def _close(st, px, taker, slip):
    pos = st[_POS]
    if pos > 0.0:
        px = px * (1.0 - slip)
    elif pos < 0.0:
        px = px * (1.0 + slip)
    fee = taker * abs(pos) * px
    st[_FEE] += fee
    return st[_C] + pos * px - fee


@njit(cache=True)
def run_kernel(o, h, l, c, fund, start, last, levels, stype, k0, q, inv,
               mmr, maker, taker, slip, exit_hi, exit_lo, eq_out):
    """Simulate one grid from the open of bar `start` to the close of bar `last`.
    Returns (reason, exit_bar, exit_price, equity_end, grid_profit, fees,
    funding, max_drawdown, n_fills, min_equity). eq_out (len >= last-start+1)
    receives the equity marked at each bar close."""
    n = levels.shape[0] - 1
    full = np.zeros(n, np.bool_)
    cost = np.zeros(n)
    st = np.zeros(8)
    p0 = o[start]
    st[_CUR] = p0
    st[_C] = inv
    st[_K] = k0
    for i in range(n):
        if (stype[i] == 1 and i >= k0) or (stype[i] == -1 and i < k0):
            full[i] = True
            cost[i] = p0
            if stype[i] == 1:
                st[_POS] += q
                st[_C] -= q * p0
            else:
                st[_POS] -= q
                st[_C] += q * p0
    f0 = taker * abs(st[_POS]) * p0
    slip_cost = slip * abs(st[_POS]) * p0
    st[_C] -= f0 + slip_cost
    st[_FEE] += f0 + slip_cost
    peak = inv
    mdd = 0.0
    mineq = inv
    nb = o.shape[0]
    if last > nb - 1:
        last = nb - 1
    pts = np.zeros(4)
    for b in range(start, last + 1):
        if fund[b] != 0.0:
            pay = -st[_POS] * o[b] * fund[b]
            st[_C] += pay
            st[_FUND] += pay
        if c[b] >= o[b]:
            pts[0], pts[1], pts[2], pts[3] = o[b], l[b], h[b], c[b]
        else:
            pts[0], pts[1], pts[2], pts[3] = o[b], h[b], l[b], c[b]
        for p in range(4):
            code, px = _leg(st, pts[p], p == 0 and b > start, levels, stype, full, cost,
                            q, mmr, maker, exit_hi, exit_lo)
            if code >= 0:
                if code == LIQ:
                    eq = 0.0
                else:
                    eq = _close(st, px, taker, slip)
                if eq < mineq:
                    mineq = eq
                if peak - eq > mdd:
                    mdd = peak - eq
                eq_out[b - start] = eq
                return code, b, px, eq, st[_GP], st[_FEE], st[_FUND], mdd, st[_NF], mineq
            eq = st[_C] + st[_POS] * pts[p]
            if eq > peak:
                peak = eq
            if peak - eq > mdd:
                mdd = peak - eq
            if eq < mineq:
                mineq = eq
        eq_out[b - start] = st[_C] + st[_POS] * c[last if b > last else b]
    eq = _close(st, c[last], taker, slip)
    if peak - eq > mdd:
        mdd = peak - eq
    if eq < mineq:
        mineq = eq
    eq_out[last - start] = eq
    reason = TIME
    return reason, last, c[last], eq, st[_GP], st[_FEE], st[_FUND], mdd, st[_NF], mineq


# ── Python-facing API ────────────────────────────────────────────────────────
@dataclass
class GridConfig:
    mode: str                     # "long" | "short" | "neutral"
    lower: float
    upper: float
    grids: int
    leverage: float
    investment: float = 50.0
    spacing: str = "arithmetic"   # or "geometric"
    stop_upper: float | None = None   # short / neutral stop (>= upper)
    stop_lower: float | None = None   # long / neutral stop (<= lower)
    tp_upper: float | None = None     # long take profit (price trigger)
    tp_lower: float | None = None     # short take profit
    mmr: float = MMR
    maker: float = MAKER_FEE
    taker: float = TAKER_FEE
    slippage: float = SLIPPAGE

    def validate(self) -> None:
        if self.mode not in ("long", "short", "neutral"):
            raise ValueError(f"bad mode {self.mode}")
        if not 0 < self.lower < self.upper:
            raise ValueError("need 0 < lower < upper")
        if self.grids < 2:
            raise ValueError("need >= 2 grids")
        if self.stop_upper is not None and self.stop_upper < self.upper:
            raise ValueError("Bybit rule: upper stop must be >= range top")
        if self.stop_lower is not None and self.stop_lower > self.lower:
            raise ValueError("Bybit rule: lower stop must be <= range bottom")
        if self.mode == "short" and self.stop_lower is not None:
            raise ValueError("short grid stop goes above the range")
        if self.mode == "long" and self.stop_upper is not None:
            raise ValueError("long grid stop goes below the range")

    def levels(self) -> np.ndarray:
        n = self.grids
        if self.spacing == "geometric":
            return self.lower * (self.upper / self.lower) ** (np.arange(n + 1) / n)
        return np.linspace(self.lower, self.upper, n + 1)


@dataclass
class GridSetup:
    levels: np.ndarray
    stype: np.ndarray
    k0: int
    q: float
    exit_hi: float
    exit_lo: float


def build(cfg: GridConfig, p0: float) -> GridSetup:
    """Lines, slot types, start pointer and per-slot qty for a start price."""
    cfg.validate()
    if not cfg.lower <= p0 <= cfg.upper:
        raise ValueError("start price must be inside the range")
    lv = cfg.levels()
    n = cfg.grids
    k0 = int(np.argmin(np.abs(lv - p0)))
    idx = np.arange(n)
    if cfg.mode == "long":
        stype = np.ones(n, np.int8)
    elif cfg.mode == "short":
        stype = -np.ones(n, np.int8)
    else:
        stype = np.where(idx < k0, 1, -1).astype(np.int8)
    long_entry = np.where(idx >= k0, p0, lv[:-1])          # cost if filled
    short_entry = np.where(idx < k0, p0, lv[1:])
    if cfg.mode == "long":
        denom = long_entry.sum()
    elif cfg.mode == "short":
        denom = short_entry.sum()
    else:
        denom = lv[:-1][idx < k0].sum() + lv[1:][idx >= k0].sum()
    q = cfg.investment * cfg.leverage / denom
    hi = cfg.stop_upper if cfg.stop_upper is not None else (cfg.tp_upper or 0.0)
    lo = cfg.stop_lower if cfg.stop_lower is not None else (cfg.tp_lower or 0.0)
    return GridSetup(lv, stype, k0, q, float(hi or 0.0), float(lo or 0.0))


@dataclass
class GridResult:
    reason: str
    exit_bar: int
    exit_price: float
    equity_end: float
    pnl: float
    grid_profit: float
    position_pnl: float
    fees: float
    funding: float
    max_drawdown: float
    min_equity: float
    fills: int
    equity: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))


def simulate(o, h, l, c, cfg: GridConfig, start: int = 0, max_bars: int | None = None,
             funding: np.ndarray | None = None) -> GridResult:
    """Run one grid on OHLC arrays from the open of bar `start`."""
    o, h, l, c = (np.asarray(x, dtype=np.float64) for x in (o, h, l, c))
    fund = np.zeros_like(o) if funding is None else np.asarray(funding, dtype=np.float64)
    last = len(o) - 1 if max_bars is None else min(len(o) - 1, start + max_bars - 1)
    s = build(cfg, float(o[start]))
    eq = np.zeros(last - start + 1)
    r = run_kernel(o, h, l, c, fund, start, last, s.levels, s.stype, s.k0, s.q,
                   cfg.investment, cfg.mmr, cfg.maker, cfg.taker, cfg.slippage,
                   s.exit_hi, s.exit_lo, eq)
    code, xb, xp, eqe, gp, fees, fnd, mdd, nf, mineq = r
    if code == TIME and max_bars is not None and start + max_bars - 1 > len(o) - 1:
        code = END
    pnl = eqe - cfg.investment
    return GridResult(REASONS[int(code)], int(xb), float(xp), float(eqe), float(pnl),
                      float(gp), float(pnl - gp + fees - fnd), float(fees), float(fnd),
                      float(mdd), float(mineq), int(nf), eq[: int(xb) - start + 1])


def _straight(p0: float, p1: float) -> tuple[np.ndarray, ...]:
    """One candle that opens at p0 and moves straight to p1."""
    o = np.array([p0]); c = np.array([p1])
    return o, np.maximum(o, c), np.minimum(o, c), c


def worst_case(cfg: GridConfig, p0: float) -> dict:
    """Loss if price runs straight from p0 through each stop (every rung on the
    way filled), and the liquidation price of the fully filled position without
    a stop. `ok_liq` = liquidation at least 2x further from p0 than the stop."""
    out = {"loss": 0.0, "liq_up": None, "liq_down": None, "ok_liq": True}
    sides = []
    if cfg.mode in ("short", "neutral"):
        sides.append(("up", cfg.stop_upper))
    if cfg.mode in ("long", "neutral"):
        sides.append(("down", cfg.stop_lower))
    for side, stop in sides:
        if stop is None:
            out["loss"] = float("inf")
            continue
        beyond = stop * (1.002 if side == "up" else 0.998)
        r = simulate(*_straight(p0, beyond), cfg)
        out["loss"] = max(out["loss"], -r.pnl)
        free = GridConfig(**{**cfg.__dict__, "stop_upper": None, "stop_lower": None,
                             "tp_upper": None, "tp_lower": None})
        far = p0 * 20 if side == "up" else p0 * 1e-6
        rl = simulate(*_straight(p0, far), free)
        liq = rl.exit_price if rl.reason == "liquidated" else None
        out[f"liq_{side}"] = liq
        if liq is None:
            continue
        if abs(liq - p0) < 2 * abs(stop - p0):
            out["ok_liq"] = False
    return out


# ── Batch kernel for the parameter sweep (no per-trade Python overhead) ──────
OK, REJ_STEP, REJ_LOSS, REJ_LIQ, SKIP = 0, 1, 2, 3, 4
MODES = {"long": 1, "short": -1, "neutral": 0}


@njit(cache=True)
def _build_nb(p0, lower, upper, n, mode, geometric, inv, lev):
    lv = np.empty(n + 1)
    for i in range(n + 1):
        if geometric:
            lv[i] = lower * (upper / lower) ** (i / n)
        else:
            lv[i] = lower + (upper - lower) * i / n
    k0 = 0
    best = np.inf
    for i in range(n + 1):
        d = abs(lv[i] - p0)
        if d < best:
            best = d
            k0 = i
    stype = np.empty(n, np.int8)
    dl = 0.0
    ds = 0.0
    for i in range(n):
        if mode == 1:
            stype[i] = 1
        elif mode == -1:
            stype[i] = -1
        else:
            stype[i] = 1 if i < k0 else -1
        le = p0 if i >= k0 else lv[i]
        se = p0 if i < k0 else lv[i + 1]
        if mode == 1:
            dl += le
        elif mode == -1:
            ds += se
        else:
            if i < k0:
                dl += lv[i]
            else:
                ds += lv[i + 1]
    denom = dl if mode == 1 else (ds if mode == -1 else dl + ds)
    return lv, stype, k0, inv * lev / denom


@njit(cache=True)
def run_batch(o, h, l, c, fund, starts, lowers, uppers, n, mode, geometric, inv, lev,
              stop_buf, tp_exit, hold_bars, max_loss, liq_mult, mmr, maker, taker, slip,
              no_overlap=False):
    """Simulate one grid per entry in `starts` (bar index; start price = open).
    Stops sit `stop_buf` beyond each range edge on the losing side(s); with
    tp_exit the bot also closes when price leaves the range on the profitable
    side (directional grids, where it is flat there). Pre-trade rejection:
    net profit per grid <= 0 after fees (REJ_STEP), straight-line loss through
    the stop > max_loss (REJ_LOSS), or liquidation closer than liq_mult x the
    stop distance (REJ_LIQ). Returns a (m, 10) array:
    status, reason, exit_bar, pnl, grid_profit, fees, funding, mdd, wc_loss, fills.
    With no_overlap (starts sorted, one coin), an entry before the previous
    taken trade's exit bar is skipped (status SKIP), as one bot per coin."""
    m = starts.shape[0]
    out = np.full((m, 10), np.nan)
    buf = np.zeros(hold_bars + 2)
    one_o = np.zeros(1)
    one_h = np.zeros(1)
    one_l = np.zeros(1)
    one_c = np.zeros(1)
    one_f = np.zeros(1)
    b1 = np.zeros(1)
    nb = o.shape[0]
    busy = -1
    for t in range(m):
        s = starts[t]
        if no_overlap and s <= busy:
            out[t, 0] = SKIP
            continue
        p0 = o[s]
        lo = lowers[t]
        hi = uppers[t]
        if not (0.0 < lo < p0 < hi):
            out[t, 0] = REJ_STEP
            continue
        lv, stype, k0, q = _build_nb(p0, lo, hi, n, mode, geometric, inv, lev)
        if geometric:
            step = (hi / lo) ** (1.0 / n) - 1.0
        else:
            step = (hi - lo) / n / hi
        if step - 2.0 * maker <= 0.0:
            out[t, 0] = REJ_STEP
            continue
        s_hi = hi * (1.0 + stop_buf) if mode <= 0 else 0.0
        s_lo = lo * (1.0 - stop_buf) if mode >= 0 else 0.0
        e_hi = s_hi
        e_lo = s_lo
        if tp_exit:
            if mode == 1:
                e_hi = hi * (1.0 + stop_buf)
            elif mode == -1:
                e_lo = lo * (1.0 - stop_buf)
        # worst case: straight line through each losing-side stop
        wc = 0.0
        bad_liq = False
        for side in range(2):
            if side == 0 and mode == 1:
                continue
            if side == 1 and mode == -1:
                continue
            stop = s_hi if side == 0 else s_lo
            tgt = stop * (1.002 if side == 0 else 0.998)
            one_o[0] = p0
            one_c[0] = tgt
            one_h[0] = max(p0, tgt)
            one_l[0] = min(p0, tgt)
            r = run_kernel(one_o, one_h, one_l, one_c, one_f, 0, 0, lv, stype, k0, q, inv,
                           mmr, maker, taker, slip, s_hi if side == 0 else 0.0,
                           s_lo if side == 1 else 0.0, b1)
            loss = inv - r[3]
            if r[0] == LIQ:
                loss = inv
                bad_liq = True
            if loss > wc:
                wc = loss
            far = p0 * 50.0 if side == 0 else p0 * 1e-6
            one_c[0] = far
            one_h[0] = max(p0, far)
            one_l[0] = min(p0, far)
            r2 = run_kernel(one_o, one_h, one_l, one_c, one_f, 0, 0, lv, stype, k0, q, inv,
                            mmr, maker, taker, slip, 0.0, 0.0, b1)
            if r2[0] == LIQ and abs(r2[2] - p0) < liq_mult * abs(stop - p0):
                bad_liq = True
        out[t, 8] = wc
        if wc > max_loss + 1e-9:
            out[t, 0] = REJ_LOSS
            continue
        if bad_liq:
            out[t, 0] = REJ_LIQ
            continue
        last = s + hold_bars - 1
        if last > nb - 1:
            last = nb - 1
        r = run_kernel(o, h, l, c, fund, s, last, lv, stype, k0, q, inv, mmr, maker, taker,
                       slip, e_hi, e_lo, buf)
        reason = r[0]
        if reason == TIME and s + hold_bars - 1 > nb - 1:
            reason = END
        out[t, 0] = OK
        busy = r[1]
        out[t, 1] = reason
        out[t, 2] = r[1]
        out[t, 3] = r[3] - inv
        out[t, 4] = r[4]
        out[t, 5] = r[5]
        out[t, 6] = r[6]
        out[t, 7] = r[7]
        out[t, 9] = r[8]
    return out
