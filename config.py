# ── config.py ────────────────────────────────────────────────────────────────
# Central configuration file. ALL settings come from the .env file.
# No passwords, secrets, or thresholds are ever hardcoded in other files.
# This follows the 12-factor app principle: store config in the environment.

from pydantic_settings import BaseSettings   # Pydantic-powered .env reader
from functools import lru_cache              # Caches the result so .env is read only once


class Settings(BaseSettings):               # Inheriting BaseSettings auto-reads .env
    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str                        # Full PostgreSQL connection string from Supabase

    # ── JWT Authentication ────────────────────────────────────────────────────
    SECRET_KEY: str = "change-in-production" # Secret used to sign JWT tokens
    ALGORITHM:  str = "HS256"               # HMAC-SHA256 — standard JWT signing algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # Token valid for 24 hours (1440 minutes)

    # ── Pipeline thresholds — loaded from config, never hardcoded in agents ──
    APPROVE_THRESHOLD:     float = 0.65     # credit_score >= 0.65 → Approve
    REFER_THRESHOLD:       float = 0.40     # credit_score >= 0.40 → Refer (else Reject)
    MIN_KYC_CONFIDENCE:    float = 0.70     # OCR confidence below this → manual review
    MAX_LOAN_TO_ASSET:     float = 0.75     # NRB Unified Directive limit
    MAX_VEHICLE_LOAN_TO_VALUE: float = 0.85
    AML_TXN_LIMIT_NPR:     float = 1_000_000  # Single transaction AML flag threshold
    AGRI_SECTOR_LIMIT_NPR: float = 500_000  # Agricultural sector exposure cap (NPR)
    OCR_TIMEOUT_SECONDS:   float = 10.0     # Hard timeout for OCR — protects 30s SLA
    google_client_id: str

    # ── Mock Government API URLs ──────────────────────────────────────────────────
    # In development: points to local mock endpoints
    # In production:  change to real DoNIDCR and NeLIS government API URLs
    # Zero code changes needed in agents — only these values change
    DONIDCR_URL: str = "http://localhost:8000/api/v1/mock/donidcr/verify"
    NELIS_URL:   str = "http://localhost:8000/api/v1/mock/nelis/lookup"
    CIB_URL: str = "http://localhost:8000/api/v1/mock/cib/lookup"

    class Config:
        env_file = ".env"                   # Tell Pydantic: read from the .env file


@lru_cache()                               # @lru_cache means this runs once, then cached
def get_settings() -> Settings:
    return Settings()                       # Returns the same Settings object every time