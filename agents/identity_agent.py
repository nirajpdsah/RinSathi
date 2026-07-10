# agents/identity_agent.py
#
# Identity Agent: first agent in the ACLO five-agent pipeline.
# Replaces the document-based verification flow.
#
# WHAT IT DOES:
#   1. Accepts a NIN (National Identity Number) from the applicant
#   2. Verifies it against mock DoNIDCR (government identity database)
#   3. Extracts citizenship_no from the DoNIDCR response
#   4. Queries mock NeLIS using that citizenship_no (land registry)
#   5. Writes all verified identity + asset data into SharedState
#
# WHY THIS IS BETTER THAN OCR:
#   OCR reads what's printed on a document — it cannot verify if the
#   document is genuine. This agent queries the issuing authority directly.
#   A forged document cannot pass NIN verification because the NIN either
#   exists in DoNIDCR or it doesn't. There is no "high confidence fake."
#
# NRB ALIGNMENT:
#   NRB's KYC guidelines recommend NID-based verification for digital
#   lending. This agent implements exactly that recommendation.
#
# DESIGN RULE:
#   NEVER raises exceptions. Always returns SharedState.
#   On any failure, degrade gracefully and set manual_review_required = True.
#   The Compliance Agent downstream will detect this and add KYC_INCOMPLETE.
#
# Reads:  state.nin (set at pipeline entry by the loan application form)
# Writes: document_verified, extracted_fields, doc_confidence,
#         manual_review_required, verified_full_name, citizenship_no,
#         date_of_birth, permanent_address, sex,
#         total_land_ropani, total_land_aana, total_land_parcels

import httpx
from agents.shared_state import SharedState
from config import get_settings

settings = get_settings()

# ── Endpoint configuration ────────────────────────────────────────────────────
# In development: points to your own FastAPI mock endpoints
# In production:  change these two URLs to real government API endpoints
#                 Zero changes needed in this agent — only config changes
#
# We read from config so these can be set per environment in .env:
#   DONIDCR_URL=https://api.donidcr.gov.np/verify      (production)
#   DONIDCR_URL=http://localhost:8000/api/v1/mock/donidcr/verify  (dev)
DONIDCR_URL = getattr(settings, "DONIDCR_URL",
              "http://localhost:8000/api/v1/mock/donidcr/verify")
NELIS_URL   = getattr(settings, "NELIS_URL",
              "http://localhost:8000/api/v1/mock/nelis/lookup")
CIB_URL     = getattr(settings, "CIB_URL",
              "http://localhost:8000/api/v1/mock/cib/lookup")

# Timeout in seconds for government API calls
# If the government server doesn't respond in time, we degrade gracefully
API_TIMEOUT = 10.0


class IdentityAgent:
    """
    Verifies applicant identity and land assets using government databases.

    Replaces the old document-based verification flow in the five-agent pipeline.
    All downstream agents (Income, Score, Compliance, Decision) are
    completely unaware of this change — SharedState field names unchanged.

    Defense note:
        Trust in this system comes from querying authoritative government
        sources directly, not from interpreting document images. This is
        the same verification approach used by NMB Bank and other NRB-
        regulated institutions for digital KYC.
    """

    async def run(self, state: SharedState) -> SharedState:
        """
        Main entry point. Runs DoNIDCR + NeLIS verification in sequence.
        Returns SharedState whether success or failure — never raises.

        Args:
            state: SharedState with state.nin already populated
                   (set by the loan application form handler)

        Returns:
            state: SharedState with identity and asset fields populated
        """
        try:
            # ── Validate that NIN was provided ────────────────────────────────
            # The pipeline entry point should always set state.nin
            # but we check defensively
            if not state.nin or not state.nin.strip():
                return self._fail(state, reason="NIN not provided")

            nin = state.nin.strip().upper()

            # ── Step 1: Verify NIN against DoNIDCR ───────────────────────────
            citizen = await self._verify_nin(nin)

            # _verify_nin returns None on any failure
            # Failure reasons are already logged inside _verify_nin
            if citizen is None:
                return self._fail(state, reason="DoNIDCR verification failed")

            # ── Step 2: Write identity data to SharedState ───────────────────
            # Confidence is 1.0 because this data comes from the government
            # issuing authority — the highest possible confidence level
            state.verified_full_name = citizen["full_name"]
            state.citizenship_no     = citizen["citizenship_no"]
            state.date_of_birth      = citizen["date_of_birth"]
            state.permanent_address  = citizen["permanent_address"]
            state.sex                = citizen["sex"]

            # Build extracted_fields in the same shape as the old OCR agent
            # This maintains compatibility with any downstream code that
            # reads state.extracted_fields
            state.extracted_fields = {
                "full_name": {
                    "value":      citizen["full_name"],
                    "confidence": 1.0,   # Government-verified
                    "source":     "DoNIDCR"
                },
                "citizenship_no": {
                    "value":      citizen["citizenship_no"],
                    "confidence": 1.0,
                    "source":     "DoNIDCR"
                },
                "date_of_birth": {
                    "value":      citizen["date_of_birth"],
                    "confidence": 1.0,
                    "source":     "DoNIDCR"
                },
                "permanent_address": {
                    "value":      citizen["permanent_address"],
                    "confidence": 1.0,
                    "source":     "DoNIDCR"
                },
            }

            # ── Step 3: Query NeLIS for land assets ───────────────────────────
            # Uses citizenship_no as the bridge — not NIN
            # This accurately reflects real NeLIS query behavior
            assets = await self._lookup_land(citizen["citizenship_no"])

            if assets is None:
                # NeLIS query failed — this is not a KYC failure
                # Identity is verified. We just don't have asset data.
                # Set land values to zero and continue pipeline.
                # Compliance Agent will note missing asset verification.
                state.total_land_parcels = 0
                state.total_land_ropani  = 0
                state.total_land_aana    = 0
                state.total_land_value_npr = 0     # NEW
            else:
                state.total_land_parcels = assets["total_parcels"]
                state.total_land_ropani  = assets["total_area_ropani"]
                state.total_land_aana    = assets["total_area_aana"]
                state.total_land_value_npr = assets["total_asset_value_npr"]   # NEW

                # Add land data to extracted_fields for audit trail
                state.extracted_fields["land_assets"] = {
                    "value": (
                        f"{assets['total_parcels']} parcel(s), "
                        f"{assets['total_area_ropani']} ropani "
                        f"{assets['total_area_aana']} aana"
                    ),
                    "confidence": 1.0,
                    "source": "NeLIS"
                }

            # ── Step 4: Query CIB for prior credit history ────────────────────────────
            # CIB = Karja Suchana Kendra Limited, Nepal's credit bureau — checking
            # is mandatory under NRB regulation for loans NPR 1,000,000+.
            cib_data = await self._lookup_cib(citizen["citizenship_no"])

            if cib_data is None:
                state.is_blacklisted     = False
                state.max_dpd_bucket     = "none"
                state.active_loan_count  = 0
                state.cib_records_count  = 0
                state.nepal_credit_score = None
            else:
                state.is_blacklisted     = cib_data["is_blacklisted"]
                state.max_dpd_bucket     = cib_data["max_dpd_bucket"]
                state.active_loan_count  = cib_data["active_loan_count"]
                state.cib_records_count  = cib_data["total_records"]
                state.nepal_credit_score = cib_data["nepal_credit_score"]

            # ── Step 5: Mark verification as successful ───────────────────────
            # doc_confidence = 1.0 because government database is authoritative
            # This is significantly more reliable than OCR (typically 0.7-0.9)
            state.document_verified      = True
            state.doc_confidence         = 1.0
            state.manual_review_required = False

        except Exception as e:
            # Catch-all safety net — same pattern as the older verification flow
            # One agent failure must never crash the entire pipeline
            print(f"IdentityAgent: Unexpected error: {e}")
            return self._fail(state, reason="Unexpected error in Identity Agent")

        return state


    async def _verify_nin(self, nin: str) -> dict | None:
        """
        Calls DoNIDCR endpoint and returns citizen data dict.

        Handles all HTTP error cases cleanly:
        - 404: NIN not found in DoNIDCR
        - 410: Person is deceased
        - 503: Mock database not found (seed scripts not run)
        - Any other error: network issue or server error

        Returns None on any failure so the caller can degrade gracefully.
        """
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                response = await client.post(
                    DONIDCR_URL,
                    json={"nin": nin}
                )

            if response.status_code == 200:
                return response.json()

            elif response.status_code == 404:
                # NIN does not exist in DoNIDCR
                print(f"IdentityAgent: NIN '{nin}' not found in DoNIDCR")
                return None

            elif response.status_code == 410:
                # Person is deceased — hard stop
                # This is the most important rejection case for fraud prevention
                print(f"IdentityAgent: NIN '{nin}' belongs to a deceased individual")
                return None

            else:
                print(f"IdentityAgent: DoNIDCR returned unexpected status {response.status_code}")
                return None

        except httpx.TimeoutException:
            print(f"IdentityAgent: DoNIDCR API timed out after {API_TIMEOUT}s")
            return None

        except httpx.RequestError as e:
            print(f"IdentityAgent: DoNIDCR connection error: {e}")
            return None


    async def _lookup_land(self, citizenship_no: str) -> dict | None:
        """
        Calls NeLIS endpoint and returns land asset data dict.

        Zero parcels is NOT a failure — some citizens own no land.
        Returns None only if the API call itself fails (network/server error).
        Returns the response dict (with empty parcels list) if citizen
        simply owns no land.
        """
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                response = await client.post(
                    NELIS_URL,
                    json={"citizenship_no": citizenship_no}
                )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"IdentityAgent: NeLIS returned status {response.status_code}")
                return None

        except httpx.TimeoutException:
            print(f"IdentityAgent: NeLIS API timed out after {API_TIMEOUT}s")
            return None

        except httpx.RequestError as e:
            print(f"IdentityAgent: NeLIS connection error: {e}")
            return None

    async def _lookup_cib(self, citizenship_no: str) -> dict | None:
        """
        Calls the mock CIB endpoint. Zero records is a valid result.
        """
        try:
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                response = await client.post(
                    CIB_URL, json={"citizenship_no": citizenship_no}
                )
            if response.status_code == 200:
                return response.json()
            print(f"IdentityAgent: CIB returned status {response.status_code}")
            return None
        except httpx.TimeoutException:
            print(f"IdentityAgent: CIB API timed out after {API_TIMEOUT}s")
            return None
        except httpx.RequestError as e:
            print(f"IdentityAgent: CIB connection error: {e}")
            return None

    def _fail(self, state: SharedState, reason: str = "") -> SharedState:
        """
        Sets SharedState to a clean failure state.

        Called whenever identity verification cannot complete.
        The Compliance Agent downstream will detect
        manual_review_required = True and add KYC_INCOMPLETE flag.
        That flag forces Decision Agent to output Refer or Reject.
        The pipeline never stops — it degrades gracefully.

        Args:
            state:  current SharedState
            reason: human-readable reason for logging
        """
        if reason:
            print(f"IdentityAgent: Verification failed — {reason}")

        state.document_verified      = False
        state.doc_confidence         = 0.0
        state.manual_review_required = True

        # Zero out asset fields — no verified data available
        state.total_land_parcels     = 0
        state.total_land_ropani      = 0
        state.total_land_aana        = 0

        return state