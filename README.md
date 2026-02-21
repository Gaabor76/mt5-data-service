# MT5 Data Service

REST API for downloading historical market data from MetaTrader 5 terminals.  
Runs on **Windows** natively alongside the MT5 terminal.  
Serves as the data gateway for the **TradeLog** application on the Synology NAS.

## Architecture

```
Synology DS923+                    Mini2 (Windows 11)
┌─────────────────┐    REST API    ┌──────────────────────┐
│ TradeLog Next.js │◄─────────────►│ MT5 Data Service     │
│ PostgreSQL       │    :8000      │ (Python FastAPI)     │
│ Portainer        │               │                      │
└─────────────────┘               │ MT5 Terminal (native) │
                                   └──────────────────────┘
```

## Prerequisites

- **Windows 10/11** (x64)
- **Python 3.11+** – [python.org](https://python.org) (check "Add to PATH")
- **MetaTrader 5** terminal installed and logged in to at least one broker
- **PostgreSQL** accessible on the NAS (port 5432 open in firewall)

## Quick Start

### 1. Setup

```batch
REM Clone or copy the project to Mini2
cd C:\mt5-data-service

REM Run setup (creates venv, installs deps, creates .env)
setup.bat
```

### 2. Configure `.env`

Edit `.env` with your settings:

```env
# NAS PostgreSQL connection
DATABASE_URL=postgresql://tradelog:your_password@192.168.1.XXX:5432/tradelog

# Generate key: python scripts\generate_key.py
ENCRYPTION_KEY=your_generated_key

# TradeLog app URL for CORS
CORS_ORIGINS=["http://192.168.1.XXX:3000"]

# Path to your MT5 terminal
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

### 3. Test MT5 Connection

```batch
venv\Scripts\activate
python scripts\test_mt5_connection.py
```

### 4. Start the Service

```batch
start.bat
```

API docs available at: `http://mini2:8000/docs`

### 5. (Optional) Install as Windows Service

For auto-start with Windows:

```batch
REM Requires NSSM: https://nssm.cc/download
install-service.bat
```

## API Endpoints

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check (MT5 + DB status) |
| GET | `/docs` | Swagger UI |

### Broker
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/broker/connect` | Connect to broker |
| GET | `/api/broker/symbols` | List available symbols |

### Download
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/download/ticks` | Submit tick download job |
| POST | `/api/download/rates` | Submit OHLCV rate download job |
| GET | `/api/download/jobs/{id}` | Get job status/progress |
| GET | `/api/download/jobs` | List all jobs |
| POST | `/api/download/data-range/ticks` | Check available tick data |
| POST | `/api/download/data-range/rates` | Check available rate data |

### Example: Download Tick Data

```bash
# 1. Submit download job
curl -X POST http://mini2:8000/api/download/ticks \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "broker_server": "ICMarketsSC-Demo",
    "broker_login": 12345678,
    "broker_password": "investor_pass",
    "symbol": "XAUUSD",
    "date_from": "2024-01-01T00:00:00",
    "date_to": "2024-01-31T23:59:59"
  }'

# Response: {"id": "abc-123", "status": "pending", "progress": 0, ...}

# 2. Poll for progress
curl http://mini2:8000/api/download/jobs/abc-123

# Response: {"id": "abc-123", "status": "running", "progress": 45, "processed_records": 450000, ...}
```

## Database Tables

The service creates these tables in the TradeLog PostgreSQL database:

- **`mt5_tick_data`** – Raw tick data (bid, ask, last, volume per millisecond)
- **`mt5_rate_data`** – OHLCV candles (open, high, low, close, volume per timeframe)
- **`mt5_download_jobs`** – Job queue with progress tracking

These are separate from TradeLog's Drizzle-managed tables.  
TradeLog reads from them via SQL queries or views.

## Project Structure

```
mt5-data-service/
├── app/
│   ├── __init__.py
│   ├── config.py           # Environment config
│   ├── main.py             # FastAPI application
│   ├── models/
│   │   ├── database.py     # SQLAlchemy tables
│   │   └── schemas.py      # Pydantic request/response models
│   ├── routers/
│   │   ├── broker.py       # /api/broker/* endpoints
│   │   └── download.py     # /api/download/* endpoints
│   └── services/
│       ├── crypto.py       # Credential encryption
│       └── mt5_service.py  # Core MT5 logic
├── scripts/
│   ├── generate_key.py     # Generate encryption key
│   └── test_mt5_connection.py  # Verify MT5 works
├── .env.example
├── requirements.txt
├── run.py                  # Entry point
├── setup.bat               # Windows setup script
├── start.bat               # Start the service
└── install-service.bat     # Install as Windows service
```

## Troubleshooting

### MT5 initialize fails
- Make sure the MT5 terminal is **installed** (not just portable)
- Check `MT5_TERMINAL_PATH` in `.env`
- The MT5 terminal does **not** need to be running – the Python API starts it

### Database connection refused
- Check NAS PostgreSQL is listening on `0.0.0.0:5432` (not just localhost)
- Verify firewall allows Mini2 IP to connect
- Test: `psql -h 192.168.1.XXX -U tradelog -d tradelog`

### No ticks/rates returned
- Market may be closed (weekends)
- Symbol name may differ between brokers (e.g., `XAUUSD` vs `GOLD`)
- Check with `/api/broker/symbols` first
- Investor password must be correct
