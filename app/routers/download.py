"""Download endpoints – tick data and OHLCV rates with background job processing."""

import threading
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.database import get_db, DownloadJob, TickData, RateData
from app.models.schemas import (
    DownloadTicksRequest, DownloadRatesRequest,
    JobStatusResponse, JobListResponse,
    DataRangeResponse, DataRangeRequest,
)
from app.services.mt5_service import mt5_service
from app.services.crypto import encrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/download", tags=["download"])


# ------------------------------------------------------------------
# Submit download jobs
# ------------------------------------------------------------------

@router.post("/ticks", response_model=JobStatusResponse)
async def submit_tick_download(req: DownloadTicksRequest, db: Session = Depends(get_db)):
    """
    Submit a tick data download job.
    The download runs in the background – poll /jobs/{id} for progress.
    """
    # Create job record
    job = DownloadJob(
        user_id=req.user_id,
        broker_server=req.broker_server,
        broker_login=encrypt(str(req.broker_login)),
        broker_password=encrypt(req.broker_password),
        symbol=req.symbol,
        data_type="ticks",
        date_from=req.date_from,
        date_to=req.date_to,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Run download in background thread
    thread = threading.Thread(
        target=mt5_service.download_ticks,
        kwargs={
            "job_id": job.id,
            "broker_server": req.broker_server,
            "login": req.broker_login,
            "password": req.broker_password,
            "symbol": req.symbol,
            "date_from": req.date_from,
            "date_to": req.date_to,
        },
        daemon=True,
    )
    thread.start()

    logger.info(f"Tick download job submitted: {job.id} for {req.symbol}")
    return _job_to_response(job)


@router.post("/rates", response_model=JobStatusResponse)
async def submit_rate_download(req: DownloadRatesRequest, db: Session = Depends(get_db)):
    """
    Submit an OHLCV rate download job.
    The download runs in the background – poll /jobs/{id} for progress.
    """
    job = DownloadJob(
        user_id=req.user_id,
        broker_server=req.broker_server,
        broker_login=encrypt(str(req.broker_login)),
        broker_password=encrypt(req.broker_password),
        symbol=req.symbol,
        data_type="rates",
        timeframe=req.timeframe.upper(),
        date_from=req.date_from,
        date_to=req.date_to,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(
        target=mt5_service.download_rates,
        kwargs={
            "job_id": job.id,
            "broker_server": req.broker_server,
            "login": req.broker_login,
            "password": req.broker_password,
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "date_from": req.date_from,
            "date_to": req.date_to,
        },
        daemon=True,
    )
    thread.start()

    logger.info(f"Rate download job submitted: {job.id} for {req.symbol} {req.timeframe}")
    return _job_to_response(job)


# ------------------------------------------------------------------
# Job status
# ------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Get the current status and progress of a download job."""
    job = db.query(DownloadJob).filter(DownloadJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List download jobs, optionally filtered by user_id and/or status."""
    query = db.query(DownloadJob)
    if user_id:
        query = query.filter(DownloadJob.user_id == user_id)
    if status:
        query = query.filter(DownloadJob.status == status)

    jobs = query.order_by(DownloadJob.created_at.desc()).limit(limit).all()
    return JobListResponse(jobs=[_job_to_response(j) for j in jobs])


# ------------------------------------------------------------------
# Data range query – what data do we already have?
# ------------------------------------------------------------------

@router.post("/data-range/ticks", response_model=DataRangeResponse)
async def get_tick_data_range(req: DataRangeRequest, db: Session = Depends(get_db)):
    """Check what tick data range is already available in the database."""
    result = db.query(
        func.min(TickData.time_msc),
        func.max(TickData.time_msc),
        func.count(TickData.id),
    ).filter(
        TickData.broker_server == req.broker_server,
        TickData.symbol == req.symbol,
    ).first()

    earliest = datetime.utcfromtimestamp(result[0] / 1000) if result[0] else None
    latest = datetime.utcfromtimestamp(result[1] / 1000) if result[1] else None

    return DataRangeResponse(
        broker_server=req.broker_server,
        symbol=req.symbol,
        data_type="ticks",
        earliest=earliest,
        latest=latest,
        total_records=result[2] or 0,
    )


@router.post("/data-range/rates", response_model=DataRangeResponse)
async def get_rate_data_range(req: DataRangeRequest, db: Session = Depends(get_db)):
    """Check what rate data range is already available in the database."""
    if not req.timeframe:
        raise HTTPException(status_code=400, detail="timeframe is required for rate data range")

    result = db.query(
        func.min(RateData.time),
        func.max(RateData.time),
        func.count(RateData.id),
    ).filter(
        RateData.broker_server == req.broker_server,
        RateData.symbol == req.symbol,
        RateData.timeframe == req.timeframe.upper(),
    ).first()

    earliest = datetime.utcfromtimestamp(result[0]) if result[0] else None
    latest = datetime.utcfromtimestamp(result[1]) if result[1] else None

    return DataRangeResponse(
        broker_server=req.broker_server,
        symbol=req.symbol,
        data_type="rates",
        timeframe=req.timeframe.upper(),
        earliest=earliest,
        latest=latest,
        total_records=result[2] or 0,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _job_to_response(job: DownloadJob) -> JobStatusResponse:
    return JobStatusResponse(
        id=job.id,
        status=job.status,
        progress=job.progress or 0,
        total_records=job.total_records,
        processed_records=job.processed_records or 0,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
