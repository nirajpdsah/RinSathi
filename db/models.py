# db/models.py
#
# SQLAlchemy ORM models — each class maps to one table in Supabase.
#
# MODELS IN THIS FILE:
#   Role        → roles table (client, officer)
#   User        → users table (everyone who can log in)
#   Applicant   → applicants table (loan applications)
#   Document    → documents table (uploaded files + OCR results)
#   AuditLog    → audit_logs table (every system action, for NRB compliance)
#
# RELATIONSHIPS:
#   User belongs to one Role
#   Applicant belongs to one User (the client who submitted it)
#   Applicant is reviewed by one User (the officer)
#   Document belongs to one Applicant
#   AuditLog belongs to one Applicant

from sqlalchemy import (
    Column, String, Float, Boolean,
    DateTime, Text, ForeignKey,
    Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

import uuid
import enum
from datetime import datetime, timezone
from db.session import Base


# ── Enums: fixed-choice values ────────────────────────────────────────────────

class LoanStatus(str, enum.Enum):
    PENDING  = "pending"   # Submitted, pipeline not yet run
    APPROVED = "approved"  # Officer approved
    REJECTED = "rejected"  # Officer rejected
    REFERRED = "referred"  # AI flagged for manual review


class DocumentType(str, enum.Enum):
    CITIZENSHIP = "citizenship"  # Nepal citizenship certificate
    LALPURJA    = "lalpurja"     # Land ownership document
    PAN         = "pan"          # PAN card


# ── Table 1: roles ────────────────────────────────────────────────────────────
class Role(Base):
    """
    Stores the two roles in the system: 'client' and 'officer'.
    
    We keep roles in a separate table instead of hardcoding "client"/"officer"
    strings everywhere. This means if we ever add a new role (e.g. "admin"),
    we add one row here — no code changes needed anywhere else.
    """
    __tablename__ = "roles"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String(50), unique=True, nullable=False)  # "client" or "officer"
    description = Column(Text, nullable=True)

    # One role can belong to many users
    # backref creates a shortcut: user.role → the Role object
    users = relationship("User", back_populates="role")


# ── Table 2: users ────────────────────────────────────────────────────────────
class User(Base):
    """
    Every person who can log into RinSathi has one row here.
    
    Clients:  google_id is filled, password_hash is NULL
    Officers: password_hash is filled, google_id is NULL
    
    We use one table for both because the JWT system only needs
    to ask one question: "Is this person in our system and what's their role?"
    One table = one query. Simple and fast.
    """
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email         = Column(String(255), nullable=False, unique=True, index=True)
    full_name     = Column(String(255), nullable=False)

    # Foreign key to roles table
    # ON DELETE RESTRICT means: you cannot delete a role that has users attached
    # This prevents accidentally breaking user accounts
    role_id       = Column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False
    )

    # Google's unique ID for this person — only for clients
    # index=True because we look this up on every Google login
    google_id     = Column(String(255), unique=True, index=True, nullable=True)

    # Bcrypt-hashed password — only for officers
    # We NEVER store plain text passwords
    password_hash = Column(Text, nullable=True)

    # Soft disable — when an officer leaves, set this to False
    # We never delete users because that would break the audit trail
    is_active     = Column(Boolean, nullable=False, default=True)

    created_at    = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    role = relationship("Role", back_populates="users")

    # All loan applications this user submitted (as a client)
    applications = relationship(
        "Applicant",
        foreign_keys="Applicant.user_id",
        back_populates="client"
    )

    # All applications this user reviewed (as an officer)
    reviewed_applications = relationship(
        "Applicant",
        foreign_keys="Applicant.reviewed_by",
        back_populates="reviewing_officer"
    )


# ── Table 3: applicants ───────────────────────────────────────────────────────
class Applicant(Base):
    """
    One row per loan application.
    
    This is the central table — everything connects to it.
    The client submits it. The AI pipeline fills the score fields.
    The officer updates the status and adds remarks.
    """
    __tablename__ = "applicants"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name       = Column(String(255), nullable=False)
    citizenship_no  = Column(String(50),  nullable=True)
    district        = Column(String(100), nullable=True)
    phone           = Column(String(20),  nullable=True)
    loan_amount_npr = Column(Float,       nullable=False)
    sector          = Column(String(100), nullable=False)

    status = Column(
        SQLEnum(LoanStatus),
        default=LoanStatus.PENDING,
        nullable=False
    )

    # ── NEW: Link to the user who submitted this application ──────────────────
    # When a client submits a loan, we store their user ID here.
    # This is how the client dashboard knows which applications belong to them.
    # SET NULL means: if a user account is deleted, the application stays
    # (we keep financial records even if the account is gone)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True   # Index for fast "show me all applications by user X" queries
    )

    # ── NEW: Link to the officer who reviewed this application ────────────────
    # Filled when an officer clicks Approve or Reject
    # NULL means "not yet reviewed"
    reviewed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # ── NEW: Officer's written remarks ────────────────────────────────────────
    # The officer types a reason when approving or rejecting
    # Required for NRB compliance — decisions must be justified in writing
    officer_remarks = Column(Text, nullable=True)

    # ── NEW: When the officer made their decision ─────────────────────────────
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    client = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="applications"
    )
    reviewing_officer = relationship(
        "User",
        foreign_keys=[reviewed_by],
        back_populates="reviewed_applications"
    )
    documents = relationship("Document", back_populates="applicant")
    audit_logs = relationship("AuditLog", back_populates="applicant")


# ── Table 4: documents ────────────────────────────────────────────────────────
class Document(Base):
    """
    One row per uploaded document.
    One applicant can have multiple documents (citizenship + lalpurja + PAN).
    Identity verification writes extracted_fields and doc_confidence.
    """
    __tablename__ = "documents"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_id   = Column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id"),
        nullable=False
    )
    document_type  = Column(SQLEnum(DocumentType), nullable=False)

    # OCR output stored as JSON
    # Example: {"name": {"value": "Ram Thapa", "confidence": 0.91}}
    extracted_fields       = Column(JSONB,    nullable=True)
    doc_confidence         = Column(Float,    nullable=True)
    manual_review_required = Column(Boolean,  default=False)
    ocr_raw_text           = Column(Text,     nullable=True)
    created_at             = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    applicant = relationship("Applicant", back_populates="documents")


# ── Table 5: audit_logs ───────────────────────────────────────────────────────
class AuditLog(Base):
    """
    Every system action is recorded here.
    
    NRB requires full audit traceability for lending decisions.
    This means: who did what, when, and to which application.
    
    We never delete audit logs. Ever.
    """
    __tablename__ = "audit_logs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    applicant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applicants.id"),
        nullable=True  # Some events are system-level, not applicant-specific
    )
    event_type   = Column(String(100), nullable=False)  # e.g. "OFFICER_APPROVED"
    agent_name   = Column(String(100), nullable=True)   # Which agent or user triggered this
    details      = Column(JSONB,       nullable=True)   # Extra context as flexible JSON
    performed_by = Column(String(255), nullable=True)   # user UUID or "system"
    created_at   = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    applicant = relationship("Applicant", back_populates="audit_logs")