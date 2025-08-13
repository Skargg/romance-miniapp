import os
import asyncio
import platform
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# Поддержка старого формата URL на asyncpg: заменяем на psycopg автоматически
_DEFAULT_URL = "postgresql+psycopg://app:app@localhost:5432/romance"
_env_url = os.getenv("DATABASE_URL", _DEFAULT_URL)
if "+asyncpg" in _env_url:
    _env_url = _env_url.replace("+asyncpg", "+psycopg")

# Windows: psycopg async requires selector event loop
try:
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except Exception:
    pass

engine = create_async_engine(_env_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
