# fix_compliance_decision.py
# Writes Compliance Agent, Decision Agent, and registers both in main.py
# Run: python fix_compliance_decision.py

import os

# ── agents/compliance_agent.py ────────────────────────────────────────────────
compliance_code = """\
# agents/compliance_agent.py
# Compliance Agent: fourth agent in the ACLO pipeline.
# Checks the applicant's data against NRB Unified Directives 2080.
# THIS IS NOT ML. It is a deterministic rule engine — pure Python conditions.
# All thresholds come from config.py, never hardcoded here.
#
# Design rule: NEVER raises exceptions. NEVER blocks the pipeline.
# On any rule violation, it appends a flag to compliance_flags and continues.
# The Decision Agent reads compliance_flags and acts on them.

from agents.shared_state import SharedState   # Central data contract
from config import get_settings               # All thresholds from .env

settings = get_settings()


class ComplianceAgent:
    \"\"\"
    Checks applicant data against NRB regulatory requirements.

    Reads from SharedState:
        monthly_income_npr  — for loan-to-income ratio check
        income_confidence   — for KYC quality check
        doc_confidence      — for KYC document quality check
        manual_review_required — direct KYC flag from Document Agent
        extracted_fields    — for loan_amount and sector
        loan_amount_npr     — the requested loan amount
        sector              — applicant's business sector

    Writes to SharedState:
        compliance_flags    — list of NRB violation codes found
                             Empty list = all checks passed = clean applicant

    Defence note: Compliance Agent has HIGHEST PRIORITY in the pipeline.
    If compliance_flags is non-empty, Decision Agent outputs Refer or Reject
    REGARDLESS of what the credit score says. This is a regulatory requirement —
    a clean credit score does not override an NRB compliance breach.
    \"\"\"

    async def run(self, state: SharedState) -> SharedState:
        # Always returns state. Appends violation codes to compliance_flags.
        # Each check is independent — one failure does not stop other checks.
        try:
            state.compliance_flags = []   # Reset flags at start of compliance run

            # ── Check 1: KYC — Document quality ───────────────────────────────
            # If Document Agent flagged manual review, OCR confidence was too low.
            # NRB requires verified identity before any credit decision.
            if state.manual_review_required:
                state.compliance_flags.append("KYC_INCOMPLETE")
                # Note: this does NOT stop other checks. We continue to catch
                # ALL violations in one pass, not just the first one found.

            # ── Check 2: KYC — Income confidence ──────────────────────────────
            # Very low income confidence means we cannot verify the income claims.
            # Below 0.25 suggests either no data or highly unreliable data.
            income_conf = state.income_confidence or 0.0
            if income_conf < 0.25:
                state.compliance_flags.append("INCOME_UNVERIFIABLE")

            # ── Check 3: Loan-to-asset ratio ──────────────────────────────────
            # NRB Unified Directive: loan cannot exceed 75% of asset value.
            # loan_to_asset = loan_amount / estimated_asset_value
            # We estimate asset value from income (simplified for Sprint 3;
            # full implementation uses Lalpurja land value from Document Agent).
            loan_amount    = state.loan_amount_npr or 0.0
            monthly_income = state.monthly_income_npr or 0.0

            if loan_amount > 0 and monthly_income > 0:
                # Simplified proxy: annual income × 10 as rough asset estimate
                # In production: replace with actual land value from Lalpurja
                estimated_assets = monthly_income * 12 * 10
                loan_to_asset    = loan_amount / estimated_assets

                if loan_to_asset > settings.MAX_LOAN_TO_ASSET:
                    # Loan amount exceeds NRB's 75% loan-to-asset limit
                    state.compliance_flags.append("LOAN_TO_ASSET_BREACH")

            # ── Check 4: Agricultural sector exposure limit ───────────────────
            # NRB caps agricultural sector lending to prevent over-concentration.
            # AGRI_SECTOR_LIMIT_NPR from config (default NPR 500,000).
            sector = (state.sector or "").lower()
            is_agricultural = any(
                keyword in sector
                for keyword in ["agriculture", "farming", "agri", "crop", "livestock"]
            )
            if is_agricultural and loan_amount > settings.AGRI_SECTOR_LIMIT_NPR:
                state.compliance_flags.append("SECTOR_EXPOSURE_LIMIT")

            # ── Check 5: AML — unusually large single income signal ────────────
            # Anti-Money Laundering: flag if any single signal suggests
            # an unusually large one-time cash deposit (structuring risk).
            # In production: check each individual transaction.
            # Here we use monthly income as a proxy for simplicity.
            if monthly_income > settings.AML_TXN_LIMIT_NPR:
                # Monthly income above NPR 1,000,000 — flag for review
                state.compliance_flags.append("AML_FLAG")

            # ── Check 6: Zero income with non-trivial loan request ─────────────
            # If Income Agent found no income signals and loan > NPR 10,000,
            # this is likely a data submission error or attempt to game the system.
            if monthly_income == 0.0 and loan_amount > 10_000:
                state.compliance_flags.append("NO_INCOME_SIGNALS")

        except Exception:
            # Safety net — if something breaks, flag for human review
            # rather than letting a potentially non-compliant application through.
            if "SYSTEM_ERROR" not in state.compliance_flags:
                state.compliance_flags.append("SYSTEM_ERROR")

        return state   # Always return state — never raise
"""

# ── agents/decision_agent.py ──────────────────────────────────────────────────
decision_code = """\
# agents/decision_agent.py
# Decision Agent: fifth and final agent in the ACLO pipeline.
# Reads the complete SharedState and issues one of three verdicts:
#   Approve — fully automated approval
#   Reject  — fully automated rejection
#   Refer   — route to human loan officer for manual review
#
# PRIORITY ORDER IS STRICT. Do not reorder these checks.
# Compliance always overrides score. Missing data always routes to Refer.

from agents.shared_state import SharedState   # Central data contract
from config import get_settings               # Score thresholds from config

settings = get_settings()


class DecisionAgent:
    \"\"\"
    Issues the final credit decision for a loan application.

    Reads from SharedState:
        compliance_flags  — any NRB violations (overrides everything)
        credit_score      — XGBoost repayment probability (0.0-1.0)
        manual_review_required — Document Agent quality flag
        monthly_income_npr — used in decision_reason text
        loan_amount_npr   — used in decision_reason text

    Writes to SharedState:
        final_decision   — \"Approve\" | \"Reject\" | \"Refer\"
        decision_reason  — human-readable explanation for the loan officer

    Defence note:
    This 3-verdict design is intentional. Banking regulators (NRB) require
    human oversight for edge cases. A binary Approve/Reject system would be
    a regulatory violation for ambiguous cases. The Refer path is the
    Human-in-the-Loop mechanism that satisfies NRB audit requirements.
    \"\"\"

    async def run(self, state: SharedState) -> SharedState:
        try:
            # ── PRIORITY 1: Compliance flags override EVERYTHING ───────────────
            # Even a perfect credit score cannot override an NRB rule violation.
            # This is the most important rule in the entire pipeline.
            if state.compliance_flags:
                # Build a readable summary of which rules were violated
                flag_descriptions = {
                    "KYC_INCOMPLETE":        "Identity document quality below KYC threshold",
                    "INCOME_UNVERIFIABLE":   "Income data insufficient for reliable assessment",
                    "LOAN_TO_ASSET_BREACH":  "Loan amount exceeds NRB 75% loan-to-asset limit",
                    "SECTOR_EXPOSURE_LIMIT": "Agricultural loan amount exceeds NRB sector cap",
                    "AML_FLAG":              "Income pattern flagged for AML review",
                    "NO_INCOME_SIGNALS":     "No income data provided for non-trivial loan",
                    "SYSTEM_ERROR":          "Pipeline error — manual verification required",
                }
                # Build reason string from all flags found
                reasons = [
                    flag_descriptions.get(flag, flag)   # Use description or raw flag code
                    for flag in state.compliance_flags
                ]
                state.final_decision  = "Refer"
                state.decision_reason = (
                    f"Referred for manual review. "
                    f"Compliance flags: {'; '.join(reasons)}."
                )
                return state   # Stop here — no further checks needed

            # ── PRIORITY 2: Missing credit score → cannot auto-decide ──────────
            # If Score Agent failed or returned None, we have no basis for
            # an automated decision. Route to human review.
            if state.credit_score is None:
                state.final_decision  = "Refer"
                state.decision_reason = (
                    "Referred: credit score could not be calculated. "
                    "Manual assessment required."
                )
                return state

            # ── PRIORITY 3: Score-based decision ──────────────────────────────
            # APPROVE_THRESHOLD = 0.65 from config (credit_score >= 0.65 → Approve)
            # REFER_THRESHOLD   = 0.40 from config (credit_score >= 0.40 → Refer)
            # Below REFER_THRESHOLD → Reject
            score   = state.credit_score
            income  = state.monthly_income_npr or 0.0
            loan    = state.loan_amount_npr    or 0.0

            if score >= settings.APPROVE_THRESHOLD:
                # High confidence of repayment — automated approval
                state.final_decision  = "Approve"
                state.decision_reason = (
                    f"Approved. Repayment probability: {score:.1%}. "
                    f"Monthly income NPR {income:,.0f} supports "
                    f"loan request of NPR {loan:,.0f}. "
                    f"All NRB compliance checks passed."
                )

            elif score >= settings.REFER_THRESHOLD:
                # Borderline case — human judgment needed
                state.final_decision  = "Refer"
                state.decision_reason = (
                    f"Referred for manual review. "
                    f"Repayment probability {score:.1%} is in the review range "
                    f"({settings.REFER_THRESHOLD:.0%}–{settings.APPROVE_THRESHOLD:.0%}). "
                    f"Loan officer assessment recommended."
                )

            else:
                # Low repayment probability — automated rejection
                state.final_decision  = "Reject"
                state.decision_reason = (
                    f"Rejected. Repayment probability {score:.1%} is below "
                    f"the minimum threshold of {settings.REFER_THRESHOLD:.0%}. "
                    f"Insufficient income signals or high risk profile detected."
                )

        except Exception:
            # Safety net — unknown error → route to human, never auto-approve
            state.final_decision  = "Refer"
            state.decision_reason = "System error during decision processing. Manual review required."

        return state   # Always return state — never raise
"""

# ── api/routes/loan.py ────────────────────────────────────────────────────────
loan_route_code = """\
# api/routes/loan.py
# Full 5-agent pipeline endpoint: POST /api/v1/loan/apply
# This is the main endpoint that wires all agents together.
# Document Agent + Income Agent run in PARALLEL (asyncio.gather).
# Score → Compliance → Decision run sequentially (each depends on prior).

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional
import asyncio      # For parallel agent execution
import time         # For pipeline timing
import uuid

from agents.shared_state    import SharedState
from agents.document_agent  import DocumentAgent
from agents.income_agent    import IncomeAgent
from agents.compliance_agent import ComplianceAgent
from agents.decision_agent  import DecisionAgent
from config import get_settings

settings = get_settings()
router   = APIRouter()

# Instantiate all agents once at module load — not per-request
doc_agent        = DocumentAgent()
income_agent     = IncomeAgent()
compliance_agent = ComplianceAgent()
decision_agent   = DecisionAgent()


class LoanDecisionResponse(BaseModel):
    applicant_id:       uuid.UUID
    final_decision:     str           # Approve | Reject | Refer
    decision_reason:    str           # Human-readable explanation
    credit_score:       Optional[float] = None    # XGBoost repayment probability
    compliance_flags:   list[str]     # NRB rule violations (empty = clean)
    monthly_income_npr: Optional[float] = None    # Verified monthly income
    income_sources:     list[str]     # Which income signals contributed
    doc_confidence:     Optional[float] = None    # Document scan quality
    pipeline_time_ms:   int           # Total processing time


@router.post(
    "/loan/apply",
    response_model=LoanDecisionResponse,
    summary="Submit a full loan application through the 5-agent pipeline",
    description=(
        "Accepts a loan application with document image and income data. "
        "Runs Document Agent and Income Agent in parallel, then Score → "
        "Compliance → Decision sequentially. Returns a credit decision "
        "with full explainability in under 30 seconds."
    ),
    tags=["Loan Pipeline"],
)
async def apply_for_loan(
    # Form fields — sent as multipart/form-data alongside the image file
    loan_amount_npr: float      = Form(...,  description="Requested loan amount in NPR"),
    sector:          str        = Form(...,  description="Business sector (e.g. agriculture)"),
    use_mock_income: bool       = Form(False,description="Use mock income data (for demo)"),
    # File upload — the citizenship certificate or Lalpurja image
    document:        UploadFile = File(...,  description="Citizenship cert or Lalpurja (JPG/PNG)"),
):
    # ── Step 1: Validate inputs ────────────────────────────────────────────────
    if loan_amount_npr <= 0:
        raise HTTPException(status_code=422, detail="loan_amount_npr must be greater than 0")

    allowed_types = {"image/jpeg", "image/jpg", "image/png"}
    if document.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Document must be JPG or PNG")

    # ── Step 2: Read file bytes ────────────────────────────────────────────────
    image_bytes = await document.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded document file is empty")

    # ── Step 3: Initialise SharedState ────────────────────────────────────────
    # SharedState flows through ALL 5 agents — every agent reads and writes to it.
    state = SharedState(
        applicant_id    = uuid.uuid4(),     # Fresh UUID for this application
        loan_amount_npr = loan_amount_npr,  # Needed by Compliance Agent
        sector          = sector,           # Needed by Compliance Agent (sector exposure check)
    )

    # ── Step 4: Prepare income data ───────────────────────────────────────────
    from utils.income_parsers import (
        generate_mock_esewa_data,
        generate_mock_remittance_data,
        generate_mock_coop_data,
    )
    # In Sprint 3 demo, use_mock_income=True generates realistic income signals.
    # In production: accept esewa_data, remittance_data, coop_data as form fields.
    if use_mock_income:
        esewa_data      = generate_mock_esewa_data()
        remittance_data = generate_mock_remittance_data()
        coop_data       = generate_mock_coop_data()
    else:
        esewa_data = remittance_data = coop_data = None

    # ── Step 5: Run Document + Income agents IN PARALLEL ──────────────────────
    # asyncio.gather() runs both coroutines concurrently on the same event loop.
    # Without parallelism: Document(15s) + Income(1s) = 16s sequential.
    # With parallelism:    max(Document, Income) = 15s — saves ~1-2 seconds.
    # Document and Income are independent — neither needs the other's output.
    pipeline_start = time.perf_counter()

    async def run_document():
        # Wraps document agent with timeout — protects 30-second SLA
        return await asyncio.wait_for(
            doc_agent.run(state, image_bytes),
            timeout=settings.OCR_TIMEOUT_SECONDS   # 45s from config
        )

    async def run_income():
        return await income_agent.run(
            state,
            esewa_data      = esewa_data,
            remittance_data = remittance_data,
            coop_data       = coop_data,
        )

    try:
        # Both agents write to state concurrently.
        # Document writes: document_verified, extracted_fields, doc_confidence
        # Income writes:   monthly_income_npr, income_confidence, income_sources
        # They write to DIFFERENT SharedState fields so there is no race condition.
        await asyncio.gather(run_document(), run_income())
    except asyncio.TimeoutError:
        # Document Agent timed out — set manual review flag and continue pipeline.
        # The Compliance Agent will catch manual_review_required=True.
        state.manual_review_required = True
        state.doc_confidence         = 0.0

    # ── Step 6: Run Score Agent ────────────────────────────────────────────────
    # Score Agent needs income data from step 5 — must run after gather().
    # Imports Score Agent here to avoid circular imports at module level.
    try:
        from agents.score_agent import ScoreAgent
        score_agent = ScoreAgent()
        state = await score_agent.run(state)
    except Exception:
        # Score Agent failure — pipeline continues, Decision Agent handles None score
        state.credit_score = None

    # ── Step 7: Run Compliance Agent ──────────────────────────────────────────
    # Checks NRB rules against the now-populated SharedState.
    state = await compliance_agent.run(state)

    # ── Step 8: Run Decision Agent ────────────────────────────────────────────
    # Reads everything in SharedState and issues the final verdict.
    state = await decision_agent.run(state)

    pipeline_ms = int((time.perf_counter() - pipeline_start) * 1000)

    # ── Step 9: Return structured response ───────────────────────────────────
    return LoanDecisionResponse(
        applicant_id       = state.applicant_id,
        final_decision     = state.final_decision     or "Refer",
        decision_reason    = state.decision_reason    or "Processing incomplete",
        credit_score       = state.credit_score,
        compliance_flags   = state.compliance_flags,
        monthly_income_npr = state.monthly_income_npr,
        income_sources     = state.income_sources     or [],
        doc_confidence     = state.doc_confidence,
        pipeline_time_ms   = pipeline_ms,
    )
"""

# Write all files
files = {
    "agents/compliance_agent.py": compliance_code,
    "agents/decision_agent.py":   decision_code,
    "api/routes/loan.py":         loan_route_code,
}

for path, content in files.items():
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Written: {path}")

# Register loan router in main.py
with open("main.py", encoding="utf-8") as f:
    main = f.read()

if "from api.routes import loan" not in main:
    main = main.replace(
        "from api.routes import documents, income",
        "from api.routes import documents, income, loan"
    )

if "loan.router" not in main:
    main = main.replace(
        "app.include_router(income.router,    prefix=\"/api/v1\")",
        "app.include_router(income.router,    prefix=\"/api/v1\")\n"
        "app.include_router(loan.router,      prefix=\"/api/v1\")"
    )

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main)
print("Updated: main.py")

print()
print("Done. Run:")
print("  uvicorn main:app --reload --port 8000")
print()
print("New endpoint: POST /api/v1/loan/apply")
print("Test in /docs with: document image + loan_amount_npr + sector + use_mock_income=true")