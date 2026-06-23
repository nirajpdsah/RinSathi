# fix_files.py
# Run this once: python fix_files.py
# It rewrites db/session.py and db/models.py with correct UTF-8 encoding

import os

os.makedirs("db", exist_ok=True)

# ── db/session.py ─────────────────────────────────────────────────────────────
session_code = """\
# db/session.py
# Manages async database connection to Supabase PostgreSQL.

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession  # Async DB engine and session
from sqlalchemy.orm import sessionmaker, DeclarativeBase               # ORM utilities
from config import get_settings                                        # Centralised config loader

settings = get_settings()  # Load settings from .env file once

# Replace postgresql:// with postgresql+asyncpg:// to activate the async driver
# asyncpg is the async PostgreSQL driver for Python
ASYNC_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

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
"""

# ── db/models.py ──────────────────────────────────────────────────────────────
models_code = """\
# db/models.py
# SQLAlchemy ORM models -- each class is one table in Supabase PostgreSQL.
# SQLAlchemy reads these class definitions and creates matching SQL tables.

from sqlalchemy import (
    Column, String, Float, Boolean,   # Basic SQL column types
    DateTime, Text, ForeignKey,        # Timestamps, long text, foreign key links
    Enum as SQLEnum                    # SQL ENUM for fixed-choice string columns
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
# UUID: universally unique identifiers -- safer than sequential integers for financial records
# JSONB: binary JSON in PostgreSQL -- used to store SHAP explanation data, fast to query

import uuid                            # Python UUID generator
import enum                            # Python enum for status choices
from datetime import datetime, timezone  # UTC-aware timestamps
from db.session import Base            # Declarative base -- all models inherit from this


# ── Enum types -- define allowed values for status columns ────────────────────
class LoanStatus(str, enum.Enum):
    # str mixin makes the enum JSON serializable (important for API responses)
    PENDING  = "pending"   # Application submitted, pipeline not yet run
    APPROVED = "approved"  # Decision Agent output: Approve
    REJECTED = "rejected"  # Decision Agent output: Reject
    REFERRED = "referred"  # Decision Agent output: Refer (manual human review needed)

class DocumentType(str, enum.Enum):
    CITIZENSHIP = "citizenship"  # Nepal citizenship certificate (nagarikta)
    LALPURJA    = "lalpurja"     # Land ownership document
    PAN         = "pan"          # PAN card for tax identification


# ── Table 1: roles ────────────────────────────────────────────────────────────
class Role(Base):
    __tablename__ = "roles"  # This string becomes the actual table name in PostgreSQL

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # as_uuid=True: SQLAlchemy handles UUID as Python uuid.UUID object, not a string
    # default=uuid.uuid4: auto-generates a unique ID if none is provided

    name        = Column(String(50),  unique=True, nullable=False)  # e.g. "loan_officer"
    description = Column(Text, nullable=True)  # Optional human-readable description


# ── Table 2: applicants ───────────────────────────────────────────────────────
class Applicant(Base):
    __tablename__ = "applicants"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name       = Column(String(255), nullable=False)    # Applicant full name
    citizenship_no  = Column(String(50),  nullable=True)     # Extracted by Document Agent
    district        = Column(String(100), nullable=True)     # District of residence
    phone           = Column(String(20),  nullable=True)     # Contact number
    loan_amount_npr = Column(Float,       nullable=False)    # Requested loan amount in NPR
    sector          = Column(String(100), nullable=False)    # Business sector
    status = Column(
        SQLEnum(LoanStatus),
        default=LoanStatus.PENDING,   # New applications start as pending
        nullable=False
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)  # Stored in UTC, not local time
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)  # Auto-updates on every save
    )


# ── Table 3: documents ────────────────────────────────────────────────────────
class Document(Base):
    __tablename__ = "documents"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_id   = Column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id"),  # Links to the applicants table
        nullable=False
    )
    document_type  = Column(SQLEnum(DocumentType), nullable=False)

    extracted_fields = Column(JSONB, nullable=True)
    # Stores OCR results as JSON -- example:
    # {"name": {"value": "Ram Thapa", "confidence": 0.91},
    #  "citizenship_no": {"value": "23-02-51-12345", "confidence": 0.88}}

    doc_confidence = Column(Float,   nullable=True)   # Mean confidence across all fields (0-1)
    manual_review_required = Column(Boolean, default=False)  # True if quality too low for KYC
    ocr_raw_text   = Column(Text,    nullable=True)   # Raw OCR output stored for audit trail
    created_at     = Column(DateTime(timezone=True),
                            default=lambda: datetime.now(timezone.utc))


# ── Table 4: audit_logs ───────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"
    # Every system action is recorded here -- NRB requires full audit traceability

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id"),
        nullable=True     # Nullable -- some events are system-level, not applicant-specific
    )
    event_type   = Column(String(100), nullable=False)   # e.g. "DOCUMENT_UPLOADED"
    agent_name   = Column(String(100), nullable=True)    # Which agent triggered this log
    details      = Column(JSONB,       nullable=True)    # Extra context as flexible JSON
    performed_by = Column(String(255), nullable=True)    # User ID or "system"
    created_at   = Column(DateTime(timezone=True),
                          default=lambda: datetime.now(timezone.utc))
"""

# Write both files with explicit UTF-8 encoding
with open("db/session.py", "w", encoding="utf-8") as f:
    f.write(session_code)
print("db/session.py  written OK (UTF-8)")

with open("db/models.py", "w", encoding="utf-8") as f:
    f.write(models_code)
print("db/models.py   written OK (UTF-8)")

print("\nNow run:")
print('  python -c "import db.session; print(\'session OK\')"')
print('  python -c "import db.models;  print(\'models  OK\')"')