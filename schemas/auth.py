# schemas/auth.py
#
# Pydantic schemas — the "standard forms" of RinSathi.
#
# Every API request coming IN and every response going OUT
# must match one of these shapes exactly.
#
# Why does this matter?
# Imagine a client sends a loan application with no email field.
# Without schemas, that bad data reaches your database and causes
# a crash deep inside your code — hard to debug, hard to fix.
# With schemas, FastAPI rejects the request at the door, before
# your code even runs, with a clear error message.
#
# Think of Pydantic as a very strict bank teller:
# "Sir, your form is incomplete. Date of birth is missing.
#  Please fill it and come back."

from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime


# ════════════════════════════════════════════════════════
# REQUEST SCHEMAS
# These define what the FRONTEND sends TO your backend.
# ════════════════════════════════════════════════════════

class GoogleLoginRequest(BaseModel):
    """
    What the frontend sends when a client clicks "Sign in with Google."

    After the Google popup completes on the frontend, Google gives
    the browser a credential string called an ID token.
    The frontend sends that token here.
    Your backend then verifies it with Google's servers.

    The frontend never sends email or name directly —
    those come from Google after verification. Never trust
    what the client sends for identity. Always verify with
    the source (Google in this case).
    """
    google_token: str


class OfficerLoginRequest(BaseModel):
    """
    What the frontend sends when an officer logs in.

    Simple email + password. No Google involved.
    EmailStr is a special Pydantic type that validates the
    email format automatically — if someone sends
    "notanemail", Pydantic rejects it before your code runs.
    """
    email: EmailStr
    password: str


# ════════════════════════════════════════════════════════
# RESPONSE SCHEMAS
# These define what your backend sends BACK to the frontend.
# ════════════════════════════════════════════════════════

class UserOut(BaseModel):
    """
    The safe public view of a user.

    Notice what is NOT here:
      - password_hash   (never send this to anyone, ever)
      - google_id       (internal identifier, frontend doesn't need it)

    This is called a "projection" — you project only the fields
    that are safe and necessary for the frontend to display.

    from_attributes = True tells Pydantic:
    "You can create this object directly from a SQLAlchemy model."
    Without this, you'd have to manually map every field.
    """
    id:         UUID
    email:      str
    full_name:  str
    role:       str        # "client" or "officer" — frontend uses this for routing
    is_active:  bool
    created_at: datetime

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """
    What your backend returns after ANY successful login —
    whether Google OAuth or officer credentials.

    The frontend receives this, stores jwt_token in localStorage,
    and uses it for every future API call.

    It also gets the user object so it can immediately display
    "Welcome, Ram Bahadur" on the dashboard without making
    a second API call.
    """
    jwt_token:  str
    token_type: str = "bearer"   # Standard OAuth2 terminology
    user:       UserOut