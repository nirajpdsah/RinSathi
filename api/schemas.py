# ── api/schemas.py ────────────────────────────────────────────────────────────
# Pydantic request and response schemas for all API endpoints.
# These are the API contracts — locked in Sprint 1 so the frontend can be built
# against them without worrying about breaking changes later.
# IMPORTANT: Never change field names here after Sprint 1.

from pydantic import BaseModel     # Pydantic v2 base class
from typing import Optional
import uuid


class FieldResult(BaseModel):
    # Represents a single OCR-extracted field with its confidence score
    value:      str                # The extracted text value
    confidence: float              # OCR confidence for this field (0.0 – 1.0)


class ErrorResponse(BaseModel):
    # Standard error response shape — consistent across all endpoints
    detail:     str               # Human-readable error message
    error_code: Optional[str] = None  # Machine-readable code (e.g. "INVALID_FILE_TYPE")