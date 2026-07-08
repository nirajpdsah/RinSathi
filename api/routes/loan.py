# api/routes/loan.py
#
# Full 5-agent pipeline endpoint: POST /api/v1/loan/apply
#
# CHANGES FROM PREVIOUS VERSION:
#   - DocumentAgent replaced with IdentityAgent (NIN-based verification)
#   - File upload removed — NIN input added
#   - Pipeline result now saved to applicants table in Supabase
#   - user_id linked from JWT token (who submitted this application)
#   - applicant_id returned so frontend can poll for status
#
# Agent execution order:
#   Identity + Income run in PARALLEL (asyncio.gather)
#   Score → Compliance → Decision run SEQUENTIALLY

from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio
import time
import uuid
from datetime import datetime, timezone

from agents.shared_state     import SharedState
from agents.identity_agent   import IdentityAgent
from agents.income_agent     import IncomeAgent
from agents.compliance_agent import ComplianceAgent
from agents.decision_agent   import DecisionAgent
from db.session  import get_db
from db.models   import Applicant, LoanStatus, AuditLog
from core.security import verify_token
from config import get_settings

settings = get_settings()
router   = APIRouter()

# Instantiate agents once at module load — not per request
identity_agent   = IdentityAgent()
income_agent     = IncomeAgent()
compliance_agent = ComplianceAgent()
decision_agent   = DecisionAgent()

bearer_scheme = HTTPBearer()


# ── Response schema ────────────────────────────────────────────────────────────
class LoanDecisionResponse(BaseModel):
    applicant_id:       uuid.UUID
    final_decision:     str
    decision_reason:    str
    credit_score:       Optional[float] = None
    compliance_flags:   list[str]
    monthly_income_npr: Optional[float] = None
    income_sources:     list[str]
    doc_confidence:     Optional[float] = None
    verified_name:      Optional[str]   = None
    citizenship_no:     Optional[str]   = None
    land_parcels:       Optional[int]   = None
    total_land_ropani:  Optional[int]   = None
    total_land_aana:    Optional[int]   = None
    pipeline_time_ms:   int


@router.post(
    "/loan/apply",
    response_model=LoanDecisionResponse,
    summary="Submit a loan application through the 5-agent pipeline",
    tags=["Loan Pipeline"],
)
async def apply_for_loan(
    # ── Form fields ────────────────────────────────────────────────────────────
    nin:             str   = Form(..., description="National Identity Number e.g. NID-001"),
    loan_amount_npr: float = Form(..., description="Requested loan amount in NPR"),
    sector:          str   = Form(..., description="Business sector e.g. agriculture"),

    # ── Income fields ──────────────────────────────────────────────────────────
    cashflow_name:          Optional[str]   = Form(None),
    esewa_monthly_npr:      Optional[float] = Form(None),
    remittance_monthly_npr: Optional[float] = Form(None),
    coop_monthly_npr:       Optional[float] = Form(None),
    use_mock_income:        bool            = Form(False),

    # ── FastAPI dependencies ───────────────────────────────────────────────────
    # JWT token — identifies which client submitted this application
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db:          AsyncSession                 = Depends(get_db),
):
    # ── Step 1: Verify JWT and get user_id ────────────────────────────────────
    # We need to know WHO is submitting this application
    # so we can link it to their account in the applicants table
    try:
        payload = verify_token(credentials)
        user_id = uuid.UUID(payload["user_id"])
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session. Please log in again."
        )

    # ── Step 2: Validate inputs ───────────────────────────────────────────────
    if not nin or not nin.strip():
        raise HTTPException(status_code=422, detail="NIN is required.")

    if loan_amount_npr <= 0:
        raise HTTPException(
            status_code=422,
            detail="Loan amount must be greater than zero."
        )
    # ── Step 2b: Check for duplicate pending application ─────────────────────────
    # A client should not have more than one active application at a time.
    # This prevents double-submission from slow networks or impatient clicking.
    #
    # "Active" means pending or referred — not yet decided by an officer.
    # If a previous application was approved or rejected, they can apply again.

    from sqlalchemy import or_

    existing = await db.execute(
        select(Applicant).where(
            Applicant.user_id == user_id,
            or_(
                Applicant.status == LoanStatus.PENDING,
                Applicant.status == LoanStatus.REFERRED,
            )
        )
    )
    duplicate = existing.scalar_one_or_none()

    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                "You already have an active application under review. "
                "Please wait for the officer's decision before submitting a new one. "
                f"Application ID: {duplicate.id}"
            )
        )

    # ── Step 3: Initialise SharedState ────────────────────────────────────────
    # SharedState is the data envelope that flows through all 5 agents.
    # Every agent reads from it and writes back to it.
    state = SharedState(
        applicant_id    = uuid.uuid4(),
        loan_amount_npr = loan_amount_npr,
        sector          = sector.strip().lower(),
        nin             = nin.strip().upper(),
    )

    # ── Step 4: Prepare income data ───────────────────────────────────────────
    from utils.income_parsers import (
        generate_mock_esewa_data,
        generate_mock_remittance_data,
        generate_mock_coop_data,
    )
    from datetime import date

    def recent_months(count: int = 3) -> list[str]:
        today = date.today()
        months = []
        year, month = today.year, today.month
        for _ in range(count):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        return months

    if use_mock_income:
        parsed_esewa_data      = generate_mock_esewa_data("Applicant")
        parsed_remittance_data = generate_mock_remittance_data("Applicant")
        parsed_coop_data       = generate_mock_coop_data("Applicant")
    else:
        name   = (cashflow_name or "Applicant").strip()
        months = recent_months()

        def build_esewa():
            if not esewa_monthly_npr or esewa_monthly_npr <= 0:
                return None
            return {
                "account_name": name,
                "transactions": [
                    {"date": f"{m}-10", "amount": esewa_monthly_npr, "type": "salary"}
                    for m in months
                ],
            }

        def build_remittance():
            if not remittance_monthly_npr or remittance_monthly_npr <= 0:
                return None
            return {
                "records": [
                    {
                        "sender_country": "Unknown",
                        "amount_usd":     round(remittance_monthly_npr / 133.0, 2),
                        "exchange_rate":  133.0,
                        "received_date":  f"{m}-20",
                        "receiver_name":  name,
                    }
                    for m in months
                ],
            }

        def build_coop():
            if not coop_monthly_npr or coop_monthly_npr <= 0:
                return None
            return {
                "member_name":      name,
                "savings_balance_npr": 0.0,
                "monthly_deposits": [
                    {"month": m, "amount": coop_monthly_npr}
                    for m in months
                ],
            }

        parsed_esewa_data      = build_esewa()
        parsed_remittance_data = build_remittance()
        parsed_coop_data       = build_coop()

        def build_income_breakdown(esewa, remittance, coop) -> dict:
            """
            Computes per-source monthly average and 3-month accumulated total
            from the raw payloads already built for the Income Agent.
            This does NOT change how the Income Agent calculates the blended
            monthly_income_npr used for scoring — it only adds transparency
            on top, for display to officer and client.
            """
            breakdown = {}

            if esewa:
                amounts = [t["amount"] for t in esewa["transactions"]]
                breakdown["esewa"] = {
                    "monthly_avg":     round(sum(amounts) / len(amounts), 2),
                    "accumulated_3mo": round(sum(amounts), 2),
                }

            if remittance:
                amounts = [r["amount_usd"] * r["exchange_rate"] for r in remittance["records"]]
                breakdown["remittance"] = {
                    "monthly_avg":     round(sum(amounts) / len(amounts), 2),
                    "accumulated_3mo": round(sum(amounts), 2),
                }

            if coop:
                amounts = [d["amount"] for d in coop["monthly_deposits"]]
                breakdown["cooperative"] = {
                    "monthly_avg":     round(sum(amounts) / len(amounts), 2) if amounts else 0,
                    "accumulated_3mo": round(sum(amounts), 2),
                }

            return breakdown

        # Call it right after building the payloads:
        state.income_breakdown = build_income_breakdown(
            parsed_esewa_data, parsed_remittance_data, parsed_coop_data
        )
        state.total_accumulated_income_npr = round(
            sum(v["accumulated_3mo"] for v in state.income_breakdown.values()), 2
        )

        if not any([parsed_esewa_data, parsed_remittance_data, parsed_coop_data]):
            raise HTTPException(
                status_code=422,
                detail="Provide at least one income source or enable mock income."
            )
        
    state.income_breakdown = build_income_breakdown(
    parsed_esewa_data, parsed_remittance_data, parsed_coop_data
    )
    state.total_accumulated_income_npr = round(
    sum(v["accumulated_3mo"] for v in state.income_breakdown.values()), 2
    )

    # ── Step 5: Run Identity + Income agents IN PARALLEL ─────────────────────
    # Identity Agent: verifies NIN against DoNIDCR, fetches land from NeLIS
    # Income Agent:   parses eSewa, remittance, cooperative data
    # They write to DIFFERENT SharedState fields — no race condition possible
    pipeline_start = time.perf_counter()

    async def run_identity():
        return await identity_agent.run(state)

    async def run_income():
        return await income_agent.run(
            state,
            esewa_data      = parsed_esewa_data,
            remittance_data = parsed_remittance_data,
            coop_data       = parsed_coop_data,
        )

    await asyncio.gather(run_identity(), run_income())

    # ── Step 6: Score Agent ───────────────────────────────────────────────────
    # ── Step 6: Run Score Agent ───────────────────────────────────────────────
    try:
        from agents.score_agent import ScoreAgent
        score_agent = ScoreAgent()
        state = await score_agent.run(state)
    except Exception as e:
        print(f"ScoreAgent Bridge Critical Error: {str(e)}")
        state.credit_score = 0.5   # Neutral fallback — routes toward Refer, not auto-approve
    # ── Step 7: Compliance Agent ──────────────────────────────────────────────
    state = await compliance_agent.run(state)

    # ── Step 8: Decision Agent ────────────────────────────────────────────────
    state = await decision_agent.run(state)

    pipeline_ms = int((time.perf_counter() - pipeline_start) * 1000)

    # ── Step 9: Save result to database ───────────────────────────────────────
    # This is new — previously results were returned but never persisted.
    # Now we save to Supabase so the officer dashboard can query them.
    try:
        # Map Decision Agent output to LoanStatus enum
        status_map = {
            "Recommend": LoanStatus.PENDING,   # AI recommends → officer still decides
            "Reject":    LoanStatus.PENDING,  # AI rejects → goes to officer for confirmation
            "Refer":     LoanStatus.REFERRED,  # Borderline → officer must review manually
        }
        db_status = status_map.get( 
            state.final_decision,
            LoanStatus.REFERRED   # Default to Refer if something unexpected
        )

        # Create the applicant record
        applicant = Applicant(
            id              = state.applicant_id,
            full_name       = state.verified_full_name or "Unknown",
            citizenship_no  = state.citizenship_no,
            district        = None,   # Could extract from address in future
            phone           = None,   # Not collected in this version
            loan_amount_npr = state.loan_amount_npr,
            sector          = state.sector,
            status          = db_status,
            user_id         = user_id,   # Links to the logged-in client
        )

        db.add(applicant)

        # Write to audit log — NRB requires every pipeline run to be logged
        audit = AuditLog(
        applicant_id = state.applicant_id,
        event_type   = "PIPELINE_COMPLETED",
        agent_name   = "pipeline",
        details      = {
            # Decision summary
            "final_decision":     state.final_decision,
            "decision_reason":    state.decision_reason,
            "credit_score":       state.credit_score,
            "compliance_flags":   state.compliance_flags,
            "pipeline_time_ms":   pipeline_ms,

            # Full identity record (from DoNIDCR)
            "nin":                nin.strip().upper(),
            "verified_full_name": state.verified_full_name,
            "date_of_birth":      state.date_of_birth,
            "sex":                state.sex,
            "permanent_address":  state.permanent_address,
            "citizenship_no":     state.citizenship_no,

            # Full asset record (from NeLIS)
            "land_parcels":       state.total_land_parcels,
            "total_land_ropani":  state.total_land_ropani,
            "total_land_aana":    state.total_land_aana,

            # Income breakdown
            "monthly_income_npr": state.monthly_income_npr,
            "income_confidence":  state.income_confidence,
            "income_sources":     state.income_sources,
            "income_breakdown":              state.income_breakdown,
            "total_accumulated_income_npr":  state.total_accumulated_income_npr,
            "total_land_value_npr":         state.total_land_value_npr,
            "income_breakdown":             state.income_breakdown,
            "total_accumulated_income_npr": state.total_accumulated_income_npr,

            # AI explainability
            "shap_explanation":   state.shap_explanation,
        },
        performed_by = str(user_id),
    )
        db.add(audit)

        await db.commit()

    except Exception as e:
        # Database save failed — log it but still return the decision
        # The applicant should not be penalised for a DB error
        print(f"Database save error: {e}")
        await db.rollback()

    # ── Step 10: Return response ───────────────────────────────────────────────
    return LoanDecisionResponse(
        applicant_id       = state.applicant_id,
        final_decision     = state.final_decision  or "Refer",
        decision_reason    = state.decision_reason or "Processing incomplete",
        credit_score       = state.credit_score,
        compliance_flags   = state.compliance_flags,
        monthly_income_npr = state.monthly_income_npr,
        income_sources     = state.income_sources or [],
        doc_confidence     = state.doc_confidence,
        verified_name      = state.verified_full_name,
        citizenship_no     = state.citizenship_no,
        land_parcels       = state.total_land_parcels,
        total_land_ropani  = state.total_land_ropani,
        total_land_aana    = state.total_land_aana,
        pipeline_time_ms   = pipeline_ms,
    )