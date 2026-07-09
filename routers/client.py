# routers/client.py
#
# Client-facing API endpoints.
# All routes here require role: "client" in the JWT.
#
# ENDPOINTS:
#   GET /client/applications        → client's own applications
#   GET /client/applications/{id}   → single application detail

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable
)
import io
import uuid

from db.session    import get_db
from db.models     import Applicant, AuditLog
from core.security import require_role

router = APIRouter(prefix="/client", tags=["Client Dashboard"])


def to_npt(dt):
    if not dt:
        return None
    return dt


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
)


@router.get("/applications/{application_id}/pdf")
async def download_my_application_pdf(
    application_id: uuid.UUID,
    payload: dict = Depends(require_role("client")),
    db: AsyncSession = Depends(get_db),
):
    """Generate the same application PDF for the owning client."""
    user_id = uuid.UUID(payload["user_id"])

    result = await db.execute(
        select(Applicant)
        .where(Applicant.id == application_id)
        .where(Applicant.user_id == user_id)
    )
    applicant = result.scalar_one_or_none()

    if not applicant:
        raise HTTPException(status_code=404, detail="Application not found.")

    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.applicant_id == application_id)
        .where(AuditLog.event_type == "PIPELINE_COMPLETED")
    )
    audit = audit_result.scalar_one_or_none()
    d = audit.details if audit and audit.details else {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=18 * mm,
        leftMargin=18 * mm, rightMargin=18 * mm,
    )
    styles = getSampleStyleSheet()

    navy = colors.HexColor("#0F2044")
    gold = colors.HexColor("#F5A623")
    grey = colors.HexColor("#6B7280")

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

    story.append(Paragraph("RinSathi — Loan Application Form", title_style))
    story.append(Paragraph(
        f"Application ID: {applicant.id} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"Submitted: {to_npt(applicant.created_at).strftime('%d %b %Y, %H:%M')} NPT",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", color=gold, thickness=2))

    def section_table(rows):
        table = Table(rows, colWidths=[55 * mm, 115 * mm])
        table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), grey),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ]))
        return table

    story.append(Paragraph("A. Applicant Identity (Verified via DoNIDCR)", section_style))
    story.append(section_table([
        ["Full Name", applicant.full_name or "—"],
        ["NIN", d.get("nin") or "—"],
        ["Citizenship No.", applicant.citizenship_no or "—"],
        ["Date of Birth", d.get("date_of_birth") or "—"],
        ["Sex", d.get("sex") or "—"],
        ["Permanent Address", d.get("permanent_address") or "—"],
    ]))

    story.append(Paragraph("B. Asset Verification (Verified via NeLIS)", section_style))
    story.append(section_table([
        ["Total Land Parcels", str(d.get("land_parcels", 0))],
        ["Total Land Area", f"{d.get('total_land_ropani', 0)} Ropani {d.get('total_land_aana', 0)} Aana"],
        ["Estimated Asset Value", f"NPR {d.get('total_land_value_npr'):,.0f}" if d.get("total_land_value_npr") else "Not verified"],
    ]))

    story.append(Paragraph("C. Loan Details", section_style))
    story.append(section_table([
        ["Requested Amount", f"NPR {applicant.loan_amount_npr:,.0f}"],
        ["Business Sector", applicant.sector.title()],
    ]))

    income_rows = [["Source", "Monthly Avg", "3-Month Total"]]
    for src, value in (d.get("income_breakdown") or {}).items():
        income_rows.append([
            src.title(),
            f"NPR {value['monthly_avg']:,.0f}",
            f"NPR {value['accumulated_3mo']:,.0f}",
        ])

    story.append(Paragraph("D. Income Assessment", section_style))
    if len(income_rows) > 1:
        income_table = Table(income_rows, colWidths=[55 * mm, 55 * mm, 60 * mm])
        income_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2044")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(income_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Total Accumulated Income (3mo):</b> NPR {d.get('total_accumulated_income_npr', 0):,.0f}",
        body_style
    ))

    story.append(Paragraph("E. AI Credit Assessment", section_style))
    story.append(section_table([
        ["Credit Score", f"{d.get('credit_score')*100:.1f}%" if d.get("credit_score") else "N/A"],
        ["AI Recommendation", d.get("final_decision") or "—"],
    ]))
    story.append(Paragraph(d.get("decision_reason") or "", body_style))

    flags = d.get("compliance_flags") or []
    story.append(Paragraph("F. NRB Compliance Check", section_style))
    story.append(Paragraph(
        ", ".join(flags) if flags else "No compliance violations detected.",
        body_style
    ))

    story.append(Paragraph("G. Officer Decision", section_style))
    story.append(section_table([
        ["Decision", applicant.status.value.upper()],
        ["Reviewed At", to_npt(applicant.reviewed_at).strftime("%d %b %Y, %H:%M") + " NPT" if applicant.reviewed_at else "Pending"],
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Officer Remarks:</b> {applicant.officer_remarks or 'Not yet reviewed.'}",
        body_style
    ))

    story.append(Spacer(1, 40))
    story.append(HRFlowable(width="40%", color=colors.HexColor("#9CA3AF"), thickness=0.7))
    story.append(Paragraph("Authorized Signature — Loan Officer", subtitle_style))

    doc.build(story)
    buffer.seek(0)

    filename = f"RinSathi_Application_{str(applicant.id)[:8]}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )