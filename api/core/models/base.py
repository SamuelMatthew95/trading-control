"""
Base model configuration.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

Base = declarative_base()

# Database configuration
def get_async_engine(database_url: str):
    """Create async engine with proper configuration."""
    return create_async_engine(
        database_url,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False
    )

def get_session_factory(async_engine):
    """Create session factory."""
    return sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
