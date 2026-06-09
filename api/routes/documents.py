# ── api/routes/documents.py ───────────────────────────────────────────────────
# FastAPI route for the Document Agent endpoint.
# Accepts an image file upload, runs the Document Agent pipeline,
# returns structured JSON with extracted fields and confidence scores.

from fastapi import APIRouter, UploadFile, File, HTTPException
# APIRouter: groups related routes together (all document routes in one file)
# UploadFile: FastAPI's type for file uploads — handles multipart/form-data
# File: dependency that tells FastAPI to expect a file in the request body
# HTTPException: raises HTTP errors with proper status codes

import time          # For measuring processing time (part of the SLA tracking)
import uuid          # For generating a unique applicant_id per upload
from agents.shared_state    import SharedState       # Our data contract
from agents.document_agent  import DocumentAgent     # The OCR pipeline agent
from api.schemas            import DocumentUploadResponse, FieldResult

router = APIRouter()              # Create a router — registered in main.py
agent  = DocumentAgent()          # Instantiate agent once (not per-request)


@router.post(
    "/document/upload",                               # URL: POST /api/v1/document/upload
    response_model=DocumentUploadResponse,            # FastAPI validates response against this
    summary="Upload and analyse a government document",
    description=(
        "Accepts a citizenship certificate or Lalpurja image. "
        "Runs PaddleOCR with OpenCV preprocessing to extract structured fields. "
        "Returns extracted fields with per-field confidence scores."
    ),
    tags=["Document Agent"],
)
async def upload_document(
    file: UploadFile = File(..., description="Citizenship cert or Lalpurja (JPG/PNG)")
    # File(...) means this parameter is required — no default value
):
    # ── Step 1: Validate file type ────────────────────────────────────────────
    allowed_types = {"image/jpeg", "image/jpg", "image/png"}
    if file.content_type not in allowed_types:
        # Return HTTP 400 Bad Request with a clear error message
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Upload JPG or PNG only."
        )

    # ── Step 2: Read file bytes ───────────────────────────────────────────────
    image_bytes = await file.read()  # await because file.read() is async in FastAPI

    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(image_bytes) > 10 * 1024 * 1024:   # 10MB limit
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    # ── Step 3: Initialise SharedState ───────────────────────────────────────
    # Create a new SharedState for this request with a fresh UUID
    state = SharedState(
        applicant_id    = uuid.uuid4(),  # New unique ID for this application
        loan_amount_npr = 0.0,           # Not known yet — filled in later steps
        sector          = "unknown"      # Not known yet — filled in later steps
    )

    # ── Step 4: Run Document Agent ────────────────────────────────────────────
    start_ms = time.perf_counter()              # Start timing
    state    = await agent.run(state, image_bytes)  # Run the OCR pipeline
    elapsed_ms = int((time.perf_counter() - start_ms) * 1000)  # Convert to milliseconds

    # ── Step 5: Determine OCR mode (real or mock) ─────────────────────────────
    from utils.ocr import OCR_AVAILABLE
    ocr_mode = "paddleocr" if OCR_AVAILABLE else "mock"

    # ── Step 6: Build and return the response ─────────────────────────────────
    # Convert extracted_fields dict to FieldResult objects for Pydantic validation
    formatted_fields = {}
    if state.extracted_fields:
        for field_name, field_data in state.extracted_fields.items():
            formatted_fields[field_name] = FieldResult(
                value=field_data.get("value", ""),
                confidence=field_data.get("confidence", 0.0)
            )

    return DocumentUploadResponse(
        applicant_id           = state.applicant_id,
        document_verified      = state.document_verified or False,
        extracted_fields       = formatted_fields,
        doc_confidence         = state.doc_confidence or 0.0,
        manual_review_required = state.manual_review_required,
        processing_time_ms     = elapsed_ms,
        ocr_mode               = ocr_mode
    )