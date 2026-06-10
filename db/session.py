# db/session.py
# Manages async database connection to Supabase PostgreSQL.

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession  # Async DB engine and session
from sqlalchemy.orm import sessionmaker, DeclarativeBase               # ORM utilities
from config import get_settings                                        # Centralised config loader

settings = get_settings()  # Load settings from .env file once

# Replace postgresql:// with postgresql+asyncpg:// to activate the async driver
# asyncpg is the async PostgreSQL driver for Python
from sqlalchemy.engine import make_url

_url = make_url(settings.DATABASE_URL)
ASYNC_URL = _url.set(drivername="postgresql+asyncpg")

engine = create_async_engine(
    ASYNC_URL,
    pool_size=5,           # Keep 5 persistent connections open in the pool
    max_overflow=10,       # Allow 10 extra connections during high traffic
    echo=False,            # Set True to print all SQL queries in terminal (debug mode)
    connect_args={
        "ssl": "require"   # Supabase mandates SSL -- this enforces encrypted connection
    }
)

# sessionmaker creates a factory that produces one AsyncSession per request
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,       # Use async (non-blocking) sessions
    expire_on_commit=False,    # Keep model objects accessible after commit
)

class Base(DeclarativeBase):   # All SQLAlchemy models in models.py inherit from this
    pass

async def create_tables():
    # Called once at app startup -- creates all tables in Supabase if they don't exist
    # After running, open Supabase Table Editor to confirm the tables appeared
    async with engine.begin() as conn:
        from db import models                           # Import models so SQLAlchemy registers them
        await conn.run_sync(Base.metadata.create_all)  # SQL: CREATE TABLE IF NOT EXISTS

async def get_db():
    # FastAPI dependency injection -- routes declare: db: AsyncSession = Depends(get_db)
    # FastAPI calls this automatically and passes the session into the route function
    async with AsyncSessionLocal() as session:
        yield session   # Session is automatically closed when the request finishes

from sqlalchemy.ext.asyncio import create_async_engine
from config import get_settings

settings = get_settings()

# Ensure the database URL contains +asyncpg
db_url = settings.DATABASE_URL
if "postgresql://" in db_url and "+asyncpg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args={
        "statement_cache_size": 0  # Crucial for Supabase transaction pooling
    }
)