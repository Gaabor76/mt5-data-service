"""Database connection and table definitions for MT5 market data."""

from sqlalchemy import (
    create_engine, Column, String, Integer, BigInteger, Float, SmallInteger,
    DateTime, Date, Numeric, Text, Boolean, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime
import uuid

from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for DB sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tables – these are created by the MT5 Data Service, separate from
# TradeLog's Drizzle-managed tables. TradeLog reads from them via SQL/views.
# ---------------------------------------------------------------------------

class TickData(Base):
    """Raw tick data from MT5 broker."""
    __tablename__ = "mt5_tick_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    broker_server = Column(String(255), nullable=False)
    symbol = Column(String(50), nullable=False)
    time_msc = Column(BigInteger, nullable=False)          # Millisecond timestamp
    bid = Column(Float, nullable=False)
    ask = Column(Float, nullable=False)
    last = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)                   # Tick volume
    flags = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_tick_broker_symbol_time", "broker_server", "symbol", "time_msc"),
        UniqueConstraint("broker_server", "symbol", "time_msc", name="uq_tick_unique"),
    )


class RateData(Base):
    """OHLCV candle data from MT5 broker."""
    __tablename__ = "mt5_rate_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    broker_server = Column(String(255), nullable=False)
    symbol = Column(String(50), nullable=False)
    timeframe = Column(String(10), nullable=False)          # M1, M5, H1, etc.
    time = Column(BigInteger, nullable=False)                # Unix timestamp
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    tick_volume = Column(BigInteger, nullable=True)
    spread = Column(Integer, nullable=True)
    real_volume = Column(BigInteger, nullable=True)

    __table_args__ = (
        Index("idx_rate_broker_symbol_tf_time", "broker_server", "symbol", "timeframe", "time"),
        UniqueConstraint("broker_server", "symbol", "timeframe", "time", name="uq_rate_unique"),
    )


class DownloadJob(Base):
    """Download job queue – tracks progress for the TradeLog UI."""
    __tablename__ = "mt5_download_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False)

    # Broker connection
    broker_server = Column(String(255), nullable=False)
    broker_login = Column(String(255), nullable=False)       # Encrypted
    broker_password = Column(String(255), nullable=False)    # Encrypted

    # What to download
    symbol = Column(String(50), nullable=False)
    data_type = Column(String(10), nullable=False)           # "ticks" or "rates"
    timeframe = Column(String(10), nullable=True)            # For rates only
    date_from = Column(DateTime, nullable=False)
    date_to = Column(DateTime, nullable=False)

    # Status tracking
    status = Column(String(20), default="pending", nullable=False)
    # pending → running → completed / failed
    progress = Column(Integer, default=0)                    # 0-100
    total_records = Column(BigInteger, nullable=True)
    processed_records = Column(BigInteger, default=0)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class MacroDaily(Base):
    """Daily macro-economic data for gold trading bias calculation."""
    __tablename__ = "macro_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)

    # Raw data
    dxy_close = Column(Numeric(10, 4), nullable=True)
    dxy_high = Column(Numeric(10, 4), nullable=True)
    dxy_low = Column(Numeric(10, 4), nullable=True)
    us10y = Column(Numeric(8, 4), nullable=True)
    us02y = Column(Numeric(8, 4), nullable=True)
    t5yie = Column(Numeric(8, 4), nullable=True)
    ffr = Column(Numeric(8, 4), nullable=True)

    # Calculated values
    real_rate = Column(Numeric(8, 4), nullable=True)       # us10y - t5yie
    yield_curve = Column(Numeric(8, 4), nullable=True)     # us10y - us02y
    fed_spread = Column(Numeric(8, 4), nullable=True)      # us02y - ffr
    dxy_percentile = Column(Numeric(6, 2), nullable=True)  # 0-100, 60-day lookback

    # Scores (individual components, -2 to +2)
    realrate_score = Column(SmallInteger, nullable=True)
    dxy_score = Column(SmallInteger, nullable=True)
    yc_score = Column(SmallInteger, nullable=True)
    fed_score = Column(SmallInteger, nullable=True)
    cb_score = Column(SmallInteger, default=0)  # manual input, default neutral

    # Weighted & final
    macro_score_raw = Column(Numeric(6, 2), nullable=True)
    macro_score_pct = Column(Numeric(6, 2), nullable=True)  # 0-100 normalized
    macro_bias = Column(SmallInteger, nullable=True)         # -2 to +2

    # Metadata
    source = Column(String(20), default="fred")  # 'fred', 'csv_import', 'manual'
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_macro_daily_date", "date"),
        Index("idx_macro_daily_bias", "macro_bias"),
    )


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified.")
