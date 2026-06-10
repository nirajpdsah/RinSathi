# agents/document_agent.py
# Document Agent: first agent in the ACLO five-agent pipeline.
# Receives an uploaded image, runs OCR, validates fields, writes to SharedState.
# Design rule: NEVER raises exceptions. Always returns SharedState.
# On any failure, it degrades gracefully and flags for manual review.

from agents.shared_state import SharedState
from utils.ocr import run_ocr, extract_fields, OCR_AVAILABLE
from config import get_settings

settings = get_settings()


class DocumentAgent:
    """
    Processes uploaded government documents through the OCR pipeline.

    Reads:  image_bytes (passed directly as parameter)
    Writes: document_verified, extracted_fields, doc_confidence,
            manual_review_required  (all into SharedState)

    Defence note: This agent does NOT verify document authenticity.
    It extracts structured data from the document image. Trust is
    established through multi-signal corroboration across all 5 agents —
    not by OCR alone.
    """

    async def run(self, state: SharedState, image_bytes: bytes) -> SharedState:
        # Main entry point. Returns state whether success or failure.
        try:
            # ── Step 1: Run OCR pipeline ──────────────────────────────────────
            # run_ocr handles: preprocessing, thread pool execution, timeout
            ocr_result = await run_ocr(image_bytes)

            # Track whether we used real OCR or mock
            state_note = "mock" if ocr_result.get("_is_mock") else "paddleocr"

            # ── Step 2: Handle OCR failure cases ─────────────────────────────
            if ocr_result.get("timed_out"):
                state.document_verified      = False
                state.doc_confidence         = 0.0
                state.manual_review_required = True
                # Compliance Agent will see manual_review_required=True
                # and add KYC_INCOMPLETE flag, routing to human reviewer
                return state

            if ocr_result.get("error"):
                state.document_verified      = False
                state.doc_confidence         = 0.0
                state.manual_review_required = True
                return state

            # ── Step 3: Check if OCR returned any text at all ────────────────
            if not ocr_result.get("raw_text", "").strip():
                # Blank result — image may be too dark, blurry, or non-document
                state.document_verified      = False
                state.doc_confidence         = 0.2   # Very low confidence
                state.manual_review_required = True
                return state

            # ── Step 4: Extract structured fields from OCR output ─────────────
            fields = extract_fields(ocr_result)

            # ── Step 5: Calculate mean confidence across extracted fields ──────
            # Only count fields we actually found (non-zero confidence)
            conf_values = [
                f["confidence"] for f in fields.values()
                if f.get("confidence", 0) > 0
            ]
            if conf_values:
                mean_confidence = round(sum(conf_values) / len(conf_values), 4)
            else:
                # OCR ran but found no recognisable fields — low quality scan
                mean_confidence = 0.2

            # ── Step 6: Write results to SharedState ─────────────────────────
            state.extracted_fields = fields
            state.doc_confidence   = mean_confidence

            # ── Step 7: Apply KYC confidence threshold ────────────────────────
            # MIN_KYC_CONFIDENCE = 0.70 from config (set 0.60 in .env for demo)
            # Below threshold = document quality too low to trust for KYC
            if mean_confidence < settings.MIN_KYC_CONFIDENCE:
                state.document_verified      = False
                state.manual_review_required = True
                # Note: this is not fraud detection — it is quality control.
                # A human reviewer will look at the original document.
            else:
                state.document_verified      = True
                state.manual_review_required = False

        except Exception:
            # Catch-all safety net.
            # In a pipeline, one agent crash must not stop all downstream agents.
            # Degrade gracefully — compliance agent will flag this case.
            state.document_verified      = False
            state.doc_confidence         = 0.0
            state.manual_review_required = True

        return state   # Always return state — never raise
