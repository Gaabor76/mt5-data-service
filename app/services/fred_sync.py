"""FRED data fetching, CSV import, and score recalculation service."""

import csv
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.database import MacroDaily
from app.services.macro_score import calculate_dxy_percentile, calculate_macro_score

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FRED CSV download (no API key required)
# ---------------------------------------------------------------------------

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

FRED_SERIES = {
    "us10y": "DGS10",
    "us02y": "DGS2",
    "t5yie": "T5YIE",
    "ffr": "DFEDTARU",
}

# Maps series name → macro_daily column
SERIES_COLUMN_MAP = {
    "us10y": "us10y",
    "us02y": "us02y",
    "t5yie": "t5yie",
    "ffr": "ffr",
    "dxy": "dxy_close",
}


async def fetch_fred_series(
    series_id: str,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Download a FRED series as CSV and parse it. No API key needed."""
    params = {
        "id": series_id,
        "cosd": start_date.isoformat(),
        "coed": end_date.isoformat(),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(FRED_CSV_URL, params=params, timeout=30)
        resp.raise_for_status()

    reader = csv.DictReader(StringIO(resp.text))
    results = []
    for row in reader:
        val = row.get(series_id, "").strip()
        if val and val != ".":
            results.append({
                "date": row["DATE"],
                "value": float(val),
            })
    return results


async def sync_fred_data(
    start_date: date,
    end_date: date,
    db: Session,
) -> dict:
    """Fetch all 4 FRED series and upsert into macro_daily."""
    total_upserted = 0
    errors = []

    for series_name, fred_id in FRED_SERIES.items():
        try:
            rows = await fetch_fred_series(fred_id, start_date, end_date)
            col = SERIES_COLUMN_MAP[series_name]
            for row in rows:
                row_date = date.fromisoformat(row["date"])
                stmt = pg_insert(MacroDaily).values(
                    date=row_date,
                    **{col: row["value"]},
                    source="fred",
                ).on_conflict_do_update(
                    index_elements=["date"],
                    set_={col: row["value"], "updated_at": datetime.utcnow()},
                )
                db.execute(stmt)
            total_upserted += len(rows)
            logger.info("FRED sync: %s (%s) → %d rows", series_name, fred_id, len(rows))
        except Exception as e:
            msg = f"FRED sync failed for {series_name} ({fred_id}): {e}"
            logger.error(msg)
            errors.append(msg)

    db.commit()
    return {"upserted": total_upserted, "errors": errors}


# ---------------------------------------------------------------------------
# CSV import (TradingView & FRED formats)
# ---------------------------------------------------------------------------

def import_csv(
    file_content: bytes,
    series_name: str,
    db: Session,
) -> dict:
    """Import a CSV file for a given series into macro_daily.

    Supports two formats:
    - TradingView: time,open,high,low,close,...  (used for DXY, US10Y, US02Y)
    - FRED:        time,close,...                 (used for T5YIE, FFR)

    For DXY, also imports high/low columns (needed for percentile calculation).
    """
    text_content = file_content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(StringIO(text_content))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]

    imported = 0
    skipped = 0
    errors = []

    is_ohlc = "open" in headers and "high" in headers and "low" in headers
    is_dxy = series_name == "dxy"

    for row_num, row in enumerate(reader, start=2):
        try:
            # Normalise keys to lowercase
            row = {k.strip().lower(): v.strip() for k, v in row.items()}

            date_str = row.get("time", "")
            if not date_str:
                skipped += 1
                continue

            # Parse date: handle both "2019-07-30" and "2019-07-30T00:00:00"
            row_date = date.fromisoformat(date_str.split("T")[0])

            close_val = row.get("close", "").strip()
            if not close_val or close_val == ".":
                skipped += 1
                continue
            close_val = float(close_val)

            if is_dxy:
                values = {
                    "date": row_date,
                    "dxy_close": close_val,
                    "dxy_high": float(row["high"]) if is_ohlc and row.get("high") else None,
                    "dxy_low": float(row["low"]) if is_ohlc and row.get("low") else None,
                    "source": "csv_import",
                }
                update_set = {
                    "dxy_close": close_val,
                    "dxy_high": values["dxy_high"],
                    "dxy_low": values["dxy_low"],
                    "updated_at": datetime.utcnow(),
                }
            else:
                col = SERIES_COLUMN_MAP.get(series_name)
                if not col:
                    errors.append(f"Unknown series: {series_name}")
                    break
                values = {
                    "date": row_date,
                    col: close_val,
                    "source": "csv_import",
                }
                update_set = {
                    col: close_val,
                    "updated_at": datetime.utcnow(),
                }

            stmt = pg_insert(MacroDaily).values(**values).on_conflict_do_update(
                index_elements=["date"],
                set_=update_set,
            )
            db.execute(stmt)
            imported += 1

        except Exception as e:
            errors.append(f"Row {row_num}: {e}")
            if len(errors) > 50:
                errors.append("Too many errors, stopping import.")
                break

    db.commit()
    logger.info("CSV import '%s': imported=%d, skipped=%d, errors=%d",
                series_name, imported, skipped, len(errors))
    return {"imported": imported, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Score recalculation
# ---------------------------------------------------------------------------

def recalculate_scores(
    start_date: date,
    end_date: date,
    db: Session,
) -> int:
    """Recalculate all derived fields for macro_daily rows in the date range.

    Needs at least 60 days of DXY data before start_date for percentile.
    """
    # Pre-fetch all DXY data for percentile lookback
    all_dxy = (
        db.query(MacroDaily.date, MacroDaily.dxy_close, MacroDaily.dxy_high, MacroDaily.dxy_low)
        .filter(MacroDaily.dxy_close.isnot(None))
        .order_by(MacroDaily.date)
        .all()
    )
    dxy_by_date = {row.date: row for row in all_dxy}
    dxy_dates_sorted = sorted(dxy_by_date.keys())

    rows = (
        db.query(MacroDaily)
        .filter(MacroDaily.date >= start_date, MacroDaily.date <= end_date)
        .order_by(MacroDaily.date)
        .all()
    )

    updated = 0
    for row in rows:
        us10y = _to_float(row.us10y)
        us02y = _to_float(row.us02y)
        t5yie = _to_float(row.t5yie)
        ffr = _to_float(row.ffr)

        # Default FFR for pre-2021-06 data
        if ffr is None:
            ffr = 0.25

        # Skip if we don't have minimum required data
        if us10y is None or us02y is None or t5yie is None:
            continue

        # Calculate DXY percentile using 60-day lookback
        dxy_pct = 50.0  # default
        dxy_close = _to_float(row.dxy_close)
        if dxy_close is not None:
            # Find index of current date in sorted DXY dates
            idx = _bisect_date(dxy_dates_sorted, row.date)
            # Grab up to 60 prior trading days
            lookback_start = max(0, idx - 60)
            lookback_dates = dxy_dates_sorted[lookback_start:idx + 1]
            if len(lookback_dates) >= 5:  # need reasonable sample
                highs = [_to_float(dxy_by_date[d].dxy_high) or _to_float(dxy_by_date[d].dxy_close)
                         for d in lookback_dates]
                lows = [_to_float(dxy_by_date[d].dxy_low) or _to_float(dxy_by_date[d].dxy_close)
                        for d in lookback_dates]
                highs = [h for h in highs if h is not None]
                lows = [lo for lo in lows if lo is not None]
                if highs and lows:
                    dxy_pct = calculate_dxy_percentile(dxy_close, highs, lows)

        cb_trend = "NEUTRAL"  # automated default
        scores = calculate_macro_score(us10y, us02y, t5yie, ffr, dxy_pct, cb_trend)

        row.real_rate = scores["real_rate"]
        row.yield_curve = scores["yield_curve"]
        row.fed_spread = scores["fed_spread"]
        row.dxy_percentile = round(dxy_pct, 2)
        row.realrate_score = scores["realrate_score"]
        row.dxy_score = scores["dxy_score"]
        row.yc_score = scores["yc_score"]
        row.fed_score = scores["fed_score"]
        row.cb_score = scores["cb_score"]
        row.macro_score_raw = scores["macro_score_raw"]
        row.macro_score_pct = scores["macro_score_pct"]
        row.macro_bias = scores["macro_bias"]
        row.updated_at = datetime.utcnow()
        updated += 1

    db.commit()
    logger.info("Recalculated scores for %d rows (%s → %s)", updated, start_date, end_date)
    return updated


async def check_fred_health() -> bool:
    """Quick connectivity check to FRED."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                FRED_CSV_URL,
                params={"id": "DGS10", "cosd": "2025-01-01", "coed": "2025-01-02"},
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(val) -> float | None:
    """Safely convert Decimal/float/None to float."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _bisect_date(sorted_dates: list[date], target: date) -> int:
    """Binary search for target date in sorted list. Returns closest index."""
    lo, hi = 0, len(sorted_dates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_dates[mid] == target:
            return mid
        elif sorted_dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return min(lo, len(sorted_dates) - 1)
