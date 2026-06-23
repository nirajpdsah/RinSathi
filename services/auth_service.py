# services/auth_service.py
#
# The back office of RinSathi authentication.
#
# This file does the actual work:
#   - Talking to Google's servers to verify tokens
#   - Hashing and checking passwords
#   - Querying the database to find or create users
#
# Why separate from the router?
# ─────────────────────────────
# Today your auth is used by a web frontend.
# Tomorrow you might add a mobile app.
# The day after, an admin CLI tool.
#
# All three need the same auth logic. If that logic lived
# inside the router, you'd copy-paste it three times.
# Copy-pasted code is the enemy — one bug fix in one place,
# you forget the other two. The system breaks in production
# at 2am on a Tuesday.
#
# Put logic in the service once. Every consumer uses it.
# That's the rule.

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from fastapi import HTTPException, status

from db.models import User, Role
from config import get_settings

settings = get_settings()

# ── Password hashing setup ────────────────────────────────────────────────────
# bcrypt is the industry standard for password hashing in fintech.
#
# Why not MD5 or SHA256?
# Because MD5 and SHA256 are FAST — a modern GPU can try billions
# per second. bcrypt is deliberately SLOW (takes ~0.3 seconds).
# That slowness is a security feature. If someone steals your database,
# cracking one password takes 0.3 seconds. Cracking a million?
# 100 years. That's the point.
#
# deprecated="auto" means: if an old hash format is detected,
# passlib will automatically upgrade it on next login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ════════════════════════════════════════════════════════
# PASSWORD UTILITIES
# ════════════════════════════════════════════════════════

def verify_password(plain: str, hashed: str) -> bool:
    """
    Checks if a plain text password matches a bcrypt hash.

    We never reverse the hash — that's mathematically impossible
    with bcrypt. Instead we hash the input and compare outputs.

    Used when an officer types their password at login.
    """
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    """
    Converts a plain text password into a bcrypt hash.

    Use this when creating officer accounts:
        hashed = hash_password("Officer@1234")
        # Store 'hashed' in DB, throw away the original

    Never called during login — only during account creation.
    """
    return pwd_context.hash(plain)


# ════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ════════════════════════════════════════════════════════

async def verify_google_token(token: str) -> dict:
    """
    Sends the Google ID token to Google's servers for verification.

    Why do we verify with Google instead of reading the token ourselves?
    ────────────────────────────────────────────────────────────────────
    Because anyone can create a fake token that looks like a Google token.
    The only way to know it's real is to ask Google directly.

    Google's response tells us:
      - This token was genuinely issued by Google
      - It was issued for YOUR app specifically (your client_id)
      - It hasn't expired
      - The email and name inside it are trustworthy

    Returns dict with: google_id, email, full_name
    Raises HTTP 401 if the token is fake, expired, or for a different app.
    """
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url)

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google could not verify your login. Please try again."
        )

    data = response.json()

    # This check is critical for security.
    # "aud" means "audience" — who this token was issued FOR.
    # If someone logs into a different Google app, gets a token,
    # and sends it to YOUR backend — this check catches it.
    # The token is real, but it wasn't made for you.
    if data.get("aud") != settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This login token was not issued for RinSathi."
        )

    return {
        "google_id": data["sub"],           # "sub" = subject = Google's unique user ID
        "email":     data["email"],
        "full_name": data.get("name", ""),
    }


async def get_or_create_client(google_data: dict, db: AsyncSession) -> User:
    """
    Finds an existing client by Google ID, or creates a new account.

    This handles two situations:
    ────────────────────────────
    Situation A — Ram logs in for the first time:
      Google gives us his ID, email, name.
      We don't find him in our DB.
      We create a new client account for him.
      He lands on the dashboard as a new user.

    Situation B — Ram logs in again next week:
      Google gives us the same ID.
      We find his existing account.
      We return it. No new account created.

    This pattern is called "get or create" — one of the most
    common patterns in user authentication systems.
    """
    # Try to find by Google ID first — most common case (returning user)
    result = await db.execute(
        select(User).where(User.google_id == google_data["google_id"])
    )
    user = result.scalar_one_or_none()

    if user:
        # Returning user — just give them back
        return user

    # Check if someone already registered this email another way.
    # Edge case: officer manually added this email, then the person
    # tries to log in via Google. We catch this gracefully.
    result = await db.execute(
        select(User).where(User.email == google_data["email"])
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists."
        )

    # New user — look up the "client" role ID
    result = await db.execute(
        select(Role).where(Role.name == "client")
    )
    client_role = result.scalar_one_or_none()

    if not client_role:
        # This means the roles table wasn't seeded properly
        # Shouldn't happen if you ran the SQL we wrote earlier
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System configuration error. Contact administrator."
        )

    # Create the new client account
    new_user = User(
        email=google_data["email"],
        full_name=google_data["full_name"],
        role_id=client_role.id,
        google_id=google_data["google_id"],
        password_hash=None,    # Clients never have passwords
        is_active=True,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)   # Fetch the DB-generated UUID and timestamps

    return new_user


# ════════════════════════════════════════════════════════
# OFFICER LOGIN
# ════════════════════════════════════════════════════════

async def authenticate_officer(
    email: str,
    password: str,
    db: AsyncSession
) -> User:
    """
    Verifies officer email + password credentials.

    Three things must ALL be true:
      1. Email exists in our database
      2. Account is active (not disabled)
      3. Password matches the stored bcrypt hash
      4. The account's role is "officer" (not a client)

    Security note on error messages:
    ──────────────────────────────────
    We return the SAME error message whether the email doesn't
    exist OR the password is wrong. This is intentional.

    If we said "email not found" for wrong email and
    "wrong password" for wrong password — an attacker
    could enumerate which emails are registered in our system
    just by trying different emails and reading the error.

    "Invalid email or password" tells them nothing useful.
    This is standard security practice in fintech.
    """
    # One generic error used for all failure cases
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password."
    )

    # Step 1: Find the user by email
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise invalid

    # Step 2: Check account is active
    # A deactivated officer gets a slightly different message
    # because they deserve to know WHY they can't log in
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Contact the administrator."
        )

    # Step 3: Officers must have a password (clients don't)
    if not user.password_hash:
        raise invalid

    # Step 4: Verify the password against the stored hash
    if not verify_password(password, user.password_hash):
        raise invalid

    # Step 5: Confirm this is actually an officer account
    # A client trying to log in via the officer portal gets rejected here
    result = await db.execute(
        select(Role).where(Role.id == user.role_id)
    )
    role = result.scalar_one_or_none()

    if not role or role.name != "officer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This login page is for loan officers only."
        )

    return user