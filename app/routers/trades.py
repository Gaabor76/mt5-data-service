"""
Trade history download and reconstruction endpoints.

Uses the existing mt5_service singleton for thread-safe MT5 access.
"""

import uuid
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.services.mt5_service import mt5_service
from app.services.trade_matcher import reconstruct_trades

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])


# ── Request / Response schemas ──────────────────────────────────────

class TradeHistoryRequest(BaseModel):
    """Request to download trade history from MT5."""
    login: int
    password: str
    server: str
    date_from: datetime
    date_to: datetime


class TradeHistoryResponse(BaseModel):
    """Response containing reconstructed trades."""
    job_id: str
    status: str
    account_login: int
    broker_server: str
    deals_count: int
    orders_count: int
    trades: List[Dict[str, Any]]
    balance_operations: List[Dict[str, Any]]
    open_positions: List[Dict[str, Any]]
    errors: List[str]


# ── Endpoint ────────────────────────────────────────────────────────

@router.post("/history", response_model=TradeHistoryResponse)
async def get_trade_history(req: TradeHistoryRequest):
    """
    Download trade history from MT5 and return reconstructed trades.

    Flow:
    1. Login to MT5 with provided credentials (via mt5_service singleton)
    2. Fetch deals, orders, and open positions
    3. Reconstruct trades by matching entry/exit deals on position_id
    4. Return structured data for TradeLog import
    """
    job_id = str(uuid.uuid4())
    errors: List[str] = []

    # 1. Login via the existing service (thread-safe, uses _mt5_lock)
    login_result = mt5_service.login(
        login=req.login,
        password=req.password,
        server=req.server,
    )

    if "error" in login_result:
        raise HTTPException(
            status_code=401,
            detail=f"MT5 login failed: {login_result['error']}"
        )

    logger.info(
        f"[{job_id}] Connected to {req.server} as {req.login}, "
        f"fetching history {req.date_from} → {req.date_to}"
    )

    try:
        # 2. Fetch history data via MT5 API
        import MetaTrader5 as mt5
        import threading

        # Use the service's lock for thread safety
        from app.services.mt5_service import _mt5_lock

        with _mt5_lock:
            deals = mt5.history_deals_get(req.date_from, req.date_to)
            orders = mt5.history_orders_get(req.date_from, req.date_to)
            positions = mt5.positions_get()

        deals_count = len(deals) if deals is not None else 0
        orders_count = len(orders) if orders is not None else 0
        positions_count = len(positions) if positions is not None else 0

        logger.info(
            f"[{job_id}] Fetched {deals_count} deals, "
            f"{orders_count} orders, {positions_count} open positions"
        )

        if deals is None:
            error_info = mt5.last_error()
            errors.append(f"Failed to fetch deals: {error_info}")
            deals_count = 0

        if orders is None:
            error_info = mt5.last_error()
            errors.append(f"Failed to fetch orders: {error_info}")
            orders_count = 0

        # 3. Reconstruct trades
        trades, balance_ops, open_pos = reconstruct_trades(
            raw_deals=deals,
            raw_orders=orders,
            raw_positions=positions,
        )

        logger.info(
            f"[{job_id}] Reconstructed {len(trades)} trades, "
            f"{len(balance_ops)} balance ops, {len(open_pos)} open positions"
        )

        return TradeHistoryResponse(
            job_id=job_id,
            status="completed",
            account_login=req.login,
            broker_server=req.server,
            deals_count=deals_count,
            orders_count=orders_count,
            trades=trades,
            balance_operations=balance_ops,
            open_positions=open_pos,
            errors=errors,
        )

    except Exception as e:
        logger.exception(f"[{job_id}] Trade history failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Trade history processing failed: {str(e)}"
        )
