"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from typing import List
import json


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://tradelog:password@localhost:5432/tradelog"

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # Encryption
    encryption_key: str = ""

    # CORS
    cors_origins: str = '["http://localhost:3000"]'

    # MT5
    mt5_terminal_path: str = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    mt5_max_concurrent_downloads: int = 2
    mt5_chunk_size: int = 100000  # Records per DB insert batch

    # FRED / Macro sync
    fred_api_key: str = ""  # Optional – CSV download works without it
    macro_sync_hour: int = 22  # UTC hour for daily FRED sync cron
    macro_sync_minute: int = 0

    # Logging
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> List[str]:
        return json.loads(self.cors_origins)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
