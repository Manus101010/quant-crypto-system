"""
Statistical Validation Gate (Deflated Sharpe Ratio)
====================================================
Roadmap item #2 (docs/INSTITUTIONAL_ROADMAP.md §1 Overfitting & Validation,
§7 Monitoring). The conviction multipliers in ``paper_trades/stats.py`` are
learned from per-setup profit factor on the *same* paper history they score
against — textbook in-sample tuning with no multiple-testing correction. With
~10 macro signals × several setup types × thresholds, the best-looking setup
is very likely a lucky draw rather than a real edge.

This module gates those multipliers behind a **Deflated Sharpe Ratio (DSR)**
test, so a setup's multiplier only deviates from neutral (1.0) when its edge is
statistically significant *after* correcting for:
  (a) the number of setups (trials) tested — multiple testing,
  (b) the sample length, and
  (c) the skew (γ3) and kurtosis (γ4) of the trade-return distribution.

Reference
---------
Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting and Non-Normality."
Journal of Portfolio Management, 40(5). SSRN id=2460551.

DSR formula
-----------
Observed (per-setup) Sharpe of the trade-return series:
    SR = mean(returns) / std(returns)        (per-trade, non-annualised)

Expected maximum Sharpe under N *independent* trials of zero-edge strategies
(Bailey & López de Prado, eq. for SR0):
    SR0 = sqrt(Var_trials) * [ (1-γ) · Z^-1(1 - 1/N)
                               + γ · Z^-1(1 - 1/(N·e)) ]
where γ ≈ 0.5772 (Euler–Mascheroni), Z^-1 is the inverse standard-normal CDF,
e is Euler's number, and Var_trials is the cross-trial variance of the Sharpe
estimates. We do not have the full set of trial Sharpes here, so we use the
estimator's own sampling variance as a conservative proxy for the spread of
candidate Sharpes (standard practice when the trial distribution is unknown).

Deflated Sharpe Ratio (probability the true Sharpe exceeds SR0):
    DSR = Z[ (SR - SR0) · sqrt(n - 1)
             / sqrt(1 - γ3·SR + ((γ4 - 1)/4)·SR^2) ]
where Z is the standard-normal CDF, n is the number of observations (trades),
γ3 is skew and γ4 is kurtosis (non-excess, i.e. 3 for a normal). DSR is a
probability in [0, 1]; we report p_value = 1 - DSR and call the setup
``significant`` when p_value < alpha (default 0.05).
"""
from __future__ import annotations

import math
import numpy as np
from scipy.stats import norm

# Euler–Mascheroni constant (used in the expected-max-Sharpe SR0 term).
_EULER_GAMMA = 0.5772156649015329

# Minimum closed trades before a DSR test is meaningful. Below this the
# moment estimates (esp. skew/kurtosis) are too noisy to trust, so we never
# declare significance.
MIN_TRADES = 10


def deflated_sharpe(returns: list[float], n_trials: int) -> dict:
    """
    Compute the Deflated Sharpe Ratio for a single setup's trade-return series.

    Parameters
    ----------
    returns : list[float]
        Per-trade net returns for ONE setup (e.g. actual_pnl_pct in %). The
        Sharpe is computed per-trade (not annualised) — fine for a relative,
        multiple-testing-honest gate.
    n_trials : int
        Number of setups (strategies/configurations) evaluated. This is the N
        in the expected-maximum-Sharpe SR0 deflation term.

    Returns
    -------
    dict with keys:
        sharpe      : observed per-trade Sharpe ratio (mean/std)
        dsr         : Deflated Sharpe Ratio, a probability in [0, 1]
        p_value     : 1 - dsr
        n           : number of observations used
        significant : bool — True iff n >= MIN_TRADES and p_value < 0.05
    """
    r = np.asarray([x for x in returns if x is not None], dtype=float)
    n = int(r.size)

    # Guard: too few trades → never significant, return a neutral report.
    if n < MIN_TRADES:
        sr = float("nan")
        if n >= 2 and np.std(r, ddof=1) > 0:
            sr = float(np.mean(r) / np.std(r, ddof=1))
        return {
            "sharpe": sr,
            "dsr": 0.0,
            "p_value": 1.0,
            "n": n,
            "significant": False,
        }

    std = float(np.std(r, ddof=1))
    if std == 0.0:
        # Zero variance → undefined Sharpe; treat as no edge.
        return {
            "sharpe": 0.0,
            "dsr": 0.0,
            "p_value": 1.0,
            "n": n,
            "significant": False,
        }

    # Observed per-trade Sharpe.
    sr = float(np.mean(r) / std)

    # Higher moments of the return distribution.
    # skew γ3 (Fisher), kurtosis γ4 NON-excess (normal == 3.0).
    from scipy.stats import skew as _skew, kurtosis as _kurtosis
    gamma3 = float(_skew(r, bias=False))
    gamma4 = float(_kurtosis(r, fisher=False, bias=False))  # non-excess

    # --- Expected maximum Sharpe under N independent zero-edge trials (SR0) ---
    # Spread of candidate Sharpes is unknown here; use the sampling variance of
    # the SR estimator as a conservative proxy (Bailey & López de Prado note
    # the cross-trial Sharpe variance drives SR0; absent the trial set we use
    # the estimator variance).
    var_sr = (1.0 - gamma3 * sr + ((gamma4 - 1.0) / 4.0) * sr * sr) / (n - 1.0)
    var_sr = max(var_sr, 1e-12)
    sigma_sr = math.sqrt(var_sr)

    N = max(int(n_trials), 1)
    if N <= 1:
        sr0 = 0.0
    else:
        z1 = norm.ppf(1.0 - 1.0 / N)
        z2 = norm.ppf(1.0 - 1.0 / (N * math.e))
        sr0 = sigma_sr * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)

    # --- Deflated Sharpe Ratio: P(true SR > SR0) ---
    denom = math.sqrt(max(1.0 - gamma3 * sr + ((gamma4 - 1.0) / 4.0) * sr * sr, 1e-12))
    z_dsr = (sr - sr0) * math.sqrt(n - 1.0) / denom
    dsr = float(norm.cdf(z_dsr))
    p_value = 1.0 - dsr

    return {
        "sharpe": sr,
        "dsr": dsr,
        "p_value": p_value,
        "n": n,
        "significant": bool(n >= MIN_TRADES and p_value < 0.05),
    }


def validated_multipliers(
    raw_multipliers: dict[str, float],
    per_setup_returns: dict[str, list[float]],
    alpha: float = 0.05,
) -> dict[str, dict]:
    """
    Gate raw learned conviction multipliers behind a DSR significance test.

    For each setup, run ``deflated_sharpe`` on its net-return series. If the
    DSR p-value >= alpha (NOT statistically significant) OR there are too few
    trades, pull the multiplier toward 1.0 (neutral). If significant, keep the
    learned multiplier. ``n_trials`` for the multiple-testing correction is the
    number of setups being evaluated.

    Parameters
    ----------
    raw_multipliers : {setup_label: float}
        The in-sample learned multipliers (e.g. from profit factor).
    per_setup_returns : {setup_label: list[float]}
        Net per-trade returns per setup.
    alpha : float
        Significance threshold (default 0.05).

    Returns
    -------
    {setup_label: {multiplier, dsr, p_value, significant, n}}
        ``multiplier`` is the GATED value: the learned multiplier if the edge
        is significant, else 1.0 (neutral).
    """
    # Number of setups tested = trial count for the multiple-testing deflation.
    n_trials = max(len(raw_multipliers), 1)

    out: dict[str, dict] = {}
    for label, raw in raw_multipliers.items():
        returns = per_setup_returns.get(label, [])
        report = deflated_sharpe(returns, n_trials=n_trials)

        if report["significant"] and report["p_value"] < alpha:
            # Edge survives multiple-testing-honest scrutiny → trust it.
            gated = float(raw)
        else:
            # Not validated → neutralise to 1.0 (no conviction tilt).
            gated = 1.0

        out[label] = {
            "multiplier": gated,
            "dsr": report["dsr"],
            "p_value": report["p_value"],
            "significant": report["significant"],
            "n": report["n"],
        }
    return out
