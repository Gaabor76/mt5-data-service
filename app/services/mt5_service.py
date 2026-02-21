"""
Core MT5 service – handles terminal connection, data downloads, and DB writes.

This runs on Windows natively, using the official MetaTrader5 Python package.
No Wine, no RPyC, no hacks.
"""

import MetaTrader5 as mt5
import numpy as np
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func, text

from app.models.database import TickData, RateData, DownloadJob, SessionLocal
from app.config import settings

logger = logging.getLogger(__name__)

# MT5 timeframe mapping
TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M2":  mt5.TIMEFRAME_M2,
    "M3":  mt5.TIMEFRAME_M3,
    "M4":  mt5.TIMEFRAME_M4,
    "M5":  mt5.TIMEFRAME_M5,
    "M6":  mt5.TIMEFRAME_M6,
    "M10": mt5.TIMEFRAME_M10,
    "M12": mt5.TIMEFRAME_M12,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H2":  mt5.TIMEFRAME_H2,
    "H3":  mt5.TIMEFRAME_H3,
    "H4":  mt5.TIMEFRAME_H4,
    "H6":  mt5.TIMEFRAME_H6,
    "H8":  mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

# Thread lock – MT5 terminal is NOT thread-safe
_mt5_lock = threading.Lock()


class MT5Service:
    """Manages MT5 terminal connection and data operations."""

    def __init__(self):
        self._initialized = False
        self._current_login: Optional[int] = None
        self._current_server: Optional[str] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Initialize MT5 terminal connection."""
        with _mt5_lock:
            if not mt5.initialize(path=settings.mt5_terminal_path):
                error = mt5.last_error()
                logger.error(f"MT5 initialize failed: {error}")
                return False
            self._initialized = True
            version = mt5.version()
            logger.info(f"MT5 initialized: v{version[0]} build {version[1]}")
            return True

    def shutdown(self):
        """Shutdown MT5 terminal connection."""
        with _mt5_lock:
            mt5.shutdown()
            self._initialized = False
            self._current_login = None
            self._current_server = None
            logger.info("MT5 shutdown.")

    def login(self, login: int, password: str, server: str) -> dict:
        """
        Login to a broker account.
        Returns account info dict or error.
        """
        with _mt5_lock:
            if not self._initialized:
                if not mt5.initialize(path=settings.mt5_terminal_path):
                    return {"error": f"MT5 init failed: {mt5.last_error()}"}

            result = mt5.login(login=login, password=password, server=server)
            if not result:
                error = mt5.last_error()
                logger.error(f"Login failed for {login}@{server}: {error}")
                return {"error": f"Login failed: {error}"}

            account = mt5.account_info()
            self._current_login = login
            self._current_server = server

            logger.info(f"Logged in: {account.name} ({login}@{server})")
            return {
                "connected": True,
                "login": login,
                "server": server,
                "name": account.name,
                "balance": account.balance,
                "currency": account.currency,
            }

    def get_version(self) -> Optional[str]:
        """Get MT5 version string."""
        with _mt5_lock:
            if not self._initialized:
                return None
            v = mt5.version()
            return f"{v[0]}.{v[1]}" if v else None

    def is_connected(self) -> bool:
        """Check if MT5 is initialized and connected."""
        with _mt5_lock:
            if not self._initialized:
                return False
            info = mt5.terminal_info()
            return info is not None and info.connected

    # ------------------------------------------------------------------
    # Symbol operations
    # ------------------------------------------------------------------

    def get_symbols(self, group: Optional[str] = None) -> List[dict]:
        """List available symbols, optionally filtered by group."""
        with _mt5_lock:
            if group:
                symbols = mt5.symbols_get(group=group)
            else:
                symbols = mt5.symbols_get()

            if symbols is None:
                return []

            return [
                {
                    "name": s.name,
                    "description": s.description,
                    "point": s.point,
                    "digits": s.digits,
                    "spread": s.spread,
                    "trade_mode": s.trade_mode,
                }
                for s in symbols
            ]

    # ------------------------------------------------------------------
    # Tick data download
    # ------------------------------------------------------------------

    def download_ticks(
        self,
        job_id: str,
        broker_server: str,
        login: int,
        password: str,
        symbol: str,
        date_from: datetime,
        date_to: datetime,
    ) -> dict:
        """
        Download tick data and write to DB in chunks.
        Updates job progress in mt5_download_jobs table.
        """
        db = SessionLocal()
        try:
            # Update job status
            self._update_job(db, job_id, status="running", started_at=datetime.utcnow())

            # Login to broker
            login_result = self.login(login, password, broker_server)
            if "error" in login_result:
                self._update_job(db, job_id, status="failed", error_message=login_result["error"])
                return login_result

            # Ensure symbol is available
            with _mt5_lock:
                selected = mt5.symbol_select(symbol, True)
                if not selected:
                    err = f"Symbol {symbol} not available"
                    self._update_job(db, job_id, status="failed", error_message=err)
                    return {"error": err}

            # Download ticks from MT5
            logger.info(f"Downloading ticks: {symbol} from {date_from} to {date_to}")

            with _mt5_lock:
                utc_from = date_from.replace(tzinfo=timezone.utc) if date_from.tzinfo is None else date_from
                utc_to = date_to.replace(tzinfo=timezone.utc) if date_to.tzinfo is None else date_to
                ticks = mt5.copy_ticks_range(symbol, utc_from, utc_to, mt5.COPY_TICKS_ALL)

            if ticks is None or len(ticks) == 0:
                error = mt5.last_error()
                logger.warning(f"No ticks returned for {symbol}: {error}")
                self._update_job(db, job_id, status="completed", total_records=0, progress=100)
                return {"total_records": 0, "message": "No ticks found for the given range"}

            total = len(ticks)
            logger.info(f"Received {total:,} ticks for {symbol}")
            self._update_job(db, job_id, total_records=total)

            # Write to DB in chunks
            chunk_size = settings.mt5_chunk_size
            processed = 0

            for i in range(0, total, chunk_size):
                chunk = ticks[i:i + chunk_size]
                rows = [
                    {
                        "broker_server": broker_server,
                        "symbol": symbol,
                        "time_msc": int(t[2]),   # time_msc field
                        "bid": float(t[3]),       # bid
                        "ask": float(t[4]),       # ask
                        "last": float(t[5]),      # last
                        "volume": float(t[6]),    # volume
                        "flags": int(t[7]),       # flags
                    }
                    for t in chunk
                ]

                # Upsert – skip duplicates based on unique constraint
                stmt = pg_insert(TickData).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    constraint="uq_tick_unique"
                )
                db.execute(stmt)
                db.commit()

                processed += len(chunk)
                progress = int((processed / total) * 100)
                self._update_job(db, job_id, processed_records=processed, progress=progress)
                logger.info(f"  Ticks progress: {processed:,}/{total:,} ({progress}%)")

            self._update_job(
                db, job_id,
                status="completed",
                progress=100,
                processed_records=total,
                completed_at=datetime.utcnow()
            )
            logger.info(f"✅ Tick download complete: {total:,} records for {symbol}")
            return {"total_records": total, "status": "completed"}

        except Exception as e:
            logger.exception(f"Tick download failed: {e}")
            self._update_job(db, job_id, status="failed", error_message=str(e))
            return {"error": str(e)}
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Rate (OHLCV) data download
    # ------------------------------------------------------------------

    def download_rates(
        self,
        job_id: str,
        broker_server: str,
        login: int,
        password: str,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> dict:
        """
        Download OHLCV candle data and write to DB in chunks.
        Updates job progress in mt5_download_jobs table.
        """
        db = SessionLocal()
        try:
            self._update_job(db, job_id, status="running", started_at=datetime.utcnow())

            # Validate timeframe
            mt5_tf = TIMEFRAME_MAP.get(timeframe.upper())
            if mt5_tf is None:
                err = f"Invalid timeframe: {timeframe}. Valid: {list(TIMEFRAME_MAP.keys())}"
                self._update_job(db, job_id, status="failed", error_message=err)
                return {"error": err}

            # Login
            login_result = self.login(login, password, broker_server)
            if "error" in login_result:
                self._update_job(db, job_id, status="failed", error_message=login_result["error"])
                return login_result

            # Select symbol
            with _mt5_lock:
                selected = mt5.symbol_select(symbol, True)
                if not selected:
                    err = f"Symbol {symbol} not available"
                    self._update_job(db, job_id, status="failed", error_message=err)
                    return {"error": err}

            # Download rates
            logger.info(f"Downloading rates: {symbol} {timeframe} from {date_from} to {date_to}")

            with _mt5_lock:
                utc_from = date_from.replace(tzinfo=timezone.utc) if date_from.tzinfo is None else date_from
                utc_to = date_to.replace(tzinfo=timezone.utc) if date_to.tzinfo is None else date_to
                rates = mt5.copy_rates_range(symbol, mt5_tf, utc_from, utc_to)

            if rates is None or len(rates) == 0:
                error = mt5.last_error()
                logger.warning(f"No rates returned for {symbol} {timeframe}: {error}")
                self._update_job(db, job_id, status="completed", total_records=0, progress=100)
                return {"total_records": 0, "message": "No rates found for the given range"}

            total = len(rates)
            logger.info(f"Received {total:,} candles for {symbol} {timeframe}")
            self._update_job(db, job_id, total_records=total)

            # Write to DB in chunks
            chunk_size = settings.mt5_chunk_size
            processed = 0

            for i in range(0, total, chunk_size):
                chunk = rates[i:i + chunk_size]
                rows = [
                    {
                        "broker_server": broker_server,
                        "symbol": symbol,
                        "timeframe": timeframe.upper(),
                        "time": int(r[0]),              # time (unix)
                        "open": float(r[1]),             # open
                        "high": float(r[2]),             # high
                        "low": float(r[3]),              # low
                        "close": float(r[4]),            # close
                        "tick_volume": int(r[5]),        # tick_volume
                        "spread": int(r[6]),             # spread
                        "real_volume": int(r[7]),        # real_volume
                    }
                    for r in chunk
                ]

                stmt = pg_insert(RateData).values(rows)
                stmt = stmt.on_conflict_do_nothing(constraint="uq_rate_unique")
                db.execute(stmt)
                db.commit()

                processed += len(chunk)
                progress = int((processed / total) * 100)
                self._update_job(db, job_id, processed_records=processed, progress=progress)
                logger.info(f"  Rates progress: {processed:,}/{total:,} ({progress}%)")

            self._update_job(
                db, job_id,
                status="completed",
                progress=100,
                processed_records=total,
                completed_at=datetime.utcnow()
            )
            logger.info(f"✅ Rate download complete: {total:,} candles for {symbol} {timeframe}")
            return {"total_records": total, "status": "completed"}

        except Exception as e:
            logger.exception(f"Rate download failed: {e}")
            self._update_job(db, job_id, status="failed", error_message=str(e))
            return {"error": str(e)}
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_job(self, db: Session, job_id: str, **kwargs):
        """Update a download job record."""
        db.query(DownloadJob).filter(DownloadJob.id == job_id).update(kwargs)
        db.commit()


# Singleton instance
mt5_service = MT5Service()
