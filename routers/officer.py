# routers/officer.py
#
# Officer-facing API endpoints.
# All routes here require role: "officer" in the JWT.
# Clients cannot access these endpoints — require_role enforces this.
#
# ENDPOINTS:
#   GET  /officer/applications           → pending queue
#   GET  /officer/applications/{id}      → single application detail
#   POST /officer/applications/{id}/decision → approve or reject

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import uuid

from db.session  import get_db
from db.models   import Applicant, LoanStatus, AuditLog, User
from core.security import require_role

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class ApplicationSummary(BaseModel):
    """One row in the officer's pending queue."""
    id:              uuid.UUID
    full_name:       str
    loan_amount_npr: float
    sector:          str
    status:          str
    submitted_at:    datetime
    citizenship_no:  Optional[str] = None

    class Config:
        from_attributes = True


class ApplicationDetail(BaseModel):
    """Full application detail for the review page."""
    id:              uuid.UUID
    full_name:       str
    citizenship_no:  Optional[str]
    loan_amount_npr: float
    sector:          str
    status:          str
    submitted_at:    datetime
    reviewed_at:     Optional[datetime]
    officer_remarks: Optional[str]
    # AI pipeline outputs from audit log
    credit_score:    Optional[float] = None
    compliance_flags: list[str]      = []
    final_decision:  Optional[str]   = None
    decision_reason: Optional[str]   = None
    pipeline_time_ms: Optional[int]  = None

    class Config:
        from_attributes = True


class DecisionRequest(BaseModel):
    """What the officer submits when approving or rejecting."""
    decision: str        # "approved" or "rejected"
    remarks:  str        # Officer must write a reason — NRB requirement


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/applications", response_model=list[ApplicationSummary])
async def get_applications(
    status_filter: Optional[str] = None,
    payload: dict  = Depends(require_role("officer")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all loan applications for the officer queue.

    Query param: ?status_filter=pending  (optional)
    Default: returns all applications, newest first.

    The officer dashboard calls this on every page load
    to show the current queue of applications to review.
    """
    query = select(Applicant).order_by(Applicant.created_at.desc())

    # Optional filter by status
    if status_filter:
        try:
            status_enum = LoanStatus(status_filter.lower())
            query = query.where(Applicant.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status filter. Use: pending, approved, rejected, referred"
            )

    result = await db.execute(query)
    applicants = result.scalars().all()

    return [
        ApplicationSummary(
            id=              a.id,
            full_name=       a.full_name,
            loan_amount_npr= a.loan_amount_npr,
            sector=          a.sector,
            status=          a.status.value,
            submitted_at=    a.created_at,
            citizenship_no=  a.citizenship_no,
        )
        for a in applicants
    ]


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def get_application_detail(
    application_id: uuid.UUID,
    payload: dict    = Depends(require_role("officer")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns full detail of one application for the review page.

    Includes the AI pipeline output pulled from audit_logs:
    credit score, compliance flags, SHAP explanation, decision reason.

    The officer reads all of this before making their decision.
    """
    result = await db.execute(
        select(Applicant).where(Applicant.id == application_id)
    )
    applicant = result.scalar_one_or_none()

    if not applicant:
        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    # Pull AI pipeline output from the audit log
    # We stored it there in loan.py Step 9
    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.applicant_id == application_id)
        .where(AuditLog.event_type   == "PIPELINE_COMPLETED")
        .order_by(AuditLog.created_at.desc())
    )
    audit = audit_result.scalar_one_or_none()

    pipeline_data = audit.details if audit and audit.details else {}

    return ApplicationDetail(
        id=               applicant.id,
        full_name=        applicant.full_name,
        citizenship_no=   applicant.citizenship_no,
        loan_amount_npr=  applicant.loan_amount_npr,
        sector=           applicant.sector,
        status=           applicant.status.value,
        submitted_at=     applicant.created_at,
        reviewed_at=      applicant.reviewed_at,
        officer_remarks=  applicant.officer_remarks,
        credit_score=     pipeline_data.get("credit_score"),
        compliance_flags= pipeline_data.get("compliance_flags", []),
        final_decision=   pipeline_data.get("final_decision"),
        decision_reason=  pipeline_data.get("decision_reason"),
        pipeline_time_ms= pipeline_data.get("pipeline_time_ms"),
    )


@router.post("/applications/{application_id}/decision")
async def submit_decision(
    application_id: uuid.UUID,
    request:  DecisionRequest,
    payload:  dict         = Depends(require_role("officer")),
    db:       AsyncSession = Depends(get_db),
):
    """
    Officer submits their final decision — approved or rejected.

    What happens:
      1. Application status updated in applicants table
      2. reviewed_by set to this officer's user_id
      3. officer_remarks saved
      4. reviewed_at timestamp set
      5. Audit log entry written

    The client dashboard polls their application status —
    they will see this update on their next page load.
    """
    # Validate decision value
    if request.decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=422,
            detail="Decision must be 'approved' or 'rejected'."
        )

    # Require remarks — NRB mandates written justification
    if not request.remarks or not request.remarks.strip():
        raise HTTPException(
            status_code=422,
            detail="Officer remarks are required. All decisions must be justified."
        )

    # Fetch the application
    result = await db.execute(
        select(Applicant).where(Applicant.id == application_id)
    )
    applicant = result.scalar_one_or_none()

    if not applicant:
        raise HTTPException(status_code=404, detail="Application not found.")

    # Prevent re-reviewing an already decided application
    if applicant.status in (LoanStatus.APPROVED, LoanStatus.REJECTED):
        raise HTTPException(
            status_code=409,
            detail="This application has already been reviewed."
        )

    officer_id = uuid.UUID(payload["user_id"])

    # Update the application
    applicant.status          = (
        LoanStatus.APPROVED if request.decision == "approved"
        else LoanStatus.REJECTED
    )
    applicant.reviewed_by     = officer_id
    applicant.officer_remarks = request.remarks.strip()
    applicant.reviewed_at     = datetime.now(timezone.utc)

    # Write audit log — every decision must be traceable
    audit = AuditLog(
        applicant_id = application_id,
        event_type   = f"OFFICER_{request.decision.upper()}",
        agent_name   = "officer",
        details      = {
            "decision":       request.decision,
            "remarks":        request.remarks.strip(),
            "officer_id":     str(officer_id),
        },
        performed_by = str(officer_id),
    )
    db.add(audit)

    await db.commit()

    return {
        "message":        f"Application {request.decision} successfully.",
        "application_id": str(application_id),
        "decision":       request.decision,
        "reviewed_at":    applicant.reviewed_at.isoformat(),
    }