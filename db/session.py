# db/session.py
#
# Manages the async database connection to Supabase PostgreSQL.
#
# Key concepts:
#   - We use asyncpg as the database driver (async, non-blocking)
#   - SQLAlchemy manages a connection pool (reuses connections instead of
#     opening a new one for every request — much faster)
#   - Every FastAPI route gets its own session via Depends(get_db)
#     and that session is automatically closed when the request finishes

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.engine import make_url
from config import get_settings

settings = get_settings()

# ── Build the async database URL ─────────────────────────────────────────────
# Supabase gives us a URL starting with "postgresql://"
# asyncpg needs "postgresql+asyncpg://" — we swap the driver prefix here
_url = make_url(settings.DATABASE_URL)
ASYNC_URL = _url.set(drivername="postgresql+asyncpg")

# ── Create the engine ────────────────────────────────────────────────────────
# The engine is the actual connection to your database.
# Think of it like the phone line between your app and Supabase.
# We create it ONCE at startup and reuse it for every request.
engine = create_async_engine(
    ASYNC_URL,
    pool_size=5,        # Keep 5 connections open at all times
    max_overflow=10,    # Allow up to 10 extra connections during traffic spikes
    echo=False,         # Set True to print SQL in terminal during debugging
    connect_args={
        # Supabase requires SSL — this enforces encrypted connection
        # "prefer" works with pgBouncer transaction pooler on port 6543
        "ssl": "prefer",
        # Required for Supabase pgBouncer — disables prepared statement caching
        # Without this, you'll get "prepared statement does not exist" errors
        "statement_cache_size": 0,
    }
)

# ── Session factory ──────────────────────────────────────────────────────────
# AsyncSessionLocal is a factory that creates one database session per request.
# Think of a session like a conversation with the database:
#   - You open it (start of request)
#   - You do your queries
#   - You commit or rollback
#   - You close it (end of request)
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects usable after commit (important for async)
)


# ── Declarative Base ─────────────────────────────────────────────────────────
# All SQLAlchemy models in models.py inherit from this Base.
# It's what connects your Python classes to actual database tables.
class Base(DeclarativeBase):
    pass


# ── Startup: create tables ───────────────────────────────────────────────────
async def create_tables():
    """
    Called once at app startup.
    Creates all tables in Supabase that don't exist yet.
    
    SQLAlchemy reads all models that inherit from Base and
    runs CREATE TABLE IF NOT EXISTS for each one.
    Safe to run multiple times — won't destroy existing data.
    """
    async with engine.begin() as conn:
        from db import models  # Import so SQLAlchemy registers all model classes
        await conn.run_sync(Base.metadata.create_all)


# ── Request dependency: get_db ───────────────────────────────────────────────
async def get_db():
    """
    FastAPI dependency — automatically provides a database session to any
    route that declares: db: AsyncSession = Depends(get_db)
    
    The 'async with' block ensures the session is ALWAYS closed after the
    request, even if an exception occurs. No leaked connections.
    
    Think of it like a library book:
      - FastAPI checks it out for you at the start of the request
      - You use it inside the route function
      - FastAPI returns it automatically when the request ends
    """
    async with AsyncSessionLocal() as session:
        yield session