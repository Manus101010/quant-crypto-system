"""Offline tests for the futures grid simulator (research/grid/sim.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.grid.sim import (  # noqa: E402
    MAKER_FEE, TAKER_FEE, SLIPPAGE, GridConfig, build, simulate, worst_case,
)


def path_candles(points: list[float]) -> tuple[np.ndarray, ...]:
    """One straight candle per consecutive pair of points (open=prev, close=next)."""
    o = np.array(points[:-1], float)
    c = np.array(points[1:], float)
    return o, np.maximum(o, c), np.minimum(o, c), c


def test_levels_arithmetic_and_geometric():
    a = GridConfig("neutral", 90, 110, 20, 3).levels()
    assert len(a) == 21 and np.allclose(np.diff(a), 1.0)
    g = GridConfig("neutral", 100, 400, 2, 3, spacing="geometric").levels()
    assert np.allclose(g, [100, 200, 400])


def test_bybit_stop_rule_enforced():
    with pytest.raises(ValueError):
        GridConfig("short", 90, 110, 20, 5, stop_upper=109).validate()
    with pytest.raises(ValueError):
        GridConfig("long", 90, 110, 20, 5, stop_lower=91).validate()


def test_pure_oscillation_profit_matches_crossings():
    cfg = GridConfig("neutral", 90, 110, 20, 3, investment=50,
                     stop_upper=111, stop_lower=89)
    cycles = 5
    pts = [100.0] + [105.0, 95.0] * cycles + [100.0]
    r = simulate(*path_candles(pts), cfg)
    q = build(cfg, 100.0).q
    # up 100->105 opens 5 shorts; each swing after closes 5 and opens 5 the
    # other way; final 95->100 closes 5 longs. Closed round trips:
    round_trips = 5 * (2 * cycles - 1) + 5
    assert r.grid_profit == pytest.approx(q * 1.0 * round_trips, rel=1e-9)
    # every round trip pays two maker fills; plus the 5 open-short fills at the
    # start; the bot ends flat at 100 so no taker fee/slip on close.
    assert r.fills == 2 * round_trips
    fees = sum(MAKER_FEE * q * x for x in [101, 102, 103, 104, 105]) * (2 * cycles)
    assert r.fees == pytest.approx(r.fills * MAKER_FEE * q * 100, rel=0.05)
    assert r.pnl == pytest.approx(r.grid_profit - r.fees, rel=1e-9)
    assert r.pnl > 0 and r.reason == "time" and fees > 0


def test_short_trend_through_stop_loses_worst_case():
    cfg = GridConfig("short", 100, 110, 10, 5, investment=50, stop_upper=111)
    o, h, l, c = path_candles([100.0, 112.0])
    r = simulate(o, h, l, c, cfg)
    assert r.reason == "exit_hi"
    s = build(cfg, 100.0)
    q = s.q
    assert s.k0 == 0                                  # flat at the bottom
    entries = np.arange(101, 111, dtype=float)        # every slot opened on the way up
    exit_px = 111 * (1 + SLIPPAGE)
    pos = q * len(entries)
    expected = (-(exit_px - entries).sum() * q
                - MAKER_FEE * q * entries.sum() - TAKER_FEE * pos * exit_px)
    assert r.pnl == pytest.approx(expected, rel=1e-9)
    assert worst_case(cfg, 100.0)["loss"] == pytest.approx(-expected, rel=1e-3)
    # sizing: the fully filled position is investment x leverage of notional
    assert (q * entries).sum() == pytest.approx(50 * 5, rel=1e-9)


def test_short_grid_opens_initial_position_at_top():
    cfg = GridConfig("short", 100, 110, 10, 5, investment=50, stop_upper=111)
    o, h, l, c = path_candles([110.0, 110.0])
    r = simulate(o, h, l, c, cfg)
    s = build(cfg, 110.0)
    assert s.k0 == 10
    # opened 10 slots at market: taker fee + slippage on the full notional
    assert r.fees == pytest.approx((TAKER_FEE + SLIPPAGE) * 10 * s.q * 110 + TAKER_FEE * 10 * s.q * 110 * (1 + SLIPPAGE), rel=1e-6)


def test_long_grid_liquidates_without_stop():
    cfg = GridConfig("long", 90, 100, 10, 10, investment=50)
    o, h, l, c = path_candles([100.0, 50.0])
    r = simulate(o, h, l, c, cfg)
    assert r.reason == "liquidated"
    assert r.equity_end == 0.0
    s = build(cfg, 100.0)
    pos = s.q * 10
    assert s.k0 == 10                       # long grid starting at the top is flat
    cash = 50 - MAKER_FEE * s.q * np.arange(90, 100).sum()
    avg = (s.q * np.arange(90, 100)).sum() / pos
    # equity(x) = cash + pos*(x - avg) == MMR*pos*x  -> solve x
    liq = (pos * avg - cash) / (pos * (1 - 0.005))
    assert r.exit_price == pytest.approx(liq, rel=1e-6)
    w = worst_case(GridConfig("long", 90, 100, 10, 10, investment=50, stop_lower=89), 100.0)
    assert w["liq_down"] == pytest.approx(liq, rel=1e-3)


def test_gap_through_stop_fills_at_open():
    cfg = GridConfig("short", 100, 110, 10, 3, investment=50, stop_upper=111)
    o = np.array([100.0, 120.0]); c = np.array([100.0, 121.0])
    r = simulate(o, np.maximum(o, c), np.minimum(o, c), c, cfg)
    assert r.reason == "exit_hi" and r.exit_price == 120.0


def test_funding_charged_on_open_position():
    cfg = GridConfig("short", 100, 110, 10, 5, investment=50, stop_upper=111)
    o = np.full(3, 110.0); c = o.copy()
    fund = np.array([0.0, 0.001, 0.0])
    r = simulate(o, o, o, c, cfg, funding=fund)
    pos = build(cfg, 110.0).q * 10
    assert r.funding == pytest.approx(pos * 110 * 0.001, rel=1e-9)   # shorts receive


def test_time_cap_and_down_candle_path():
    cfg = GridConfig("neutral", 90, 110, 20, 3, stop_upper=111, stop_lower=89)
    # down candle: O->H->L->C, so the high is visited first
    o = np.array([100.0, 100.0]); h = np.array([103.0, 100.0])
    l = np.array([97.0, 100.0]); c = np.array([99.0, 100.0])
    r = simulate(o, h, l, c, cfg, max_bars=1)
    assert r.reason == "time" and r.exit_bar == 0
    q = build(cfg, 100.0).q
    # 100->103 opens 3 shorts, 103->97 closes 3 and opens 3 longs, 97->99 closes 2
    assert r.grid_profit == pytest.approx(q * 5, rel=1e-9)


def test_batch_matches_single_and_rejects():
    from research.grid.sim import run_batch, OK, REJ_LOSS, REJ_STEP, MMR
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 600)))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * 1.001
    l = np.minimum(o, c) * 0.999
    f = np.zeros_like(o)
    starts = np.array([10, 200])
    lows = o[starts] * 0.95
    highs = o[starts] * 1.05
    out = run_batch(o, h, l, c, f, starts, lows, highs, 20, 0, False, 50.0, 3.0,
                    0.002, False, 100, 1e9, 0.0, MMR, MAKER_FEE, TAKER_FEE, SLIPPAGE)
    for j, s in enumerate(starts):
        cfg = GridConfig("neutral", lows[j], highs[j], 20, 3.0, stop_upper=highs[j] * 1.002,
                         stop_lower=lows[j] * 0.998)
        r = simulate(o, h, l, c, cfg, start=int(s), max_bars=100)
        assert out[j, 0] == OK
        assert out[j, 3] == pytest.approx(r.pnl, rel=1e-9, abs=1e-12)
        assert out[j, 4] == pytest.approx(r.grid_profit, rel=1e-9, abs=1e-12)
    rej = run_batch(o, h, l, c, f, starts, lows, highs, 20, 0, False, 50.0, 10.0,
                    0.002, False, 100, 5.0, 2.0, MMR, MAKER_FEE, TAKER_FEE, SLIPPAGE)
    assert (rej[:, 0] == REJ_LOSS).all() and (rej[:, 8] > 5.0).all()
    tight = run_batch(o, h, l, c, f, starts, o[starts] * 0.999, o[starts] * 1.001, 200, 0,
                      False, 50.0, 3.0, 0.002, False, 100, 12.5, 2.0, MMR, MAKER_FEE,
                      TAKER_FEE, SLIPPAGE)
    assert (tight[:, 0] == REJ_STEP).all()


def test_batch_no_overlap_skips_while_bot_running():
    from research.grid.sim import run_batch, OK, SKIP, MMR
    o = np.full(300, 100.0); c = o.copy()
    starts = np.array([0, 50, 120, 130])
    out = run_batch(o, o, o, c, np.zeros(300), starts, o[starts] * 0.95, o[starts] * 1.05,
                    20, 0, False, 50.0, 3.0, 0.002, False, 100, 1e9, 0.0, MMR,
                    MAKER_FEE, TAKER_FEE, SLIPPAGE, True)
    assert list(out[:, 0]) == [OK, SKIP, OK, SKIP]


def _brute_grid(path, lv, k0, q, stype):
    """Independent order-book model: resting orders per line, re-armed on fill."""
    n = len(lv) - 1
    cash = pos = 0.0
    orders = {}
    for i in range(n):
        if stype[i] == 1 and i < k0:
            orders[i] = ("buy", i)
        elif stype[i] == -1 and i >= k0:
            orders[i + 1] = ("sell", i)
        elif stype[i] == 1:                       # long slot opened at start
            orders[i + 1] = ("sell", i)
        else:                                     # short slot opened at start
            orders[i] = ("buy", i)
    for i in range(n):                            # initial market position
        if stype[i] == 1 and i >= k0:
            pos += q; cash -= q * path[0]
        elif stype[i] == -1 and i < k0:
            pos -= q; cash += q * path[0]
    prev = path[0]
    for x in path[1:]:
        if x > prev:
            lines = [j for j in range(n + 1) if prev < lv[j] <= x]
        else:
            lines = [j for j in range(n + 1) if x <= lv[j] < prev][::-1]
        for j in lines:
            if j in orders:
                side, slot = orders.pop(j)
                if side == "buy":
                    pos += q; cash -= q * lv[j]; orders[slot + 1] = ("sell", slot)
                else:
                    pos -= q; cash += q * lv[j]; orders[slot] = ("buy", slot)
        prev = x
    return cash + pos * path[-1]


@pytest.mark.parametrize("mode", ["neutral", "long", "short"])
def test_kernel_matches_bruteforce_orderbook(mode):
    rng = np.random.default_rng(5)
    for _ in range(20):
        path = 100 * np.exp(np.cumsum(np.r_[0, rng.normal(0, 0.003, 400)]))
        cfg = GridConfig(mode, 85, 118, 40, 3.0, maker=0, taker=0, slippage=0)
        o, c = path[:-1], path[1:]
        if not (85 < o.min() and o.max() < 118 and c.min() > 85 and c.max() < 118):
            continue
        r = simulate(o, np.maximum(o, c), np.minimum(o, c), c, cfg)
        s = build(cfg, o[0])
        assert r.pnl == pytest.approx(_brute_grid(path, s.levels, s.k0, s.q, s.stype), abs=1e-9)
