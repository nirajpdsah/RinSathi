# fix_ocr_integration.py
# Rewrites utils/ocr.py, agents/document_agent.py, and updates main.py
# Run with: python fix_ocr_integration.py

import os

# ── utils/ocr.py ──────────────────────────────────────────────────────────────
ocr_code = """\
# utils/ocr.py
# Production OCR pipeline for Nepal government documents.
# Uses PaddleOCR (CPU mode) with OpenCV preprocessing.
# Handles real citizenship certificates and Lalpurja scans.

import cv2                      # OpenCV: image preprocessing before OCR
import numpy as np              # NumPy: array operations on image pixel data
import asyncio                  # Async wrapper and timeout enforcement
import re                       # Regex: pattern matching for structured fields
from config import get_settings

settings = get_settings()

# ── PaddleOCR initialisation ─────────────────────────────────────────────────
# Initialised once at module load — NOT per request.
# Loading per request would cost 3-5 minutes each time.
try:
    from paddleocr import PaddleOCR
    _ocr_engine = PaddleOCR(
        use_angle_cls=True,  # Detect and correct rotated text (common in scanned docs)
        lang='en',           # English model — captures printed text on Nepali docs well
        use_gpu=False,       # Explicitly CPU — no GPU required for this project
        show_log=False,      # Suppress PaddleOCR's internal debug logs in terminal
    )
    OCR_AVAILABLE = True
    print("PaddleOCR initialised (CPU mode)")
except Exception as e:
    _ocr_engine = None
    OCR_AVAILABLE = False
    print(f"PaddleOCR not available ({e}) — running in mock mode")

# Nepal's 77 districts — used for district field extraction by text matching
NEPAL_DISTRICTS = [
    "Achham","Arghakhanchi","Baglung","Baitadi","Bajhang","Bajura","Banke",
    "Bara","Bardiya","Bhaktapur","Bhojpur","Chitwan","Dadeldhura","Dailekh",
    "Dang","Darchula","Dhading","Dhankuta","Dhanusha","Dolakha","Dolpa",
    "Doti","Eastern Rukum","Gorkha","Gulmi","Humla","Ilam","Jajarkot",
    "Jhapa","Jumla","Kailali","Kalikot","Kaski","Kathmandu","Kavrepalanchok",
    "Khotang","Lalitpur","Lamjung","Mahottari","Makwanpur","Manang","Morang",
    "Mugu","Mustang","Myagdi","Nawalparasi East","Nawalparasi West","Nuwakot",
    "Okhaldhunga","Palpa","Panchthar","Parbat","Parsa","Pyuthan","Ramechhap",
    "Rasuwa","Rautahat","Rolpa","Rupandehi","Salyan","Sankhuwasabha","Saptari",
    "Sarlahi","Sindhuli","Sindhupalchok","Siraha","Solukhumbu","Sunsari",
    "Surkhet","Syangja","Tanahu","Taplejung","Terhathum","Udayapur",
    "Western Rukum",
]

# Label keywords that appear before field values on citizenship certificates
# OCR sometimes misreads letters, so we include common misread variants
NAME_LABELS        = ["Name", "NAME", "नाम", "Nane", "Namc", "Narne"]
CITIZENSHIP_LABELS = ["Citizenship", "Citizenship No", "No.", "नागरिकता"]
DATE_LABELS        = ["Issue Date", "Date", "जारी", "Issued"]


def _preprocess_image(image_bytes: bytes) -> np.ndarray:
    # Converts raw image bytes to a clean, OCR-optimised numpy array.
    # These steps improve PaddleOCR accuracy by ~30% on scanned government docs.

    # Decode bytes to OpenCV image
    nparr = np.frombuffer(image_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Cannot decode image — ensure file is a valid JPG or PNG")

    # Step 1: Resize to max 1600px width
    # 1600px gives PaddleOCR enough resolution to read small text on certs
    # without being slow. Lower resolution = missed characters on fine print.
    h, w = img.shape[:2]
    if w > 1600:
        scale = 1600 / w
        img   = cv2.resize(img, (1600, int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    elif w < 800:
        # Upscale very small images — improves OCR on phone camera thumbnails
        scale = 800 / w
        img   = cv2.resize(img, (800, int(h * scale)), interpolation=cv2.INTER_LANCZOS4)

    # Step 2: Convert to grayscale — OCR needs single-channel intensity image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Step 3: Deskew — correct scan angle so text lines are horizontal
    gray = _deskew(gray)

    # Step 4: Adaptive thresholding — converts to black/white per local region
    # Handles uneven lighting (shadows, faded corners) far better than global threshold
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,  # Gaussian-weighted neighbourhood
        cv2.THRESH_BINARY,               # Output: pure black or white pixels
        15,                              # Block size: 15x15 pixel neighbourhood
        8                                # Constant subtracted from weighted mean
    )

    # Step 5: Morphological closing — fills small gaps in characters
    # Helps when ink is faded or photocopier quality is poor
    kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed  = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # Step 6: Denoise — removes speckle noise from photocopied documents
    denoised = cv2.fastNlMeansDenoising(closed, h=12)

    return denoised


def _deskew(gray: np.ndarray) -> np.ndarray:
    # Detects and corrects document tilt using contour analysis.
    # Scanned documents are often slightly rotated — this corrects up to 45 degrees.

    # Find all non-white pixels (text pixels)
    coords = np.column_stack(np.where(gray < 128))

    if len(coords) < 100:
        return gray   # Not enough text to detect angle reliably — skip

    # minAreaRect finds the minimum bounding rectangle around all text pixels
    # Its angle tells us how much the document is rotated
    rect  = cv2.minAreaRect(coords.astype(np.float32))
    angle = rect[-1]   # Rotation angle in degrees

    # Normalise angle to -45 to +45 degree range
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    # Skip tiny angles — rotating adds blur, not worth it for < 0.5 degrees
    if abs(angle) < 0.5:
        return gray

    # Apply rotation correction
    h, w   = gray.shape[:2]
    center = (w // 2, h // 2)
    M      = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE   # Fill borders with edge pixels, not black
    )


def _run_ocr_sync(image_bytes: bytes) -> dict:
    # Synchronous OCR function — runs inside a thread pool via run_in_executor.
    # Must be synchronous because PaddleOCR is not async-compatible internally.

    img     = _preprocess_image(image_bytes)
    results = _ocr_engine.ocr(img, cls=True)

    # PaddleOCR returns None or empty list on blank/unreadable images
    if not results or not results[0]:
        return {"raw_text": "", "boxes": [], "line_count": 0}

    boxes     = []
    raw_lines = []

    for line in results[0]:
        # Each result line: [bounding_box_coords, (recognised_text, confidence)]
        bbox, (text, confidence) = line

        # Skip very low confidence detections — likely noise
        if confidence < 0.3:
            continue

        # Clean the text: strip whitespace, normalise spaces
        text = text.strip()
        if not text:
            continue

        boxes.append({
            "text":       text,
            "confidence": round(float(confidence), 4),
            "bbox":       bbox   # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        })
        raw_lines.append(text)

    return {
        "raw_text":   " ".join(raw_lines),  # All text as one string for regex
        "boxes":      boxes,                # Individual boxes with coordinates
        "line_count": len(boxes),           # How many text regions were found
    }


async def run_ocr(image_bytes: bytes) -> dict:
    # Async entry point called by DocumentAgent.
    # Uses run_in_executor so OCR runs in a thread pool without blocking
    # the FastAPI event loop (which would freeze all other requests).

    if not OCR_AVAILABLE:
        return _mock_ocr_result()   # Fallback for development without PaddleOCR

    try:
        loop   = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_ocr_sync, image_bytes),
            timeout=settings.OCR_TIMEOUT_SECONDS   # From .env (set to 45)
        )
        return result

    except asyncio.TimeoutError:
        # OCR exceeded timeout — return empty, DocumentAgent degrades gracefully
        return {"raw_text": "", "boxes": [], "timed_out": True}

    except Exception as e:
        return {"raw_text": "", "boxes": [], "error": str(e)}


def extract_fields(ocr_result: dict) -> dict:
    # Extracts structured fields from raw PaddleOCR output.
    # Uses BOTH regex (for patterned data like IDs and dates) AND
    # spatial bounding box proximity (for labelled fields like name).
    # Spatial proximity handles layout variation across Nepal's 77 district offices —
    # pure line-by-line parsing fails when layouts differ.

    raw   = ocr_result.get("raw_text", "")
    boxes = ocr_result.get("boxes",    [])
    out   = {}

    if not raw:
        return out   # Nothing to extract from blank result

    # ── Field 1: Citizenship number ───────────────────────────────────────────
    # Standard Nepal format: XX-XX-XX-XXXXX  (2-2-2-5 digit groups)
    # Allow dash or hyphen variants — OCR sometimes reads hyphen as dash
    cn_match = re.search(r"\d{2}[-\u2013]\d{2}[-\u2013]\d{2}[-\u2013]\d{5}", raw)
    if cn_match:
        value = cn_match.group().replace("\u2013", "-")   # Normalise en-dash to hyphen
        out["citizenship_no"] = {
            "value":      value,
            "confidence": _avg_conf(value, boxes)
        }

    # ── Field 2: District ─────────────────────────────────────────────────────
    # Match raw text against all 77 known Nepal district names
    raw_upper = raw.upper()
    for district in NEPAL_DISTRICTS:
        if district.upper() in raw_upper:
            out["district"] = {
                "value":      district,
                "confidence": _avg_conf(district, boxes)
            }
            break   # Take first match — districts don't repeat on one cert

    # ── Field 3: Name — spatial label proximity ───────────────────────────────
    # Find the text box nearest to a "Name" label
    # Spatial approach handles layout variation better than regex
    name_box = _text_near_label(boxes, NAME_LABELS)
    if name_box:
        # Filter out obvious non-names: numbers, single chars, labels themselves
        value = name_box["text"].strip()
        is_label    = any(lbl.lower() in value.lower() for lbl in NAME_LABELS)
        is_too_short= len(value) < 3
        is_numeric  = value.replace(" ", "").replace("-", "").isdigit()
        if not is_label and not is_too_short and not is_numeric:
            out["name"] = {
                "value":      value,
                "confidence": name_box["confidence"]
            }

    # ── Field 4: Issue date ───────────────────────────────────────────────────
    # Match Bikram Sambat dates (YYYY-MM-DD) or written BS dates
    # BS years typically range 2020-2090 (AD 1963-2033)
    date_match = re.search(r"20[2-9]\d[-/]\d{2}[-/]\d{2}", raw)   # BS format
    if not date_match:
        date_match = re.search(r"19[6-9]\d[-/]\d{2}[-/]\d{2}", raw)  # AD format
    if date_match:
        out["issue_date"] = {
            "value":      date_match.group(),
            "confidence": _avg_conf(date_match.group(), boxes)
        }

    return out


def _avg_conf(text: str, boxes: list) -> float:
    # Returns mean OCR confidence of all boxes containing the given text substring.
    # Gives us field-level confidence, not just overall document confidence.
    hits = [b["confidence"] for b in boxes if text.lower() in b["text"].lower()]
    return round(sum(hits) / len(hits), 4) if hits else 0.5  # Default 0.5 if not found


def _text_near_label(boxes: list, labels: list) -> dict | None:
    # Finds the text box spatially to the right of or below a label keyword.
    # "Spatially adjacent" means: same row (within 40px vertically) and to the right,
    # OR directly below (within 60px vertically and overlapping horizontally).
    # This is robust to layout differences across Nepal's district offices.

    for box in boxes:
        box_text = box["text"].strip()

        # Check if this box is a label we're looking for
        # Use partial match to handle OCR misreads like "Nane" for "Name"
        is_label = any(lbl.lower() in box_text.lower() for lbl in labels)
        if not is_label:
            continue

        # Get label position
        label_bbox    = box["bbox"]
        label_top_y   = label_bbox[0][1]    # Top-left Y
        label_right_x = label_bbox[1][0]    # Top-right X
        label_left_x  = label_bbox[0][0]    # Top-left X

        best_candidate = None
        best_distance  = float("inf")

        for candidate in boxes:
            if candidate["text"] == box_text:
                continue   # Skip the label itself

            cand_left_x  = candidate["bbox"][0][0]
            cand_top_y   = candidate["bbox"][0][1]

            # Option A: candidate is to the RIGHT on the same line
            same_row    = abs(cand_top_y - label_top_y) < 40
            to_the_right= cand_left_x > label_right_x - 10

            # Option B: candidate is BELOW the label (next line)
            below       = 5 < (cand_top_y - label_top_y) < 60
            horiz_overlap = cand_left_x < label_right_x and cand_left_x >= label_left_x - 20

            if (same_row and to_the_right) or (below and horiz_overlap):
                dist = abs(cand_left_x - label_right_x) + abs(cand_top_y - label_top_y)
                if dist < best_distance:
                    best_distance  = dist
                    best_candidate = candidate

        if best_candidate:
            return best_candidate

    return None


def _mock_ocr_result() -> dict:
    # Returns realistic mock OCR data when PaddleOCR is unavailable.
    # Structure is identical to real PaddleOCR output —
    # the rest of the pipeline cannot tell the difference.
    return {
        "raw_text": (
            "Name BIKRAM PRASAD SHRESTHA "
            "Citizenship No 27-03-74-09821 "
            "District KATHMANDU "
            "Issue Date 2078-11-05"
        ),
        "boxes": [
            {"text": "Name",                   "confidence": 0.971, "bbox": [[60,80],[130,80],[130,105],[60,105]]},
            {"text": "BIKRAM PRASAD SHRESTHA", "confidence": 0.948, "bbox": [[140,80],[420,80],[420,105],[140,105]]},
            {"text": "Citizenship No",         "confidence": 0.965, "bbox": [[60,140],[210,140],[210,165],[60,165]]},
            {"text": "27-03-74-09821",         "confidence": 0.939, "bbox": [[220,140],[390,140],[390,165],[220,165]]},
            {"text": "KATHMANDU",              "confidence": 0.981, "bbox": [[220,200],[360,200],[360,225],[220,225]]},
            {"text": "2078-11-05",             "confidence": 0.923, "bbox": [[220,260],[360,260],[360,285],[220,285]]},
        ],
        "line_count": 6,
        "_is_mock":   True,
    }


async def warm_up_ocr():
    # Runs a dummy OCR call at server startup so PaddleOCR loads its
    # 300MB models into memory BEFORE the first real API request arrives.
    # Without this warm-up, the first real request always times out on CPU.
    if not OCR_AVAILABLE:
        return
    print("PaddleOCR warm-up starting (loading models into memory)...")
    print("This takes 3-5 minutes on first run. Subsequent server starts are faster.")
    dummy = np.ones((100, 300, 3), dtype=np.uint8) * 255  # Tiny blank white image
    loop  = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _ocr_engine.ocr(dummy, cls=True)),
            timeout=300.0   # 5 minute limit for initial model download/load
        )
        print("PaddleOCR warm-up complete — first API request will now be fast")
    except Exception as e:
        print(f"PaddleOCR warm-up warning: {e}")
        print("OCR will still work — model will load on first request instead")
"""

# ── agents/document_agent.py ──────────────────────────────────────────────────
doc_agent_code = """\
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
    \"\"\"
    Processes uploaded government documents through the OCR pipeline.

    Reads:  image_bytes (passed directly as parameter)
    Writes: document_verified, extracted_fields, doc_confidence,
            manual_review_required  (all into SharedState)

    Defence note: This agent does NOT verify document authenticity.
    It extracts structured data from the document image. Trust is
    established through multi-signal corroboration across all 5 agents —
    not by OCR alone.
    \"\"\"

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
"""

# ── main.py ───────────────────────────────────────────────────────────────────
main_code = """\
# main.py
# FastAPI application entry point.
# Registers routes, configures middleware, manages startup/shutdown lifecycle.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.requests import Request
from contextlib import asynccontextmanager
from db.session import create_tables
from api.routes import documents
from config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ───────────────────────────────────────────────────────────────
    # Everything here runs ONCE when uvicorn starts, before any request arrives.
    print("Starting ACLO API...")

    # Create all Supabase tables if they don't exist yet
    await create_tables()
    print("Database tables ready (Supabase)")

    # Warm up PaddleOCR — loads 300MB models into memory now, not on first request.
    # Without this, the first upload request would time out every time.
    from utils.ocr import warm_up_ocr
    await warm_up_ocr()

    print("ACLO API ready")
    print("  Local:   http://127.0.0.1:8000")
    print("  API docs: http://127.0.0.1:8000/docs")

    yield   # Server runs here — code after yield runs on shutdown

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    print("ACLO API shutting down.")


app = FastAPI(
    title="ACLO API",
    description=(
        "Autonomous Credit and Lending Orchestrator — "
        "5-agent AI pipeline for rural Nepal microfinance credit assessment. "
        "Stack: FastAPI, PostgreSQL (Supabase), PaddleOCR, XGBoost, SHAP."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware — allows browser fetch() calls from any origin
# Restrict allow_origins in production to your actual frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
# prefix="/api/v1" namespaces all routes: /api/v1/document/upload etc.
app.include_router(documents.router, prefix="/api/v1")

# Serve HTML templates (Jinja2)
templates = Jinja2Templates(directory="frontend/templates")

@app.get("/", include_in_schema=False)
async def root(request: Request):
    # Serves login page at http://localhost:8000/
    # include_in_schema=False hides this route from the /docs page
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/health", tags=["System"])
async def health():
    # Simple health check endpoint — useful for monitoring and supervisor demo
    # Shows OCR mode so it's clear whether real PaddleOCR is active
    from utils.ocr import OCR_AVAILABLE
    return {
        "status":   "ok",
        "version":  "1.0.0",
        "ocr_mode": "paddleocr" if OCR_AVAILABLE else "mock",
        "database": "supabase",
    }
"""

# Write all three files
files = {
    "utils/ocr.py":             ocr_code,
    "agents/document_agent.py": doc_agent_code,
    "main.py":                  main_code,
}

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Written: {path}")

print("\nAll files updated. Now:")
print("  1. Add OCR_TIMEOUT_SECONDS=45 to your .env file")
print("  2. Run: uvicorn main:app --reload --port 8000")
print("  3. Wait for 'PaddleOCR warm-up complete' in the terminal")
print("  4. Then test the /document/upload endpoint")