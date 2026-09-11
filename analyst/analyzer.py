"""
Claude API Analyst Layer (L3)
- Chain-of-Thought reasoning
- Self-critique pass
- Consistency scoring
- 7 dimensions: Earnings Quality, Growth Trajectory, Balance Sheet Health,
  Margin Trends, Red Flags, Competitive Moat, Management Allocation
"""
from __future__ import annotations
import json
import re
from datetime import datetime
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from analyst.cache import get_analyst, set_analyst
from utils.logger import get_logger

log = get_logger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


_SYSTEM_PROMPT = """\
You are a senior equity research analyst at a top-tier hedge fund. \
You are rigorous, data-driven, and intellectually honest. You flag risks \
as prominently as opportunities. You score companies strictly on the merits \
of their financial data, not market consensus."""

_ANALYSIS_PROMPT = """\
Analyze the following fundamental data for {ticker} ({name}, {sector}).

## Quarterly Data (most recent first, up to 8 quarters)
{quarterly_table}

## TTM (Trailing Twelve Months)
{ttm_table}

## Key Ratios
{ratios_table}

## Peer Benchmarks vs {sector} sector (percentile rank = higher is better, except Debt/Equity)
{peer_table}

---

**Instructions — follow exactly in order:**

### Step 1 — Chain-of-Thought Analysis
Think through each of the 7 dimensions below. For each, note 2-3 specific \
data points from the table above that support your conclusion. Show your reasoning.

Dimensions:
1. **Earnings Quality** (1-10): Is net income backed by cash flow? CFO/NI ratio, \
   AR divergence from revenue growth.
2. **Growth Trajectory** (1-10): Revenue and profit growth trend. Acceleration or \
   deceleration? Quality of growth.
3. **Balance Sheet Health** (1-10): Debt/equity, current ratio, equity trend.
4. **Margin Trends** (1-10): Gross/operating/net margin direction over 8 quarters.
5. **Red Flags** (1-10, where 10 = NO red flags): Channel stuffing, \
   aggressive accruals, unusual AR build, deteriorating FCF.
6. **Competitive Moat** (1-10): Do margins hold under pressure? Pricing power \
   evidence, R&D/capex investment pattern.
7. **Management Capital Allocation** (1-10): FCF deployment — buybacks, dividends, \
   capex efficiency, debt paydown vs growth investment.

### Step 2 — Self-Critique
Review your reasoning above. Challenge your most optimistic and most pessimistic \
assessments. Would a bear make a strong counter-argument? Adjust any scores if warranted.

### Step 3 — Consistency Check
Are your 7 scores internally consistent? (e.g., high earnings quality but low \
red flags score would be contradictory.) Flag any inconsistencies and resolve them.

Do your full chain-of-thought reasoning, self-critique, and consistency check \
in your thinking. Then return the final scored assessment — each score an \
integer 1-10, `composite_score` a weighted average, `bull_case`/`bear_case` \
2-3 sentences, `key_risks` a list of 2-4 items, `reasoning_summary` a 3-4 \
sentence synthesis. The output schema is enforced; output only the result.
"""


# Structured-output schema — guarantees valid, parseable JSON and removes the
# need to write the verbose JSON template (and a fragile regex) into the prompt.
# additionalProperties:false is required on every object by structured outputs.
_ANALYST_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "earnings_quality":  {"type": "integer"},
                "growth_trajectory": {"type": "integer"},
                "balance_sheet":     {"type": "integer"},
                "margin_trends":     {"type": "integer"},
                "red_flags":         {"type": "integer"},
                "competitive_moat":  {"type": "integer"},
                "mgmt_allocation":   {"type": "integer"},
            },
            "required": [
                "earnings_quality", "growth_trajectory", "balance_sheet",
                "margin_trends", "red_flags", "competitive_moat", "mgmt_allocation",
            ],
            "additionalProperties": False,
        },
        "composite_score":    {"type": "number"},
        "consistency_rating": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "bull_case":          {"type": "string"},
        "bear_case":          {"type": "string"},
        "key_risks":          {"type": "array", "items": {"type": "string"}},
        "reasoning_summary":  {"type": "string"},
    },
    "required": [
        "scores", "composite_score", "consistency_rating",
        "bull_case", "bear_case", "key_risks", "reasoning_summary",
    ],
    "additionalProperties": False,
}


def analyze(ticker: str, fundamentals: dict, peer_data: dict,
            force: bool = False) -> dict:
    ticker = ticker.upper()

    # Cache key based on latest quarter
    quarters = fundamentals.get("quarters", [])
    quarter_end = quarters[0]["period"] if quarters else "unknown"

    if not force:
        cached = get_analyst(ticker, quarter_end)
        if cached:
            log.info("Analyst cache hit: %s / %s", ticker, quarter_end)
            return cached

    if not ANTHROPIC_API_KEY:
        return _fallback(ticker, "No API key configured")

    prompt = _build_prompt(ticker, fundamentals, peer_data)

    try:
        log.info("Calling Claude for %s …", ticker)
        client = _get_client()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,                       # ceiling — covers thinking + JSON
            system=_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},          # reason privately, emit compact JSON
            output_config={
                "effort": "medium",                 # balance: full reasoning, ~30% cheaper than visible CoT
                "format": {"type": "json_schema", "schema": _ANALYST_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        # With structured outputs the final text block is guaranteed-valid JSON;
        # skip any thinking blocks that precede it.
        raw_text = next((b.text for b in response.content if b.type == "text"), "")
        result = _parse_response(raw_text, ticker)
        result["quarter_end"] = quarter_end
        result["model"] = CLAUDE_MODEL
        result["analyzed_at"] = datetime.utcnow().isoformat()
        set_analyst(ticker, quarter_end, result)
        return result

    except Exception as exc:
        log.error("Claude analysis failed for %s: %s", ticker, exc)
        return _fallback(ticker, str(exc))


def _build_prompt(ticker: str, data: dict, peer: dict) -> str:
    quarters = data.get("quarters", [])
    ttm = data.get("ttm", {})
    ratios = data.get("ratios", {})

    def fmt_row(label: str, key: str, multiplier: float = 1e-6, suffix: str = "M") -> str:
        vals = []
        for q in quarters[:8]:
            v = q.get(key)
            if v is None:
                vals.append("N/A")
            elif suffix in ("%",):
                vals.append(f"{v*100:.1f}%")
            else:
                vals.append(f"${v*multiplier:,.0f}{suffix}")
        return f"| {label} | " + " | ".join(vals) + " |"

    def fmt_pct_row(label: str, key: str) -> str:
        vals = []
        for q in quarters[:8]:
            v = q.get(key)
            vals.append(f"{v*100:.1f}%" if v is not None else "N/A")
        return f"| {label} | " + " | ".join(vals) + " |"

    headers = "| Metric | " + " | ".join(q["period"] for q in quarters[:8]) + " |"
    sep = "| --- |" + " --- |" * min(8, len(quarters))

    quarterly_table = "\n".join([
        headers, sep,
        fmt_row("Revenue", "revenue"),
        fmt_row("Net Income", "net_income"),
        fmt_row("CFO", "cfo"),
        fmt_row("FCF", "fcf"),
        fmt_pct_row("Gross Margin", "gross_margin"),
        fmt_pct_row("Op Margin", "operating_margin"),
        fmt_pct_row("Net Margin", "net_margin"),
        fmt_pct_row("CFO/NI Ratio", "cfo_ni_ratio"),
    ])

    def ttm_val(key: str, pct: bool = False) -> str:
        v = ttm.get(key)
        if v is None:
            return "N/A"
        if pct:
            return f"{v*100:.1f}%"
        return f"${v/1e6:,.0f}M"

    ttm_table = (
        f"Revenue: {ttm_val('revenue')} | "
        f"Net Income: {ttm_val('net_income')} | "
        f"CFO: {ttm_val('cfo')} | FCF: {ttm_val('fcf')} | "
        f"Gross Margin: {ttm_val('gross_margin', True)} | "
        f"Op Margin: {ttm_val('operating_margin', True)} | "
        f"Net Margin: {ttm_val('net_margin', True)}"
    )

    def r(k, pct=False):
        v = ratios.get(k)
        if v is None:
            return "N/A"
        return f"{v*100:.1f}%" if pct else f"{v:.2f}"

    ratios_table = (
        f"ROE: {r('roe', True)} | ROA: {r('roa', True)} | "
        f"Current Ratio: {r('current_ratio')} | P/E: {r('pe_ratio')} | "
        f"EV/EBITDA: {r('ev_ebitda')} | "
        f"AR/Rev Divergence: {r('ar_rev_divergence', True)}"
    )

    peer_rankings = peer.get("rankings", {})
    peer_lines = []
    for metric, info in peer_rankings.items():
        pct_rank = info.get("percentile_rank")
        val = info.get("value")
        med = info.get("peer_median")
        if pct_rank is not None:
            v_str = f"{val*100:.1f}%" if val is not None else "N/A"
            m_str = f"{med*100:.1f}%" if med is not None else "N/A"
            peer_lines.append(
                f"{metric}: {v_str} vs peer median {m_str} | Percentile: {pct_rank:.0f}th"
            )
    peer_table = "\n".join(peer_lines) if peer_lines else "Peer data unavailable"

    return _ANALYSIS_PROMPT.format(
        ticker=ticker,
        name=data.get("name", ticker),
        sector=data.get("sector", "Unknown"),
        quarterly_table=quarterly_table,
        ttm_table=ttm_table,
        ratios_table=ratios_table,
        peer_table=peer_table,
    )


def _parse_response(text: str, ticker: str) -> dict:
    # Extract JSON block — handle markdown fences
    json_match = re.search(r"\{[\s\S]+\}", text)
    if not json_match:
        return _fallback(ticker, "No JSON found in response")
    try:
        data = json.loads(json_match.group())
        scores = data.get("scores", {})
        # Compute composite if missing
        if "composite_score" not in data or not data["composite_score"]:
            weights = {
                "earnings_quality": 0.20,
                "growth_trajectory": 0.20,
                "balance_sheet":     0.15,
                "margin_trends":     0.15,
                "red_flags":         0.15,
                "competitive_moat":  0.10,
                "mgmt_allocation":   0.05,
            }
            composite = sum(scores.get(k, 5) * w for k, w in weights.items())
            data["composite_score"] = round(composite, 2)
        return data
    except json.JSONDecodeError as exc:
        return _fallback(ticker, f"JSON parse error: {exc}")


def _fallback(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker,
        "scores": {k: 5 for k in [
            "earnings_quality", "growth_trajectory", "balance_sheet",
            "margin_trends", "red_flags", "competitive_moat", "mgmt_allocation",
        ]},
        "composite_score": 5.0,
        "consistency_rating": "Low",
        "bull_case": "Analysis unavailable.",
        "bear_case": "Analysis unavailable.",
        "key_risks": ["Analysis unavailable"],
        "reasoning_summary": f"Fallback: {reason}",
        "error": reason,
    }
