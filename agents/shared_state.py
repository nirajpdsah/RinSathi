# ── agents/shared_state.py ────────────────────────────────────────────────────
# THE most important file in the project.
# SharedState is the single data contract flowing through all 5 agents.
# Think of it as an envelope: each agent opens it, adds results, passes it on.
# Designed before any agent is built — field names NEVER change after Sprint 1.

from pydantic import BaseModel, ConfigDict   # Pydantic v2 for runtime validation
from typing import Optional, Literal         # Type hints for optional and fixed-choice fields
import uuid                                  # For unique applicant identification


class SharedState(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True   # Validate EVERY field write, not just initialisation
        # This means if an agent writes the wrong type, it raises immediately
        # instead of silently passing bad data to the next agent.
        # Critical in a financial pipeline where wrong data = wrong loan decision.
    )

    # ── Request identity ── set at pipeline entry, never modified ─────────────
    applicant_id:     uuid.UUID   # Unique ID for this loan application
    loan_amount_npr:  float       # Requested loan amount in Nepali Rupees
    sector:           str         # Business sector (e.g. "agriculture", "retail")

    # ── Identity Agent outputs ── None until Identity Agent runs ──────────────
    # Same field names are preserved for downstream compatibility.

    document_verified:        Optional[bool]  = None
    # True if NIN verified successfully against DoNIDCR
    # False if NIN not found, deceased, or API error
    # Named 'document_verified' to maintain compatibility with Compliance Agent

    extracted_fields:         Optional[dict]  = None
    # Structured identity data from DoNIDCR + asset data from NeLIS
    # Same shape as before: {"field": {"value": ..., "confidence": ...}}
    # Confidence is 1.0 for government-verified data (authoritative source)

    doc_confidence:           Optional[float] = None
    # Identity verification confidence
    # 1.0 = NIN verified against DoNIDCR (authoritative)
    # 0.0 = verification failed

    manual_review_required:   bool            = False
    # True if identity verification fails — triggers KYC_INCOMPLETE in Compliance Agent

    # ── NEW: NIN verification results ─────────────────────────────────────────
    nin:                      Optional[str]   = None
    # The NIN provided by the applicant e.g. "NID-001"

    verified_full_name:       Optional[str]   = None
    # Full name as returned by DoNIDCR — authoritative source
    # Used by Income Agent for name_mismatch_detected check

    citizenship_no:           Optional[str]   = None
    # Citizenship number from DoNIDCR — the bridge to NeLIS
    # Also stored in applicants table for audit trail

    date_of_birth:            Optional[str]   = None
    permanent_address:        Optional[str]   = None
    sex:                      Optional[str]   = None

    # ── NEW: NeLIS asset verification results ─────────────────────────────────
    total_land_ropani:        Optional[int]   = None
    total_land_aana:          Optional[int]   = None
    total_land_parcels:       Optional[int]   = None
    total_land_value_npr:     Optional[int]   = None
    # Combined estimated market value of all verified land parcels, in NPR.
    # Calculated by NeLIS based on district rate and land type — this is
    # what the Compliance Agent actually compares against loan_amount_npr
    # for the loan-to-asset ratio check, not raw land area.
    # Number of Lalpurja entries found under this citizenship_no
    # Zero is valid — some applicants own no land

    # ── Income Agent outputs ── None until Income Agent runs ──────────────────
    monthly_income_npr:       Optional[float] = None
    # Normalised monthly income in raw NPR — NEVER scaled or transformed here.
    # Scaling only happens inside the XGBoost Pipeline object in Score Agent.
    # Keeping raw NPR here allows SHAP explanations to show real money amounts.

    income_confidence:        Optional[float] = None
    # Confidence in the income estimate (0.0 – 1.0)
    # Low if fewer than 3 months of data, or if data is highly irregular

    income_sources:           list[str]       = []
    name_mismatch_detected:   bool            = False
    # Which income signals were available, e.g. ["esewa", "remittance"]

    # ── Score Agent outputs ── None until Score Agent runs ────────────────────
    credit_score:             Optional[float]      = None
    # XGBoost probability of loan repayment (0.0 = high risk, 1.0 = low risk)

    shap_explanation:         Optional[list[dict]] = None
    # Top 5 SHAP feature contributions as human-readable sentences
    # Example: [{"feature": "monthly_income_npr",
    #             "readable_text": "Monthly income of NPR 25,000 increased score by 31%",
    #             "shap_value": 0.312}]

    # ── Compliance Agent outputs ── empty list = no violations ────────────────
    compliance_flags:         list[str]       = []
    # NRB rule violations detected, e.g. ["LOAN_TO_ASSET_BREACH", "KYC_INCOMPLETE"]
    # If this list is non-empty, Decision Agent MUST output "Refer" or "Reject"
    # regardless of what the credit_score says — compliance overrides everything

    # ── Decision Agent outputs ── None until Decision Agent runs ─────────────
    final_decision:  Optional[Literal["Recommend", "Reject", "Refer"]] = None
    # Recommend means the applicant is in a good position, but the loan officer makes final approval

    decision_reason:          Optional[str]   = None
    # Human-readable explanation of the decision — shown to loan officer and applicant

    audit_trail_path:         Optional[str]   = None
    # File path to the generated PDF audit report — stored in audit_logs table

    income_breakdown:  Optional[dict]  = None
    # Per-source detail, e.g.
    # {"esewa": {"monthly_avg": 30000, "accumulated_3mo": 90000},
    #  "remittance": {"monthly_avg": 35000, "accumulated_3mo": 105000}}

    total_accumulated_income_npr: Optional[float] = None
    # Sum of all sources' 3-month accumulated income — NOT the monthly average.
    # Gives the officer the full picture of cash actually seen over the window,
    # not just a blended monthly figure that hides volatility.

    qualification_score: Optional[float] = None
    # The final 0-100 auditable scorecard result — ML score (40%) +
    # asset coverage (25%) + income stability (20%) + compliance (15%).
    # This, not the raw ML probability, is what actually drives the
    # Approve/Refer/Reject threshold — the number an NRB auditor would
    # independently recompute to verify the decision.

    is_blacklisted:        bool            = False
    # True if formally blacklisted per NRB directive — the most serious
    # CIB signal, publicly notified for serious defaulters.

    max_dpd_bucket:        str             = "none"
    # Worst Days Past Due severity found in credit history:
    # "none" / "dpd_30" / "dpd_60" / "dpd_90_plus"

    active_loan_count:     int             = 0
    # Number of currently ongoing loans elsewhere.

    cib_records_count:     int             = 0
    # Total prior loan records — 0 means first-time borrower.

    nepal_credit_score:    Optional[int]   = None
    # Traditional Nepali CIB score, 60-960 scale, mirroring the real
    # convention used by Karja Suchana Kendra Limited — shown alongside
    # our own qualification_score for comparison in officer/client views.

    loan_type:                   str            = "microfinance"
    # "microfinance" (land-secured, default) or "vehicle" (vehicle-purchase loan)

    vehicle_make_model:          Optional[str]  = None
    vehicle_is_new:               Optional[bool] = None
    vehicle_purchase_price_npr:  Optional[int]  = None
    vehicle_value_npr:            Optional[int]  = None
    # Estimated collateral value of the vehicle being purchased —
    # either the dealer-quoted price directly, or our reference estimate.