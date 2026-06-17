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

    # ── Document Agent outputs ── None until Document Agent runs ─────────────
    document_verified:        Optional[bool]  = None
    # True if OCR confidence meets threshold; False if scan quality is too low

    extracted_fields:         Optional[dict]  = None
    # Dict of field name → {value, confidence}
    # Example: {"name": {"value": "Ram Thapa", "confidence": 0.91}}

    doc_confidence:           Optional[float] = None
    # Mean OCR confidence score across all extracted fields (0.0 – 1.0)

    manual_review_required:   bool            = False
    # Set True when doc_confidence < MIN_KYC_CONFIDENCE
    # Compliance Agent detects this and adds KYC_INCOMPLETE flag

    # ── Income Agent outputs ── None until Income Agent runs ──────────────────
    monthly_income_npr:       Optional[float] = None
    # Normalised monthly income in raw NPR — NEVER scaled or transformed here.
    # Scaling only happens inside the XGBoost Pipeline object in Score Agent.
    # Keeping raw NPR here allows SHAP explanations to show real money amounts.

    income_confidence:        Optional[float] = None
    # Confidence in the income estimate (0.0 – 1.0)
    # Low if fewer than 3 months of data, or if data is highly irregular

    income_sources:           list[str]       = []
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
