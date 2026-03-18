"""
Database initialization script for PostgreSQL
Run this once to set up the database schema
"""

import asyncio
import os
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Create async engine
engine = create_async_engine(DATABASE_URL)
async_engine = create_async_engine(
    DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
)

# Create declarative base
Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, nullable=False)
    asset = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # LONG/SHORT/FLAT
    size = Column(Float, nullable=False)  # Position size
    entry = Column(Float, nullable=False)  # Entry price
    stop = Column(Float, nullable=False)  # Stop loss
    target = Column(Float, nullable=False)  # Take profit
    rr_ratio = Column(Float, nullable=False)  # Risk/Reward ratio
    exit_price = Column(Float, nullable=True)  # Exit price
    pnl = Column(Float, nullable=True)  # Profit/Loss
    outcome = Column(String, default="OPEN")  # OPEN/WIN/LOSS
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String, nullable=False, unique=True)
    total_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    avg_response_time = Column(Float, default=0.0)
    accuracy_score = Column(Float, default=0.0)
    improvement_areas = Column(Text, default="[]")  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


async def init_database():
    """Initialize database tables"""
    print(f"Connecting to database: {DATABASE_URL}")

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("Database tables created successfully!")


async def test_connection():
    """Test database connection"""
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute("SELECT 1")
            print("Database connection successful!")
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


if __name__ == "__main__":
    # Test connection first
    if asyncio.run(test_connection()):
        # Initialize tables
        asyncio.run(init_database())
        print("Database initialization complete!")
    else:
        print("Database initialization failed!")
