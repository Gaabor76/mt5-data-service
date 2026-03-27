"""Macro daily data endpoints – FRED sync, CSV import, and data retrieval."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import MacroDaily, get_db
from app.models.schemas import (
    MacroComponents,
    MacroHealthResponse,
    MacroHistoryResponse,
    MacroImportResponse,
    MacroLatestResponse,
    MacroMultipliers,
    MacroDailyRecord,
    MacroSyncRequest,
)
from app.services.fred_sync import (
    check_fred_health,
    import_csv,
    recalculate_scores,
    sync_fred_data,
)
from app.services.macro_score import bias_label

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/macro", tags=["macro"])


def _to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _row_to_record(row: MacroDaily) -> MacroDailyRecord:
    return MacroDailyRecord(
        date=row.date.isoformat(),
        dxy_close=_to_float(row.dxy_close),
        dxy_high=_to_float(row.dxy_high),
        dxy_low=_to_float(row.dxy_low),
        us10y=_to_float(row.us10y),
        us02y=_to_float(row.us02y),
        t5yie=_to_float(row.t5yie),
        ffr=_to_float(row.ffr),
        real_rate=_to_float(row.real_rate),
        yield_curve=_to_float(row.yield_curve),
        fed_spread=_to_float(row.fed_spread),
        dxy_percentile=_to_float(row.dxy_percentile),
        realrate_score=row.realrate_score,
        dxy_score=row.dxy_score,
        yc_score=row.yc_score,
        fed_score=row.fed_score,
        cb_score=row.cb_score,
        macro_score_raw=_to_float(row.macro_score_raw),
        macro_score_pct=_to_float(row.macro_score_pct),
        macro_bias=row.macro_bias,
        source=row.source,
    )


# ------------------------------------------------------------------
# GET /api/macro/latest – called by the MT5 EA
# ------------------------------------------------------------------

@router.get("/latest", response_model=MacroLatestResponse)
async def get_latest(db: Session = Depends(get_db)):
    """Return the most recent macro_daily record with bias & multipliers."""
    row = db.query(MacroDaily).order_by(MacroDaily.date.desc()).first()
    if not row:
        return MacroLatestResponse()

    # Data age in hours
    now = datetime.utcnow()
    row_dt = datetime.combine(row.date, datetime.min.time())
    data_age_hours = round((now - row_dt).total_seconds() / 3600, 1)

    return MacroLatestResponse(
        date=row.date.isoformat(),
        macro_bias=row.macro_bias,
        macro_bias_str=bias_label(row.macro_bias) if row.macro_bias is not None else None,
        macro_score_pct=_to_float(row.macro_score_pct),
        macro_score_raw=_to_float(row.macro_score_raw),
        multipliers=MacroMultipliers(),
        components=MacroComponents(
            real_rate=_to_float(row.real_rate),
            dxy_percentile=_to_float(row.dxy_percentile),
            yield_curve=_to_float(row.yield_curve),
            fed_spread=_to_float(row.fed_spread),
            realrate_score=row.realrate_score,
            dxy_score=row.dxy_score,
            yc_score=row.yc_score,
            fed_score=row.fed_score,
            cb_score=row.cb_score,
        ),
        data_age_hours=data_age_hours,
    )


# ------------------------------------------------------------------
# GET /api/macro/history?days=30
# ------------------------------------------------------------------

@router.get("/history", response_model=MacroHistoryResponse)
async def get_history(days: int = 30, db: Session = Depends(get_db)):
    """Return the last N days of macro_daily records."""
    if days < 1 or days > 3000:
        raise HTTPException(status_code=400, detail="days must be between 1 and 3000")

    rows = (
        db.query(MacroDaily)
        .order_by(MacroDaily.date.desc())
        .limit(days)
        .all()
    )
    records = [_row_to_record(r) for r in reversed(rows)]
    return MacroHistoryResponse(count=len(records), records=records)


# ------------------------------------------------------------------
# POST /api/macro/sync – trigger FRED fetch for a date range
# ------------------------------------------------------------------

@router.post("/sync", response_model=MacroImportResponse)
async def trigger_sync(req: MacroSyncRequest, db: Session = Depends(get_db)):
    """Fetch FRED data for the specified date range and recalculate scores."""
    try:
        start = date.fromisoformat(req.start_date)
        end = date.fromisoformat(req.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    result = await sync_fred_data(start, end, db)
    updated = recalculate_scores(start, end, db)

    return MacroImportResponse(
        imported=result["upserted"],
        skipped=0,
        errors=result["errors"],
    )


# ------------------------------------------------------------------
# POST /api/macro/import-csv – upload historical CSV
# ------------------------------------------------------------------

@router.post("/import-csv", response_model=MacroImportResponse)
async def import_csv_endpoint(
    series: str = Form(..., description="One of: dxy, us10y, us02y, t5yie, ffr"),
    file: UploadFile = File(...),
    recalculate: bool = Form(True, description="Recalculate scores after import"),
    db: Session = Depends(get_db),
):
    """Import a historical CSV file for a given macro series."""
    valid_series = {"dxy", "us10y", "us02y", "t5yie", "ffr"}
    if series not in valid_series:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid series '{series}'. Must be one of: {', '.join(sorted(valid_series))}",
        )

    content = await file.read()
    result = import_csv(content, series, db)

    if recalculate and result["imported"] > 0:
        # Recalculate across all data
        earliest = db.query(func.min(MacroDaily.date)).scalar()
        latest = db.query(func.max(MacroDaily.date)).scalar()
        if earliest and latest:
            recalculate_scores(earliest, latest, db)

    return MacroImportResponse(**result)


# ------------------------------------------------------------------
# GET /api/macro/health
# ------------------------------------------------------------------

@router.get("/health", response_model=MacroHealthResponse)
async def health(db: Session = Depends(get_db)):
    """Check FRED connectivity and last sync status."""
    fred_ok = await check_fred_health()

    last_date = db.query(func.max(MacroDaily.date)).scalar()
    total = db.query(func.count(MacroDaily.id)).scalar() or 0

    return MacroHealthResponse(
        fred_reachable=fred_ok,
        last_sync_date=last_date.isoformat() if last_date else None,
        total_records=total,
    )
