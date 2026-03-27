"""Pure macro score calculation logic – mirrors the Pine Script v8 indicator exactly.

Zero I/O, fully testable. All functions are stateless.
"""

# Component weights (configurable defaults from backtest optimisation)
W_REALRATE = 1.5
W_DXY = 1.2
W_FED = 0.8
W_CB = 1.2
W_YC = 0.8

BIAS_LABELS = {
    -2: "STRONG SHORT",
    -1: "SHORT",
    0: "NEUTRAL",
    1: "LONG",
    2: "STRONG LONG",
}


def calculate_dxy_percentile(
    dxy_close: float,
    dxy_highs_60d: list[float],
    dxy_lows_60d: list[float],
) -> float:
    """Where DXY sits within its 60-trading-day high/low range (0-100)."""
    if not dxy_highs_60d or not dxy_lows_60d:
        return 50.0
    hi = max(dxy_highs_60d)
    lo = min(dxy_lows_60d)
    rng = hi - lo
    if rng <= 0:
        return 50.0
    return (dxy_close - lo) / rng * 100


def calculate_macro_score(
    us10y: float,
    us02y: float,
    t5yie: float,
    ffr: float,
    dxy_percentile: float,
    cb_trend: str = "NEUTRAL",
) -> dict:
    """Calculate all macro-derived fields from raw inputs.

    Returns dict with: real_rate, yield_curve, fed_spread, component scores,
    macro_score_raw, macro_score_pct, macro_bias.
    """
    real_rate = us10y - t5yie
    yield_curve = us10y - us02y
    fed_spread = us02y - ffr

    # --- Real rate score (-2 to +2): low/negative = gold bullish ---
    if real_rate < 0:
        rr_score = 2
    elif real_rate < 0.5:
        rr_score = 1
    elif real_rate < 1.5:
        rr_score = 0
    elif real_rate < 2.5:
        rr_score = -1
    else:
        rr_score = -2

    # --- DXY score (-2 to +2): weak DXY = gold bullish ---
    if dxy_percentile > 85:
        d_score = -2
    elif dxy_percentile > 70:
        d_score = -1
    elif dxy_percentile < 15:
        d_score = 2
    elif dxy_percentile < 30:
        d_score = 1
    else:
        d_score = 0

    # --- Yield curve score (-1 to +1): inverted = recession fear = gold bullish ---
    if yield_curve < -0.5:
        yc_score = 1
    elif yield_curve > 1.0:
        yc_score = -1
    else:
        yc_score = 0

    # --- FED score (-2 to +2): negative spread = rate cut expected = gold bullish ---
    if fed_spread < -1.0:
        f_score = 2
    elif fed_spread < -0.5:
        f_score = 1
    elif fed_spread > 0.5:
        f_score = -2
    elif fed_spread > 0.2:
        f_score = -1
    else:
        f_score = 0

    # --- CB buying score (-1 to +1) ---
    cb_score = 1 if cb_trend == "INCREASING" else (-1 if cb_trend == "DECREASING" else 0)

    # --- Weighted composite ---
    score_raw = (
        rr_score * W_REALRATE
        + d_score * W_DXY
        + f_score * W_FED
        + cb_score * W_CB
        + yc_score * W_YC
    )
    max_possible = 2 * W_REALRATE + 2 * W_DXY + 2 * W_FED + 1 * W_CB + 1 * W_YC
    score_pct = (score_raw + max_possible) / (2 * max_possible) * 100

    # --- Macro bias ---
    if score_pct >= 75:
        bias = 2   # STRONG LONG
    elif score_pct >= 60:
        bias = 1   # LONG
    elif score_pct <= 25:
        bias = -2  # STRONG SHORT
    elif score_pct <= 40:
        bias = -1  # SHORT
    else:
        bias = 0   # NEUTRAL

    return {
        "real_rate": round(real_rate, 4),
        "yield_curve": round(yield_curve, 4),
        "fed_spread": round(fed_spread, 4),
        "realrate_score": rr_score,
        "dxy_score": d_score,
        "yc_score": yc_score,
        "fed_score": f_score,
        "cb_score": cb_score,
        "macro_score_raw": round(score_raw, 2),
        "macro_score_pct": round(score_pct, 2),
        "macro_bias": bias,
    }


def bias_label(bias: int) -> str:
    """Human-readable label for a macro_bias value."""
    return BIAS_LABELS.get(bias, "NEUTRAL")
