# routers/mock_gov.py
#
# Mock Government API Endpoints
#
# These endpoints simulate two Nepal government systems:
#   1. DoNIDCR — Department of National ID and Civil Registration
#   2. NeLIS   — Nepal Land Information System
#
# WHY THIS EXISTS:
#   In production, RinSathi would call real government APIs via
#   NRB-mediated agreements. Those agreements don't exist yet.
#   These mock endpoints allow the full pipeline to run during
#   development and defense demonstration.
#
# HOW IT WORKS:
#   - Data lives in SQLite files: donidcr.db and nelis.db
#   - These endpoints query those files and return realistic responses
#   - The Identity Agent calls these endpoints exactly as it would
#     call the real government APIs — same request/response shape
#   - Swapping mock for real requires changing only the base URL
#     in one environment variable
#
# DEFENSE TALKING POINT:
#   "Production integration requires NRB-mediated API agreements
#    with DoNIDCR and NeLIS. Our architecture is designed for this
#    transition — the agent code requires zero changes, only the
#    endpoint URL changes in the configuration."
#
# ENDPOINTS:
#   POST /mock/donidcr/verify   → verify NIN, return citizen record
#   POST /mock/nelis/lookup     → lookup land parcels by citizenship_no

import sqlite3
import os
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/mock", tags=["Mock Government APIs"])

# ── Database paths ─────────────────────────────────────────────────────────────
# Resolve relative to project root, not this file's location
# Assumes you run uvicorn from D:\RinSathi
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONIDCR_PATH = os.path.join(BASE_DIR, "mock_databases", "donidcr.db")
NELIS_PATH   = os.path.join(BASE_DIR, "mock_databases", "nelis.db")


# ══════════════════════════════════════════════════════════════
# SCHEMAS — Request and Response shapes
# ══════════════════════════════════════════════════════════════

class NINVerifyRequest(BaseModel):
    """
    What your Identity Agent sends to DoNIDCR.
    Just the NIN — nothing else.
    The government system looks up everything from that one number.
    """
    nin: str  # e.g. "NID-001"


class CitizenResponse(BaseModel):
    """
    What DoNIDCR returns after successful NIN verification.
    Mirrors exactly what appears on a real Nepal NID card.

    This is the data your Identity Agent extracts and stores
    in SharedState for the rest of the pipeline to use.
    """
    nin:              str
    full_name:        str
    date_of_issue:    str
    nationality:      str
    date_of_birth:    str
    sex:              str
    permanent_address: str
    citizenship_type: str
    citizenship_no:   str   # ← the bridge to NeLIS
    status:           str   # "active" or "deceased"


class LandParcel(BaseModel):
    """
    One land parcel record from NeLIS.
    Represents one Lalpurja entry.

    A single citizen can own multiple parcels —
    your Identity Agent receives a list of these.
    """
    sanket_no:        str
    citizenship_no:   str
    full_name:        str
    land_area_ropani: int
    land_area_aana:   int
    district:            str      # NEW — needed to explain the valuation
    land_type:           str      # NEW — needed to explain the valuation
    estimated_value_npr: int      # NEW — the actual rupee figure


class CitizenshipLookupRequest(BaseModel):
    """
    What your Identity Agent sends to NeLIS.
    Uses citizenship_no — not NIN — because Lalpurja
    contains citizenship number, not NIN.

    The bridge:
        DoNIDCR response → citizenship_no → NeLIS query
    """
    citizenship_no: str  # e.g. "27-01-75-00234"


class NeLISResponse(BaseModel):
    """
    What NeLIS returns — all land parcels for a given citizenship_no.

    total_area_ropani and total_area_aana are pre-calculated
    so your Score Agent doesn't have to sum them manually.
    """
    citizenship_no:   str
    parcels:          List[LandParcel]
    total_parcels:    int
    total_area_ropani: int   # Sum of all parcels in ropani
    total_area_aana:  int    # Sum of all parcels in aana (remainder)
    total_asset_value_npr: int      # NEW — sum of every parcel's value 


# ══════════════════════════════════════════════════════════════
# HELPER — SQLite connection
# ══════════════════════════════════════════════════════════════

def get_sqlite_connection(db_path: str) -> sqlite3.Connection:
    """
    Opens a SQLite connection and configures it to return
    rows as dictionaries (column_name: value) instead of
    plain tuples.

    Without this, row[0] is the only way to access values.
    With this, row["full_name"] works — much cleaner code.
    """
    if not os.path.exists(db_path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Mock database not found at {db_path}. "
                   f"Run seed scripts first: python mock_databases/seed_donidcr.py"
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Makes rows accessible as dicts
    return conn


# ══════════════════════════════════════════════════════════════
# ENDPOINT 1: DoNIDCR — NIN Verification
# ══════════════════════════════════════════════════════════════

@router.post(
    "/donidcr/verify",
    response_model=CitizenResponse,
    summary="Verify NIN against DoNIDCR",
    description=(
        "Simulates the DoNIDCR identity verification API. "
        "Accepts a National Identity Number (NIN) and returns "
        "the citizen's full identity record if found and active."
    )
)
async def verify_nin(request: NINVerifyRequest):
    """
    Verifies a NIN against the mock DoNIDCR database.

    Three possible outcomes:
    ──────────────────────────────────────────────────
    1. NIN not found     → HTTP 404
       "This NIN does not exist in DoNIDCR records."
       Could mean: typo, fake NIN, unregistered citizen

    2. NIN is deceased   → HTTP 410 GONE
       "This NIN belongs to a deceased individual."
       HTTP 410 means "this resource existed but is gone"
       — semantically correct for a deceased person's record.
       Your Identity Agent must catch this and reject the
       application immediately. Prevents fraud using
       deceased persons' identity documents.

    3. NIN found, active → HTTP 200 with full citizen record
       Pipeline continues to NeLIS lookup.
    """
    conn   = get_sqlite_connection(DONIDCR_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT * FROM citizens WHERE nin = ?",
            (request.nin.strip().upper(),)
            # .strip() removes accidental whitespace
            # .upper() makes NID-001 and nid-001 both work
        )
        row = cursor.fetchone()

    finally:
        conn.close()  # Always close connection, even if query fails

    # Outcome 1: NIN not in database at all
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NIN '{request.nin}' not found in DoNIDCR records. "
                   f"Please verify the number and try again."
        )

    # Outcome 2: Person is deceased
    # HTTP 410 Gone — semantically correct, and distinctive enough
    # that your Identity Agent can handle it separately from 404
    if row["status"] == "deceased":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"NIN '{request.nin}' belongs to a deceased individual. "
                   f"Identity verification failed. "
                   f"If you believe this is an error, contact DoNIDCR."
        )

    # Outcome 3: Valid active citizen — return full record
    return CitizenResponse(
        nin=              row["nin"],
        full_name=        row["full_name"],
        date_of_issue=    row["date_of_issue"],
        nationality=      row["nationality"],
        date_of_birth=    row["date_of_birth"],
        sex=              row["sex"],
        permanent_address=row["permanent_address"],
        citizenship_type= row["citizenship_type"],
        citizenship_no=   row["citizenship_no"],
        status=           row["status"],
    )


# ══════════════════════════════════════════════════════════════
# ENDPOINT 2: NeLIS — Land Parcel Lookup
# ══════════════════════════════════════════════════════════════

@router.post(
    "/nelis/lookup",
    response_model=NeLISResponse,
    summary="Lookup land parcels by citizenship number",
    description=(
        "Simulates the NeLIS land registry API. "
        "Accepts a citizenship number and returns all land parcels "
        "registered under that number, with total area calculated."
    )
)
async def lookup_land(request: CitizenshipLookupRequest):
    """
    Looks up all land parcels owned by a citizenship number.

    Two possible outcomes:
    ──────────────────────────────────────────────────
    1. No parcels found → HTTP 200 with empty list
       This is NOT an error. Some citizens own no land.
       NID-050 demonstrates this scenario.
       Your Score Agent must handle zero assets gracefully
       — it affects the credit score but doesn't crash the pipeline.

    2. Parcels found → HTTP 200 with full parcel list
       Includes pre-calculated totals for Score Agent convenience.

    NOTE: We intentionally do NOT return HTTP 404 for zero parcels.
    "No land found" is valid data, not an error. The pipeline
    continues — it just has zero asset collateral to work with.
    """
    conn   = get_sqlite_connection(NELIS_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT sanket_no, citizenship_no, full_name,
                   land_area_ropani, land_area_aana, district, land_type, estimated_value_npr
            FROM   land_parcels
            WHERE  citizenship_no = ?
            ORDER  BY sanket_no ASC
            """,
            (request.citizenship_no.strip(),)
        )
        rows = cursor.fetchall()

    finally:
        conn.close()

    # Convert SQLite rows to LandParcel objects
    parcels = [
    LandParcel(
        sanket_no=           row["sanket_no"],
        citizenship_no=      row["citizenship_no"],
        full_name=           row["full_name"],
        land_area_ropani=    row["land_area_ropani"],
        land_area_aana=      row["land_area_aana"],
        district=            row["district"],
        land_type=           row["land_type"],
        estimated_value_npr= row["estimated_value_npr"],
    )
    for row in rows
]

    # Pre-calculate total land area across all parcels
    # Score Agent uses this directly — no need to sum in the agent
    total_ropani = sum(p.land_area_ropani for p in parcels)
    total_aana   = sum(p.land_area_aana   for p in parcels)
    total_asset_value = sum(p.estimated_value_npr for p in parcels)
    total_asset_value_npr = sum(p.estimated_value_npr for p in parcels)

    # Normalize aana overflow into ropani
    # 1 ropani = 16 aana — if total aana >= 16, convert the overflow
    # Example: 3 ropani 18 aana → 4 ropani 2 aana
    extra_ropani, remaining_aana = divmod(total_aana, 16)
    total_ropani += extra_ropani
    total_aana    = remaining_aana

    return NeLISResponse(
    citizenship_no=       request.citizenship_no,
    parcels=              parcels,
    total_parcels=        len(parcels),
    total_area_ropani=    total_ropani,
    total_area_aana=      total_aana,
    total_asset_value_npr= total_asset_value,
)