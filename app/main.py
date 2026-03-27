"""
MT5 Data Service – REST API for downloading historical market data from MetaTrader 5.

Runs on Windows natively alongside the MT5 terminal.
Serves as the data gateway for the TradeLog application on the Synology NAS.
"""

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.database import init_db, SessionLocal, DownloadJob
from app.services.mt5_service import mt5_service
from app.services.fred_sync import sync_fred_data, recalculate_scores
from app.routers.broker import router as broker_router
from app.routers.download import router as download_router
from app.routers.trades import router as trades_router
from app.routers.macro import router as macro_router
from app.models.schemas import HealthResponse

# Logging setup
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


scheduler = AsyncIOScheduler()


async def daily_macro_sync():
    """Scheduled job: fetch last 7 days of FRED data and recalculate scores."""
    logger.info("Daily macro sync starting...")
    db = SessionLocal()
    try:
        today = date.today()
        start = today - timedelta(days=7)
        await sync_fred_data(start, today, db)
        recalculate_scores(start, today, db)
        logger.info("Daily macro sync completed.")
    except Exception as e:
        logger.error("Daily macro sync failed: %s", e)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup
    logger.info("🚀 MT5 Data Service starting...")
    init_db()
    mt5_service.initialize()

    # Start macro sync scheduler
    scheduler.add_job(
        daily_macro_sync,
        "cron",
        hour=settings.macro_sync_hour,
        minute=settings.macro_sync_minute,
        id="daily_macro_sync",
    )
    scheduler.start()
    logger.info("📅 Macro sync scheduled at %02d:%02d UTC daily.",
                settings.macro_sync_hour, settings.macro_sync_minute)

    logger.info("✅ MT5 Data Service ready.")
    yield
    # Shutdown
    logger.info("Shutting down MT5 Data Service...")
    scheduler.shutdown(wait=False)
    mt5_service.shutdown()


app = FastAPI(
    title="MT5 Data Service",
    description="REST API for downloading historical market data from MetaTrader 5 terminals.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS – allow TradeLog app on the NAS to call this service
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(broker_router)
app.include_router(download_router)
app.include_router(trades_router)
app.include_router(macro_router)


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """Service health check – used by TradeLog to verify connectivity."""
    db_ok = False
    active_jobs = 0
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        active_jobs = db.query(DownloadJob).filter(
            DownloadJob.status.in_(["pending", "running"])
        ).count()
        db_ok = True
        db.close()
    except Exception:
        pass

    return HealthResponse(
        status="ok" if db_ok and mt5_service.is_connected() else "degraded",
        mt5_connected=mt5_service.is_connected(),
        mt5_version=mt5_service.get_version(),
        db_connected=db_ok,
        active_jobs=active_jobs,
    )


@app.get("/", tags=["system"])
async def root():
    return {
        "service": "MT5 Data Service",
        "version": "1.0.0",
        "docs": "/docs",
    }
