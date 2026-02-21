"""Pydantic schemas for API requests and responses."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ---------------------------------------------------------------------------
# Broker connection
# ---------------------------------------------------------------------------

class BrokerConnectRequest(BaseModel):
    server: str = Field(..., example="ICMarketsSC-Demo")
    login: int = Field(..., example=12345678)
    password: str = Field(..., example="investor_password")

class BrokerConnectResponse(BaseModel):
    connected: bool
    server: str
    login: int
    mt5_version: Optional[str] = None
    account_name: Optional[str] = None
    account_balance: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

class SymbolInfo(BaseModel):
    name: str
    description: str
    point: float
    digits: int
    spread: int
    trade_mode: int

class SymbolsResponse(BaseModel):
    count: int
    symbols: List[SymbolInfo]


# ---------------------------------------------------------------------------
# Download requests
# ---------------------------------------------------------------------------

class DownloadTicksRequest(BaseModel):
    user_id: str
    broker_server: str
    broker_login: int
    broker_password: str
    symbol: str = Field(..., example="XAUUSD")
    date_from: datetime
    date_to: datetime

class DownloadRatesRequest(BaseModel):
    user_id: str
    broker_server: str
    broker_login: int
    broker_password: str
    symbol: str = Field(..., example="XAUUSD")
    timeframe: str = Field(..., example="M1")
    date_from: datetime
    date_to: datetime


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    id: str
    status: str
    progress: int
    total_records: Optional[int] = None
    processed_records: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]


# ---------------------------------------------------------------------------
# Data query
# ---------------------------------------------------------------------------

class DataRangeRequest(BaseModel):
    broker_server: str
    symbol: str
    timeframe: Optional[str] = None  # For rates only

class DataRangeResponse(BaseModel):
    broker_server: str
    symbol: str
    data_type: str
    timeframe: Optional[str] = None
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    total_records: int = 0


# ---------------------------------------------------------------------------
# Service health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    mt5_connected: bool
    mt5_version: Optional[str] = None
    db_connected: bool
    active_jobs: int = 0
