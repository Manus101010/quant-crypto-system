# QuantCore → Institutional-Grade Roadmap

A prioritized research roadmap for evolving QuantCore from a single-name signal engine with a basic paper-trading feedback loop into something that resembles how institutional systematic desks actually operate.

**Tier legend**
- **Tier 1** — highest ROI / lowest effort. Build first. These close the gaps most likely to make current backtested/paper results lie to you.
- **Tier 2** — meaningful institutional capability, moderate effort.
- **Tier 3** — aspirational / full-desk parity.

A recurring theme: **QuantCore's current learning loop tunes conviction on in-sample paper P&L, and its paper P&L assumes frictionless fills.** Almost every section below is, at root, an attack on one of those two illusions.

---

## 1. Overfitting & Validation Rigor

### What institutional desks do
Serious desks treat a backtest as a *multiple-testing problem*, not a single experiment. Every parameter swept, every setup variant, every conviction threshold tried is a trial — and the best of N trials looks good by luck alone.

- **Walk-forward analysis (rolling, not anchored)** is the baseline: optimize on window *t*, test on the untouched *t+1*, roll forward. The rolling/sliding variant best mimics live deployment because parameters are continuously re-estimated on only-past data ([QuantInsti](https://blog.quantinsti.com/walk-forward-optimization-introduction/), [Susan Potter](https://www.susanpotter.net/quant/walk-forward-optimization/)).
- **Combinatorial Purged Cross-Validation (CPCV)** — López de Prado's method that draws test groups combinatorially, *purges* training samples whose labels overlap the test period, and *embargoes* a buffer after each test fold. It produces *many* backtest paths and thus a *distribution* of Sharpe ratios, not a point estimate. CPCV shows markedly lower Probability of Backtest Overfitting than walk-forward or k-fold ([Wikipedia: Purged CV](https://en.wikipedia.org/wiki/Purged_cross-validation), [SSRN id4778909](https://www.scribd.com/document/725401650/SSRN-id4778909)).
- **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado correct the observed Sharpe for (a) the number of trials, (b) sample length, and (c) skew/kurtosis of returns. A Sharpe of 2.0 found after 100 trials may not be significant ([Wikipedia: DSR](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio), [SSRN 2460551](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)).
- **Probability of Backtest Overfitting (PBO)** via Combinatorially Symmetric Cross-Validation (CSCV) — directly estimates the probability that the in-sample-best configuration underperforms the median out-of-sample ([SSRN 2326253](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253), [pbo R package](https://cran.r-project.org/web/packages/pbo/vignettes/pbo.html)). The same authors' "Pseudo-Mathematics and Financial Charlatanism" shows standard hold-out is unreliable for investment sims.

### What QuantCore lacks
- The conviction multipliers learned from per-setup profit factor are tuned **on the same paper history they're evaluated on** — textbook in-sample tuning with no purge/embargo and no out-of-sample holdout. This is the single biggest overfitting risk in the system.
- No accounting for multiple testing: 10 macro signals × multiple setup types × thresholds = a large trial count with no DSR/PBO deflation.
- No walk-forward harness around the scanner's parameters (RSI-2 bounds, 200-SMA rule, ATR multiples, the 65 conviction cutoff).

### Recommendation
- **Tier 1:** Implement a rolling walk-forward harness for the conviction/threshold parameters. Freeze a true out-of-sample tail of paper history that the learning loop never sees. Add a labeling **purge + embargo** so a trade still open at the train/test boundary can't leak.
- **Tier 1:** Compute and log a **Deflated Sharpe Ratio** for any strategy variant, passing in the count of configurations tried. Treat DSR < 0 / p > 0.05 as "not validated, do not auto-trade."
- **Tier 2:** Add **CPCV** to generate a Sharpe *distribution* and report **PBO** for each setup family. Display the PBO on the setup card next to conviction.

---

## 2. Portfolio Construction

### What institutional desks do
Desks allocate at the *portfolio* level, not as a list of independent best ideas. Markowitz mean-variance optimization (MVO) is notoriously unstable: it inverts the covariance matrix, so estimation error in correlations gets amplified into extreme, concentrated weights, and it fails outright when the covariance matrix is ill-conditioned.

- **Risk parity / equal-risk-contribution (ERC)** sizes positions so each contributes equal risk, not equal dollars — far more robust than MVO to expected-return error.
- **Hierarchical Risk Parity (HRP)** — López de Prado's tree-based alternative: cluster assets by correlation, quasi-diagonalize, then recursively bisect and allocate by inverse variance. It needs no matrix inversion, works on singular/ill-conditioned covariances, and Monte Carlo shows **lower out-of-sample variance than mean-variance — even though MVO explicitly minimizes variance** ([Wikipedia: HRP](https://en.wikipedia.org/wiki/Hierarchical_Risk_Parity), [SSRN 2708678 "Building Diversified Portfolios that Outperform Out-of-Sample"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)).
- Hard **sector / factor exposure limits** and correlation-aware sizing so 8 "independent" longs aren't secretly one tech-beta bet.

### What QuantCore lacks
QuantCore is single-name: it ranks setups and opens any with conviction ≥ 65, sized individually by Kelly + ATR. There is **no covariance estimate, no cross-position correlation, no portfolio-level weight optimization, and no sector/factor cap.** Kelly sizing per-trade ignores that two correlated longs together exceed the intended portfolio risk.

### Recommendation
- **Tier 1:** Add a **correlation-aware position cap** — before opening a setup, estimate its trailing correlation to current open positions and scale size down (or skip) if it stacks an existing exposure. Cheap, prevents the most common blowup.
- **Tier 2:** Replace independent Kelly sizing with **HRP weights** over the candidate set (open positions + new BUYs). HRP is robust to the noisy crypto/stock covariances QuantCore deals with and degrades gracefully.
- **Tier 2:** Add **sector / asset-class exposure limits** (e.g., max % gross in one GICS sector, hard cap on crypto gross).
- **Tier 3:** Factor-model the book (market, momentum, value, size) and constrain net factor betas.

---

## 3. Risk Management

### What institutional desks do
- **Volatility targeting** — scale gross exposure inversely to realized vol to hold portfolio vol near a constant target. Reduces max drawdown for balanced and risk-parity books ([Man Group: The Impact of Volatility Targeting](https://www.man.com/insights/the-impact-of-volatility-targeting)). But naive vol targeting has costs: it can overshoot the target, generate >200%/yr turnover, and demand large time-varying leverage ([Alpha Architect / Financial Analysts Journal: Conditional Volatility Targeting](https://alphaarchitect.com/conditional-volatility-targeting/)).
- **Conditional / regime-aware vol targeting** — only de-risk in extreme high-vol states and lever up in extreme low-vol states, otherwise leave exposure unscaled. Improves Sharpe and cuts tail risk with far lower turnover ([Tandfonline: Conditional Volatility Targeting](https://www.tandfonline.com/doi/full/10.1080/0015198X.2020.1790853)).
- **Max-drawdown governors** that cut gross when peak-to-trough breaches a threshold; **correlation-aware gross/net limits**; and **tail hedges** (put spreads, VIX calls) sized as a standing cost.

### What QuantCore lacks
Risk is purely *per-trade* (Kelly + ATR stop). There is **no portfolio vol target, no aggregate drawdown governor, no gross/net exposure cap, and no tail hedge.** The macro Deployment Score gates *whether* to deploy but does not continuously scale *leverage* to a vol target.

### Recommendation
- **Tier 1:** Add a **portfolio max-drawdown governor** — when equity drops X% from its high-water mark, halve new-position sizing and raise the conviction cutoff until recovery. Trivial to bolt onto the paper loop, large tail benefit.
- **Tier 1:** Wire the existing macro Deployment Score into a **regime-conditional leverage scalar** (e.g., gross 0.5× in risk-off, 1.0× neutral, up to 1.5× in confirmed risk-on) — you already compute the regime; just let it size the whole book.
- **Tier 2:** Implement **conditional volatility targeting** on portfolio realized vol (act only in extreme states) to control overshoot and turnover.
- **Tier 3:** Standing **tail-risk hedge** budget.

---

## 4. Execution Realism

### What institutional desks do
They assume the backtest is optimistic until proven otherwise. A strategy showing Sharpe 1.5 frictionless can fall below 0.5 once realistic fills are modeled ([QuantMedia: Slippage & Latency Modeling](https://quantmedia.io/paper-slippage-latency-modeling.html)).

- Model the fill as **future midprice + half-spread + market impact + noise**, not the current mid ([QuantMedia](https://quantmedia.io/paper-slippage-latency-modeling.html)).
- **Square-root market-impact law**: impact ≈ k · σ · √(order size / ADV) — cost grows with the square root of participation, scaled by volatility. It's a first-order approximation (empirical exponent ranges ~0.4–0.7) but the standard institutional default ([arXiv 1602.03043](https://arxiv.org/pdf/1602.03043), [arXiv 2311.18283](https://arxiv.org/pdf/2311.18283)).
- Charge commissions, spread, borrow, and slippage on *every* simulated fill.

### What QuantCore lacks
The paper loop opens/closes at observed prices with (apparently) **no spread, no commission, no slippage, and no market-impact charge.** Crypto on Bybit and small/illiquid stocks via yfinance are exactly where impact and spread bite hardest. **This means paper P&L — which feeds the conviction-learning loop — is systematically inflated, so the system is learning from biased rewards.**

### Recommendation
- **Tier 1:** Add a **transaction-cost model** to every paper fill: half-spread + fixed commission/bps + a square-root impact term keyed to the symbol's ATR and average volume. Even rough numbers stop the learning loop from over-rewarding high-churn, illiquid setups. This is the **highest-leverage single fix** because it corrects the reward signal everything else learns from.
- **Tier 2:** Model **fill realism** — assume entry at next-bar open (not signal-bar close) plus half-spread, to remove the implicit look-ahead of same-bar fills.
- **Tier 2:** Add a **liquidity gate** — skip/penalize setups whose intended size exceeds a % of ADV.

---

## 5. Data Quality

### What institutional desks do
They use **point-in-time (PIT)** databases: each datum is stamped with the date it was actually knowable, financial statements appear only after their real reporting date, and the universe includes delisted/merged/bankrupt names.

- **Survivorship bias** (dropping defunct tickers) overstates annual returns by ~1–4% and flatters Sharpe and drawdown ([LuxAlgo](https://www.luxalgo.com/blog/survivorship-bias-in-backtesting-explained/), [QuantifiedStrategies](https://www.quantifiedstrategies.com/survivorship-bias-in-backtesting/)).
- **Look-ahead bias** — using data not yet released; **financial-statement restatements** are a classic instance, because the value you see today differs from what was reported then ([AnalystPrep](https://analystprep.com/study-notes/cfa-level-2/problems-in-backtesting/), DB/Hudson & Thames *Seven Sins of Quantitative Investing*: [PDF](https://hudsonthames.org/wp-content/uploads/2022/01/DB-201409-Seven_Sins_of_Quantitative_Investing.pdf)).

### What QuantCore lacks
- **yfinance fundamentals are point-in-time-unsafe**: they return *latest/restated* values with no as-of date. Any backtest of the Analyst's fundamental scoring against history is contaminated by look-ahead and restatement bias.
- yfinance equity history is **survivorship-biased** — delisted names are gone, so backtests only see winners.
- The Analyst blends a Claude fundamental score (7 dimensions) into conviction with no guarantee the inputs were knowable at the simulated date.

### Recommendation
- **Tier 1:** **Quarantine fundamentals from any backtest.** Use the Claude/yfinance fundamental score for *live, forward* decisions only, and explicitly label it non-backtestable. Mark this clearly in code/docs so no one validates on it.
- **Tier 2:** For price backtests, source a **survivorship-bias-free** universe (include delisted tickers) — even a static historical constituent list with delisted names beats today's survivors-only set.
- **Tier 3:** Move fundamentals onto a **point-in-time** vendor (e.g., a PIT feed with as-reported + as-of dates) to make fundamental signals genuinely backtestable.

---

## 6. Signal Ensembling

### What institutional desks do
Rather than maintaining momentum, mean-reversion, and macro as parallel lists, desks **combine them into one coherent allocation**.

- **Meta-labeling** (López de Prado, 2017): separate *side* (the primary model's direction) from *size* (a secondary classifier that predicts whether a given signal will be profitable, sizing or vetoing accordingly). It suppresses false positives and sizes by confidence, and is widely used by multi-manager systematic shops ([Wikipedia: Meta-Labeling](https://en.wikipedia.org/wiki/Meta-Labeling), [Hudson & Thames: Does Meta-Labeling Add to Signal Efficacy?](https://hudsonthames.org/wp-content/uploads/2022/04/Does-Meta-Labeling-Add-to-Signal-Efficacy.pdf)).
- Classifiers combine in **serial / conditional / hybrid / parallel** arrangements; meta-labeling over a momentum + Bollinger mean-reversion combo (with triple-barrier labels and event-based sampling) improves performance. It is *not* a silver bullet — it only helps when the primary signal already has edge ([QuantConnect](https://www.quantconnect.com/forum/discussion/14706/why-meta-labeling-is-not-a-silver-bullet/)).

### What QuantCore lacks
The scanner produces **parallel lists** (momentum setups, mean-reversion setups) gated by the macro regime, but there's no unified model that says "given macro state X, this RSI-2 signal on this name has Y% chance of hitting target before stop, so size it Z." The conviction score is heuristic, not a calibrated probability.

### Recommendation
- **Tier 2:** Build a **meta-labeling layer**: keep the current scanner as the *primary* side model, and train a secondary classifier on labeled outcomes (triple-barrier: target / stop / timeout) using macro state, setup type, RSI-2, ATR, and trailing correlation as features. Its output is a **calibrated probability of success** that replaces the heuristic conviction multiplier — and naturally fuses momentum + mean-reversion + macro into one number. (Reuses the paper-trade outcomes you already record as training labels.)
- **Tier 1 (precursor):** Adopt **triple-barrier labeling** for paper trades now, so you accumulate clean, meta-labeling-ready training data even before building the model.

---

## 7. Monitoring

### What institutional desks do
- **Signal decay detection** — track each signal's hit rate / alpha over rolling and out-of-sample windows; declining hit rate, rising drawdown, or shrinking alpha flag a decaying signal ([Wright Research: Signal Decay](https://www.wrightresearch.in/quant-glossary/signal-decay/)).
- **Regime-change alerts** — detect regime shifts in real time and adjust thresholds/cooldowns/sizing accordingly.
- **Performance attribution** — decompose realized P&L by setup type, sector, regime, and signal so you know *what* is working, not just *that* the book is up.

### What QuantCore lacks
The per-setup profit-factor feedback is a primitive form of decay tracking, but there's **no statistical decay alert, no regime-transition notification, and no P&L attribution** by setup / sector / macro state.

### Recommendation
- **Tier 1:** Add **per-setup-family performance attribution** to the paper-trading dashboard — realized P&L and hit rate sliced by setup type, asset class, and the macro regime in force at entry. Mostly aggregation over data you already store.
- **Tier 1:** Add a **signal-decay alert**: rolling hit rate / profit factor with a control band; fire when a setup family drops below its historical lower bound for N consecutive windows, and auto-throttle its conviction.
- **Tier 2:** **Regime-transition alerts** when the Deployment Score crosses regime boundaries, with a log of how each setup family historically performed in the *new* regime.

---

## Next 5 Things to Build (in priority order)

1. **Transaction-cost & slippage model on every paper fill** (half-spread + commission + √-impact). — Fixes the biased reward signal the entire learning loop trains on; without it, every downstream metric overstates edge. *Highest leverage, low effort.*
2. **Walk-forward + holdout harness with Deflated Sharpe Ratio** around conviction/threshold tuning. — Stops in-sample conviction tuning from manufacturing fake edge; gives a multiple-testing-honest "validated / not validated" gate before anything auto-trades.
3. **Portfolio drawdown governor + regime-conditional leverage scalar** (reuse the macro Deployment Score). — Adds the portfolio-level risk control the system completely lacks today, using infrastructure you already have.
4. **Correlation-aware position sizing** (cap/scale new setups against open-position correlation). — Closes the "8 longs that are secretly one beta bet" gap; cheap precursor to full HRP.
5. **Triple-barrier labeling + per-setup performance attribution & decay alerts.** — Two-for-one: makes monitoring genuinely institutional *and* lays the labeled-data foundation for a later meta-labeling model (#6 territory).

These five convert QuantCore from "optimistic single-name signal generator" into a system whose backtests, rewards, and risk controls are honest — the prerequisite for everything more advanced (HRP, CPCV/PBO, meta-labeling, PIT fundamentals).
