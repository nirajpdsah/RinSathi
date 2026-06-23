# routers/auth.py
#
# The reception desk of RinSathi authentication.
#
# Three endpoints live here:
#   POST /api/v1/auth/google          → client Google login
#   POST /api/v1/auth/officer/login   → officer credential login
#   GET  /api/v1/auth/me              → "who am I?" for any logged-in user
#
# The golden rule of routers:
# ────────────────────────────
# A router function should be SHORT.
# Receive the request → call the service → return the response.
# No database queries directly in here.
# No business logic in here.
# No password checking in here.
# All of that lives in services/auth_service.py.
#
# Why? Because in six months when a bug is reported in
# the password check, you know EXACTLY which file to open.
# You don't hunt through ten router files. You go to
# auth_service.py. One place. Every time.

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.session import get_db
from db.models import User, Role
from schemas.auth import (
    GoogleLoginRequest,
    OfficerLoginRequest,
    LoginResponse,
    UserOut
)
from services.auth_service import (
    verify_google_token,
    get_or_create_client,
    authenticate_officer
)
from core.security import create_access_token, verify_token

# prefix means every route in this file starts with /auth
# tags groups them together in your Swagger docs at /docs
router = APIRouter(prefix="/auth", tags=["Authentication"])


def build_login_response(user: User, role_name: str) -> LoginResponse:
    """
    Helper that builds the LoginResponse from a User object.

    Used by both login endpoints — Google and officer —
    because both return the exact same shape of response.
    We write this once instead of duplicating in both endpoints.

    This is the DRY principle: Don't Repeat Yourself.
    """
    jwt_token = create_access_token({
        "user_id":   str(user.id),
        "email":     user.email,
        "full_name": user.full_name,
        "role":      role_name,      # "client" or "officer"
    })

    return LoginResponse(
        jwt_token=jwt_token,
        user=UserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=role_name,
            is_active=user.is_active,
            created_at=user.created_at,
        )
    )


@router.post("/google", response_model=LoginResponse)
async def google_login(
    request: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    CLIENT LOGIN via Google OAuth.

    Step by step:
    1. Frontend gets google_token from Google after user clicks
       "Sign in with Google" button
    2. Frontend sends that token here — one POST request
    3. We verify it with Google's servers (in auth_service)
    4. We find the client or create a new account (in auth_service)
    5. We return our own JWT token + user info

    After this point, the frontend never uses the Google token again.
    Everything from here uses our JWT.
    """
    # Verify with Google and extract user info
    google_data = await verify_google_token(request.google_token)

    # Find existing client or register new one
    user = await get_or_create_client(google_data, db)

    # Get role name for the JWT payload
    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one()

    return build_login_response(user, role.name)


@router.post("/officer/login", response_model=LoginResponse)
async def officer_login(
    request: OfficerLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    OFFICER LOGIN via email and password.

    Officers are created by the admin directly in the database.
    There is no self-registration for officers — this is intentional.
    In a real MFI, you don't want random people creating officer accounts.

    Step by step:
    1. Officer goes to /officer/login page
    2. Types their email + password
    3. Frontend sends it here
    4. We verify credentials (in auth_service)
    5. We return JWT token + user info
    """
    user = await authenticate_officer(request.email, request.password, db)

    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one()

    return build_login_response(user, role.name)


@router.get("/me", response_model=UserOut)
async def get_me(
    payload: dict = Depends(verify_token),
    db: AsyncSession = Depends(get_db)
):
    """
    "WHO AM I?" — works for both clients and officers.

    The frontend calls this on every page load to:
      1. Verify the stored JWT is still valid
      2. Get fresh user info (name, role, active status)
      3. Decide which dashboard to show

    If the JWT is expired or invalid, verify_token raises HTTP 401
    automatically. This endpoint body never even executes.
    That's the power of FastAPI's Depends() system.

    Think of this like a security badge scanner at the office door.
    You scan your badge. If it's valid, the door opens.
    If it's expired, the door stays shut. You don't even get
    to explain yourself.
    """
    result = await db.execute(
        select(User).where(User.id == payload["user_id"])
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found or deactivated."
        )

    result = await db.execute(select(Role).where(Role.id == user.role_id))
    role = result.scalar_one()

    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=role.name,
        is_active=user.is_active,
        created_at=user.created_at,
    )