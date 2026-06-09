# ── agents/document_agent.py ──────────────────────────────────────────────────
# The Document Agent: first agent in the ACLO pipeline.
# Receives raw image bytes, runs OCR, validates fields, updates SharedState.
# DESIGN PRINCIPLE: Never raises exceptions — always returns SharedState.
# If something fails, it degrades gracefully and flags for manual review.

from agents.shared_state import SharedState   # Our central data contract
from utils.ocr import run_ocr, extract_fields # OCR utilities
from config import get_settings

settings = get_settings()


class DocumentAgent:
    """
    Processes uploaded government documents through the OCR pipeline.
    Reads: image_bytes (passed directly, not from SharedState)
    Writes: document_verified, extracted_fields, doc_confidence, manual_review_required
    """

    async def run(self, state: SharedState, image_bytes: bytes) -> SharedState:
        # Main entry point. Always returns state — never raises.
        try:
            # ── Step 1: Run OCR pipeline ──────────────────────────────────────
            # run_ocr handles preprocessing, OCR, timeout, and fallback to mock
            ocr_result = await run_ocr(image_bytes)

            # ── Step 2: Handle OCR failure ────────────────────────────────────
            if ocr_result.get("timed_out") or ocr_result.get("error"):
                # OCR failed or timed out — mark for manual review
                # The Compliance Agent will detect manual_review_required=True
                # and add a KYC_INCOMPLETE flag, sending to human review
                state.document_verified      = False
                state.doc_confidence         = 0.0
                state.manual_review_required = True
                return state

            # ── Step 3: Extract structured fields from OCR text ────────────────
            fields = extract_fields(ocr_result)

            # ── Step 4: Calculate mean confidence across all extracted fields ──
            # This gives a single number representing overall document quality
            confidence_values = [f["confidence"] for f in fields.values()]
            mean_confidence   = (
                round(sum(confidence_values) / len(confidence_values), 3)
                if confidence_values else 0.0
            )

            # ── Step 5: Write results to SharedState ──────────────────────────
            state.extracted_fields = fields           # Structured field data
            state.doc_confidence   = mean_confidence  # Overall document quality score

            # ── Step 6: Apply KYC confidence threshold ─────────────────────────
            # MIN_KYC_CONFIDENCE = 0.70 (from config.py)
            # Below this threshold: the document scan quality is too low to trust
            if mean_confidence < settings.MIN_KYC_CONFIDENCE:
                state.document_verified      = False   # Doc did not pass quality check
                state.manual_review_required = True    # Flag for human review
            else:
                state.document_verified      = True    # Doc accepted — quality sufficient

        except Exception:
            # Safety net: if anything unexpected happens, degrade gracefully.
            # In a 5-agent pipeline, one crash must not stop all agents.
            state.document_verified      = False
            state.doc_confidence         = 0.0
            state.manual_review_required = True

        return state   # Always return state, whether success or failure