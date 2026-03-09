"""
Configuration Management for Trading Control Platform
Handles all system configuration with type safety and validation
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class LogLevel(Enum):
    """Log levels"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Settings:
    """Application settings with type safety"""

    # Basic Settings
    host: str
    port: int
    debug: bool
    environment: str
    log_level: str
    log_file: Optional[str]
    enable_colors: bool

    # CORS Settings
    cors_origins: list[str]

    # OpenClaw Settings
    cycle_interval: int
    max_concurrent_cycles: int
    confidence_threshold: float
    risk_threshold: float

    # Database Settings
    redis_url: str
    postgres_url: str

    # API Keys
    alpha_vantage_api_key: Optional[str]
    news_api_key: Optional[str]
    fmp_api_key: Optional[str]

    @classmethod
    def from_env(cls) -> Settings:
        """Create settings from environment variables"""
        return cls(
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            environment=os.getenv("ENVIRONMENT", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE"),
            enable_colors=os.getenv("ENABLE_COLORS", "true").lower() == "true",
            cors_origins=os.getenv(
                "CORS_ORIGINS", "http://localhost:3000,http://localhost:8080"
            ).split(","),
            cycle_interval=int(os.getenv("CYCLE_INTERVAL", "60")),
            max_concurrent_cycles=int(os.getenv("MAX_CONCURRENT_CYCLES", "3")),
            confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
            risk_threshold=float(os.getenv("RISK_THRESHOLD", "0.7")),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            postgres_url=os.getenv(
                "POSTGRES_URL", "postgresql://user:pass@localhost/trading"
            ),
            alpha_vantage_api_key=os.getenv("ALPHA_VANTAGE_API_KEY"),
            news_api_key=os.getenv("NEWS_API_KEY"),
            fmp_api_key=os.getenv("FMP_API_KEY"),
        )


def get_settings() -> Settings:
    """Get settings instance"""
    return Settings.from_env()


# Environment-specific configurations
def get_env_file() -> str:
    """Get appropriate environment file path"""
    env = os.getenv("ENVIRONMENT", "development")
    return f".env.{env}"


def load_env_file(env_file: str) -> dict:
    """Load environment variables from file"""
    env_vars = {}

    if Path(env_file).exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

    return env_vars


# Load environment file at startup
env_file = get_env_file()
env_vars = load_env_file(env_file)

# Apply environment variables to os.environ
for key, value in env_vars.items():
    os.environ[key] = value
