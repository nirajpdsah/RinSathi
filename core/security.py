# core/security.py
#
# The security department of RinSathi.
#
# Two responsibilities:
#   1. CREATE a JWT token after successful login
#   2. VERIFY a JWT token on every protected request
#
# What is a JWT?
#   A JWT (JSON Web Token) is a signed string the server gives to a user
#   after login. The user sends it back on every request to prove who they are.
#   It's like a stamped visitor pass at an office building.
#
#   Structure: HEADER.PAYLOAD.SIGNATURE
#   The payload contains: user_id, email, role, expiry
#   The signature is created with SECRET_KEY — if anyone tampers with the
#   payload, the signature breaks and we reject the token immediately.

from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import get_settings

settings = get_settings()

# HTTPBearer tells FastAPI: expect "Authorization: Bearer <token>" in headers
# This is the standard way to send JWT tokens in API requests
bearer_scheme = HTTPBearer()


def create_access_token(data: dict) -> str:
    """
    Creates a signed JWT token.

    Called after successful login. The token is returned to the
    frontend, which stores it in localStorage and sends it with
    every subsequent request.

    Args:
        data: dict with user_id, email, full_name, role

    Returns:
        Signed JWT string — e.g. "eyJhbGci..."
    """
    payload = data.copy()

    # Token expires after ACCESS_TOKEN_EXPIRE_MINUTES (set in .env)
    # Default: 1440 minutes = 24 hours
    # After expiry, the user must log in again
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload.update({"exp": expire})

    # Sign the token with SECRET_KEY using HS256 algorithm
    # HS256 = HMAC with SHA-256 — fast and secure for this use case
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> dict:
    """
    Verifies a JWT token and returns the decoded payload.

    This runs on EVERY protected endpoint. FastAPI calls it automatically
    via Depends(verify_token) in route functions.

    What it checks:
      1. Is the token signed by our SECRET_KEY? (not tampered or forged)
      2. Has it expired?
      3. Does it contain a user_id?

    Returns:
        Decoded payload dict: {user_id, email, full_name, role}

    Raises:
        HTTP 401 if anything is wrong with the token
    """
    # We use the same error for all failure cases intentionally.
    # Never tell an attacker specifically WHY their token failed.
    auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("user_id") is None:
            raise auth_error
        return payload

    except JWTError:
        raise auth_error


def require_role(required_role: str):
    """
    A dependency factory that enforces role-based access control.

    Usage in a route:
        @router.get("/officer/dashboard")
        async def dashboard(payload = Depends(require_role("officer"))):
            ...

    If a client tries to access an officer route, they get HTTP 403 Forbidden.
    This is your route guard — the bouncer at the door.

    Args:
        required_role: "client" or "officer"

    Returns:
        A FastAPI dependency function
    """
    def _check_role(
        credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
    ) -> dict:
        payload = verify_token(credentials)

        if payload.get("role") != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. This area requires '{required_role}' access.",
            )
        return payload

    return _check_role