# routers/client.py
#
# Client-facing API endpoints.
# All routes here require role: "client" in the JWT.
#
# ENDPOINTS:
#   GET /client/applications        → client's own applications
#   GET /client/applications/{id}   → single application detail

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

from db.session    import get_db
from db.models     import Applicant, AuditLog
from core.security import require_role

router = APIRouter(prefix="/client", tags=["Client Dashboard"])


class ClientApplicationSummary(BaseModel):
    """One row on the client's application history dashboard."""
    id:              uuid.UUID
    loan_amount_npr: float
    sector:          str
    status:          str
    submitted_at:    datetime
    reviewed_at:     Optional[datetime] = None
    officer_remarks: Optional[str]      = None

    class Config:
        from_attributes = True


class ClientApplicationDetail(BaseModel):
    """Full detail of one application — shown on status page."""
    id:              uuid.UUID
    full_name:       str
    loan_amount_npr: float
    sector:          str
    status:          str
    submitted_at:    datetime
    reviewed_at:     Optional[datetime] = None
    officer_remarks: Optional[str]      = None
    credit_score:    Optional[float]    = None
    final_decision:  Optional[str]      = None
    decision_reason: Optional[str]      = None
    compliance_flags: list[str]         = []

    class Config:
        from_attributes = True


@router.get("/applications", response_model=list[ClientApplicationSummary])
async def get_my_applications(
    payload: dict    = Depends(require_role("client")),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all applications submitted by the logged-in client.

    Client can only see their OWN applications — never others'.
    This is enforced by filtering on user_id from the JWT.
    """
    user_id = uuid.UUID(payload["user_id"])

    result = await db.execute(
        select(Applicant)
        .where(Applicant.user_id == user_id)
        .order_by(Applicant.created_at.desc())
    )
    applicants = result.scalars().all()

    return [
        ClientApplicationSummary(
            id=              a.id,
            loan_amount_npr= a.loan_amount_npr,
            sector=          a.sector,
            status=          a.status.value,
            submitted_at=    a.created_at,
            reviewed_at=     a.reviewed_at,
            officer_remarks= a.officer_remarks,
        )
        for a in applicants
    ]


@router.get("/applications/{application_id}",
            response_model=ClientApplicationDetail)
async def get_my_application_detail(
    application_id: uuid.UUID,
    payload: dict    = Depends(require_role("client")),
    db: AsyncSession = Depends(get_db),
):
    """
    Full detail of one application — client's status page.

    Security: verifies the application belongs to THIS client.
    A client cannot view another client's application by guessing IDs.
    """
    user_id = uuid.UUID(payload["user_id"])

    result = await db.execute(
        select(Applicant)
        .where(Applicant.id      == application_id)
        .where(Applicant.user_id == user_id)   # ← ownership check
    )
    applicant = result.scalar_one_or_none()

    if not applicant:
        raise HTTPException(
            status_code=404,
            detail="Application not found."
        )

    # Pull AI output from audit log
    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.applicant_id == application_id)
        .where(AuditLog.event_type   == "PIPELINE_COMPLETED")
    )
    audit = audit_result.scalar_one_or_none()
    pipeline_data = audit.details if audit and audit.details else {}

    return ClientApplicationDetail(
        id=               applicant.id,
        full_name=        applicant.full_name,
        loan_amount_npr=  applicant.loan_amount_npr,
        sector=           applicant.sector,
        status=           applicant.status.value,
        submitted_at=     applicant.created_at,
        reviewed_at=      applicant.reviewed_at,
        officer_remarks=  applicant.officer_remarks,
        credit_score=     pipeline_data.get("credit_score"),
        final_decision=   pipeline_data.get("final_decision"),
        decision_reason=  pipeline_data.get("decision_reason"),
        compliance_flags= pipeline_data.get("compliance_flags", []),
    )