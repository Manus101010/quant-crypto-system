from __future__ import annotations


def score_color(score: float) -> str:
    if score >= 70:
        return "green"
    if score >= 40:
        return "yellow"
    return "red"


def score_pill(score: float, label: str = "") -> str:
    cls = f"score-{score_color(score)}"
    text = f"{score:.0f}" if not label else f"{label}: {score:.0f}"
    return f'<span class="score-pill {cls}">{text}</span>'


def delta_arrow(delta: float) -> str:
    if delta > 0:
        return f'<span class="rank-up">▲ {abs(delta):.0f}</span>'
    if delta < 0:
        return f'<span class="rank-down">▼ {abs(delta):.0f}</span>'
    return '<span class="rank-flat">—</span>'


def pct(val: float, decimals: int = 1) -> str:
    return f"{val * 100:.{decimals}f}%"


def fmt_num(val: float, decimals: int = 2) -> str:
    return f"{val:,.{decimals}f}"
