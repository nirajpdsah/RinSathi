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
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
import io
from datetime import timedelta

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])

NPT_OFFSET = timedelta(hours=5, minutes=45)

def to_npt(dt):
    """
    Converts a UTC-aware datetime into Nepal Standard Time for display.
    
    We only ever call this at the moment of PRESENTING a timestamp
    to a human — never when storing or comparing timestamps internally.
    The database and all internal logic continue to use UTC exclusively.
    """
    if dt is None:
        return None
    return dt + NPT_OFFSET

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
    id:                 uuid.UUID
    full_name:          str
    citizenship_no:     Optional[str]
    loan_amount_npr:    float
    sector:             str
    status:             str
    submitted_at:       datetime
    reviewed_at:        Optional[datetime]
    officer_remarks:    Optional[str]

    # AI decision
    credit_score:       Optional[float]  = None
    compliance_flags:   list[str]        = []
    final_decision:     Optional[str]    = None
    decision_reason:    Optional[str]    = None
    pipeline_time_ms:   Optional[int]    = None
    shap_explanation:   Optional[list]   = None

    # Full identity — NEW
    date_of_birth:      Optional[str]    = None
    sex:                Optional[str]    = None
    permanent_address:  Optional[str]    = None
    nin:                Optional[str]    = None

    # Full asset detail — NEW
    total_land_ropani:  Optional[int]    = None
    total_land_aana:    Optional[int]    = None
    land_parcels_count: Optional[int]    = None
    total_land_value_npr: Optional[float] = None

    # Full income detail — NEW
    monthly_income_npr: Optional[float]  = None
    income_confidence:  Optional[float]  = None
    income_sources:     list[str]        = []
    income_breakdown:              Optional[dict]  = None
    total_accumulated_income_npr:  Optional[float] = None   

    is_blacklisted:      Optional[bool] = None
    max_dpd_bucket:      Optional[str]  = None
    cib_records_count:   Optional[int]  = None
    nepal_credit_score:  Optional[int]  = None

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
    id=                 applicant.id,
    full_name=          applicant.full_name,
    citizenship_no=     applicant.citizenship_no,
    loan_amount_npr=    applicant.loan_amount_npr,
    sector=             applicant.sector,
    status=             applicant.status.value,
    submitted_at=       applicant.created_at,
    reviewed_at=        applicant.reviewed_at,
    officer_remarks=    applicant.officer_remarks,
    credit_score=       pipeline_data.get("credit_score"),
    compliance_flags=   pipeline_data.get("compliance_flags", []),
    final_decision=     pipeline_data.get("final_decision"),
    decision_reason=    pipeline_data.get("decision_reason"),
    pipeline_time_ms=   pipeline_data.get("pipeline_time_ms"),
    shap_explanation=   pipeline_data.get("shap_explanation"),
    date_of_birth=      pipeline_data.get("date_of_birth"),
    sex=                pipeline_data.get("sex"),
    permanent_address=  pipeline_data.get("permanent_address"),
    nin=                pipeline_data.get("nin"),
    total_land_ropani=  pipeline_data.get("total_land_ropani"),
    total_land_aana=    pipeline_data.get("total_land_aana"),
    land_parcels_count= pipeline_data.get("land_parcels"),
    total_land_value_npr= pipeline_data.get("total_land_value_npr"),
    monthly_income_npr= pipeline_data.get("monthly_income_npr"),
    income_confidence=  pipeline_data.get("income_confidence"),
    income_sources=     pipeline_data.get("income_sources", []),
    income_breakdown=   pipeline_data.get("income_breakdown"), 
    total_accumulated_income_npr= pipeline_data.get("total_accumulated_income_npr"),  
    is_blacklisted=      pipeline_data.get("is_blacklisted"),        # ← NEW
    max_dpd_bucket=      pipeline_data.get("max_dpd_bucket"),        # ← NEW
    cib_records_count=   pipeline_data.get("cib_records_count"),     # ← NEW
    nepal_credit_score=  pipeline_data.get("nepal_credit_score"),    # ← NEW       
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
@router.get("/applications/{application_id}/pdf")
async def download_application_pdf(
    application_id: uuid.UUID,
    payload: dict    = Depends(require_role("officer")),
    db: AsyncSession = Depends(get_db),
):
    """
    Generates a downloadable PDF of the complete loan application —
    identity, assets, income, AI assessment, and officer decision.

    Think of this as the digital equivalent of a physical loan file
    an officer would staple together and archive. Every verified
    fact from DoNIDCR, NeLIS, and the AI pipeline is laid out in
    one document that can be printed, signed, and filed for audit.
    """
    # ── Fetch the applicant record ────────────────────────────────────────────
    result = await db.execute(
        select(Applicant).where(Applicant.id == application_id)
    )
    applicant = result.scalar_one_or_none()
    if not applicant:
        raise HTTPException(status_code=404, detail="Application not found.")

    # ── Fetch the AI pipeline output from the audit log ───────────────────────
    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.applicant_id == application_id)
        .where(AuditLog.event_type   == "PIPELINE_COMPLETED")
    )
    audit = audit_result.scalar_one_or_none()
    d = audit.details if audit and audit.details else {}

    # ── Build the PDF in memory ────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18*mm, bottomMargin=18*mm,
        leftMargin=18*mm, rightMargin=18*mm,
    )
    styles = getSampleStyleSheet()

    navy   = colors.HexColor("#0F2044")
    gold   = colors.HexColor("#F5A623")
    grey   = colors.HexColor("#6B7280")

    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"],
        textColor=navy, fontSize=20, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"],
        textColor=grey, fontSize=10, spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "SectionStyle", parent=styles["Heading2"],
        textColor=navy, fontSize=13, spaceBefore=16, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyStyle", parent=styles["Normal"], fontSize=10, leading=15,
    )

    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(Paragraph("RinSathi — Loan Application Form", title_style))
    story.append(Paragraph(
        f"Application ID: {applicant.id} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Submitted: {to_npt(applicant.created_at).strftime('%d %b %Y, %H:%M')} NPT",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", color=gold, thickness=2))

    def section_table(rows):
        """Two-column label/value table styled consistently across sections."""
        t = Table(rows, colWidths=[55*mm, 115*mm])
        t.setStyle(TableStyle([
            ("FONTSIZE",     (0,0), (-1,-1), 10),
            ("TEXTCOLOR",    (0,0), (0,-1),  grey),
            ("FONTNAME",     (0,0), (0,-1),  "Helvetica"),
            ("FONTNAME",     (1,0), (1,-1),  "Helvetica-Bold"),
            ("BOTTOMPADDING",(0,0), (-1,-1), 6),
            ("TOPPADDING",   (0,0), (-1,-1), 6),
            ("LINEBELOW",    (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ]))
        return t

    # ── Section A — Identity ────────────────────────────────────────────────
    story.append(Paragraph("A. Applicant Identity (Verified via DoNIDCR)", section_style))
    story.append(section_table([
        ["Full Name",           applicant.full_name or "—"],
        ["NIN",                 d.get("nin") or "—"],
        ["Citizenship No.",     applicant.citizenship_no or "—"],
        ["Date of Birth",       d.get("date_of_birth") or "—"],
        ["Sex",                 d.get("sex") or "—"],
        ["Permanent Address",   d.get("permanent_address") or "—"],
    ]))

    # ── Section B — Assets ──────────────────────────────────────────────────
    story.append(Paragraph("B. Asset Verification (Verified via NeLIS)", section_style))
    story.append(section_table([
        ["Total Land Parcels",  str(d.get("land_parcels", 0))],
        ["Total Land Area",
        f"{d.get('total_land_ropani', 0)} Ropani {d.get('total_land_aana', 0)} Aana"],
        ["Estimated Asset Value",
        f"NPR {d.get('total_land_value_npr'):,.0f}" if d.get("total_land_value_npr") else "Not verified"],
    ]))

    # ── Section C — Loan Details ────────────────────────────────────────────
    story.append(Paragraph("C. Loan Details", section_style))
    story.append(section_table([
        ["Requested Amount",  f"NPR {applicant.loan_amount_npr:,.0f}"],
        ["Business Sector",   applicant.sector.title()],
    ]))

    # ── Section D — Income Assessment ───────────────────────────────────────
    income_rows = [["Source", "Monthly Avg", "3-Month Total"]]
    for src, v in (d.get("income_breakdown") or {}).items():
        income_rows.append([
            src.title(),
            f"NPR {v['monthly_avg']:,.0f}",
            f"NPR {v['accumulated_3mo']:,.0f}",
        ])

    story.append(Paragraph("D. Income Assessment", section_style))
    if len(income_rows) > 1:
        t = Table(income_rows, colWidths=[55*mm, 55*mm, 60*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0F2044")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Total Accumulated Income (3mo):</b> "
        f"NPR {d.get('total_accumulated_income_npr', 0):,.0f}", body_style
    ))

    # ── Section E — AI Credit Assessment ────────────────────────────────────
    story.append(Paragraph("E. AI Credit Assessment", section_style))
    story.append(section_table([
        ["Credit Score",
         f"{d.get('credit_score')*100:.1f}%" if d.get("credit_score") else "N/A"],
        ["AI Recommendation",   d.get("final_decision") or "—"],
    ]))
    story.append(Paragraph(d.get("decision_reason") or "", body_style))

    # ── Section F — Compliance ──────────────────────────────────────────────
    flags = d.get("compliance_flags") or []
    story.append(Paragraph("F. NRB Compliance Check", section_style))
    story.append(Paragraph(
        ", ".join(flags) if flags else "No compliance violations detected.",
        body_style
    ))

    # ── Section G — Officer Decision ────────────────────────────────────────
    story.append(Paragraph("G. Officer Decision", section_style))
    story.append(section_table([
        ["Decision",         applicant.status.value.upper()],
        ["Reviewed At",
         to_npt(applicant.reviewed_at).strftime("%d %b %Y, %H:%M") + " NPT" if applicant.reviewed_at else "Pending"],
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Officer Remarks:</b> {applicant.officer_remarks or 'Not yet reviewed.'}",
        body_style
    ))

    story.append(Spacer(1, 60))
    story.append(HRFlowable(width="40%", color=colors.HexColor("#9CA3AF"), thickness=0.7, hAlign='LEFT', spaceAfter=4))
    story.append(Paragraph("Authorized Signature — Loan Officer", subtitle_style))

    doc.build(story)
    buffer.seek(0)

    filename = f"RinSathi_Application_{str(applicant.id)[:8]}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
