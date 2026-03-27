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


class TradeHistoryRequest(BaseModel):
    server: str
    login: int
    password: str
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


# ---------------------------------------------------------------------------
# Macro daily
# ---------------------------------------------------------------------------

class MacroComponents(BaseModel):
    real_rate: Optional[float] = None
    dxy_percentile: Optional[float] = None
    yield_curve: Optional[float] = None
    fed_spread: Optional[float] = None
    realrate_score: Optional[int] = None
    dxy_score: Optional[int] = None
    yc_score: Optional[int] = None
    fed_score: Optional[int] = None
    cb_score: Optional[int] = None

class MacroMultipliers(BaseModel):
    lot_aligned: float = 2.0
    lot_neutral: float = 1.0
    lot_conflict: float = 0.5
    sl_aligned: float = 0.75
    sl_neutral: float = 1.0
    sl_conflict: float = 1.25
    tp_aligned: float = 1.5
    tp_neutral: float = 1.0
    tp_conflict: float = 0.6

class MacroLatestResponse(BaseModel):
    date: Optional[str] = None
    macro_bias: Optional[int] = None
    macro_bias_str: Optional[str] = None
    macro_score_pct: Optional[float] = None
    macro_score_raw: Optional[float] = None
    multipliers: MacroMultipliers = MacroMultipliers()
    components: Optional[MacroComponents] = None
    data_age_hours: Optional[float] = None

class MacroDailyRecord(BaseModel):
    date: str
    dxy_close: Optional[float] = None
    dxy_high: Optional[float] = None
    dxy_low: Optional[float] = None
    us10y: Optional[float] = None
    us02y: Optional[float] = None
    t5yie: Optional[float] = None
    ffr: Optional[float] = None
    real_rate: Optional[float] = None
    yield_curve: Optional[float] = None
    fed_spread: Optional[float] = None
    dxy_percentile: Optional[float] = None
    realrate_score: Optional[int] = None
    dxy_score: Optional[int] = None
    yc_score: Optional[int] = None
    fed_score: Optional[int] = None
    cb_score: Optional[int] = None
    macro_score_raw: Optional[float] = None
    macro_score_pct: Optional[float] = None
    macro_bias: Optional[int] = None
    source: Optional[str] = None

class MacroHistoryResponse(BaseModel):
    count: int
    records: List[MacroDailyRecord]

class MacroSyncRequest(BaseModel):
    start_date: str  # ISO date YYYY-MM-DD
    end_date: str    # ISO date YYYY-MM-DD

class MacroImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: List[str]

class MacroHealthResponse(BaseModel):
    fred_reachable: bool
    last_sync_date: Optional[str] = None
    total_records: int = 0
