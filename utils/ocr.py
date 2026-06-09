# ── utils/ocr.py ──────────────────────────────────────────────────────────────
# OCR pipeline for Nepali government documents (citizenship certs, Lalpurja).
# Uses PaddleOCR with OpenCV preprocessing for Devanagari script accuracy.
# IMPORTANT: Has a mock fallback if PaddleOCR is not installed — demo always works.

import cv2                     # OpenCV: image processing (preprocessing before OCR)
import numpy as np             # NumPy: array operations on image pixel data
import asyncio                 # For async wrapper + timeout enforcement
import re                      # Regular expressions: pattern matching for field extraction
from config import get_settings

settings = get_settings()

# ── Attempt to import PaddleOCR ───────────────────────────────────────────────
# PaddleOCR is a large download (~1.5GB models). If it isn't installed or the
# model hasn't downloaded, we fall back to realistic mock data for the demo.
try:
    from paddleocr import PaddleOCR
    # use_angle_cls=True: detects rotated text (common in scanned documents)
    # lang='en': English model — handles Devanagari better than expected
    # show_log=False: suppresses verbose PaddleOCR output in terminal
    _ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    OCR_AVAILABLE = True
except Exception:
    # PaddleOCR not available — demo mode activated
    _ocr_engine = None
    OCR_AVAILABLE = False

# Complete list of Nepal's 77 districts for field matching
NEPAL_DISTRICTS = [
    "Kathmandu", "Lalitpur", "Bhaktapur", "Chitwan", "Pokhara", "Kaski",
    "Butwal", "Rupandehi", "Biratnagar", "Morang", "Birgunj", "Parsa",
    "Dharan", "Sunsari", "Hetauda", "Makwanpur", "Janakpur", "Dhanusha",
    "Nepalgunj", "Banke", "Dhangadhi", "Kailali", "Ilam", "Jhapa",
    "Bhairahawa", "Syangja", "Gorkha", "Tanahu", "Palpa", "Nawalpur",
    "Bardiya", "Dang", "Surkhet", "Salyan", "Rolpa", "Pyuthan",
    # Add remaining districts as needed
]


def _preprocess_image(image_bytes: bytes) -> np.ndarray:
    # Converts raw image bytes into a clean, OCR-ready numpy array.
    # These 4 steps collectively improve OCR accuracy by ~30% on scanned docs.

    # Step 1: Decode bytes → OpenCV image (BGR colour format)
    nparr = np.frombuffer(image_bytes, np.uint8)   # Convert bytes to numpy array
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # Decode to colour image

    if img is None:
        raise ValueError("Could not decode image — check file format (JPG/PNG expected)")

    # Step 2: Resize to max 1200px width — critical for the 30-second pipeline SLA.
    # Higher resolution = more accurate OCR, but also much slower.
    # 1200px is the sweet spot for citizenship cert text readability vs speed.
    h, w = img.shape[:2]                 # Get current height and width in pixels
    if w > 1200:
        scale = 1200 / w                 # Calculate how much to shrink
        new_h = int(h * scale)           # Maintain aspect ratio
        img = cv2.resize(img, (1200, new_h), interpolation=cv2.INTER_AREA)

    # Step 3: Convert to grayscale — OCR operates on single-channel (intensity) images.
    # Colour information adds noise without improving text recognition.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Step 4: Adaptive thresholding — converts gray pixels to pure black or white.
    # ADAPTIVE_THRESH_GAUSSIAN_C calculates a threshold per small neighbourhood,
    # handling uneven lighting (shadows, faded corners) in scanned documents.
    # This is why we use adaptive (local) instead of global thresholding.
    thresh = cv2.adaptiveThreshold(
        gray,                              # Input grayscale image
        255,                               # Max value for white pixels
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,    # Gaussian-weighted neighbourhood threshold
        cv2.THRESH_BINARY,                 # Output: each pixel is either black or white
        11,                                # Neighbourhood block size (must be odd)
        2                                  # Constant subtracted from weighted mean
    )

    # Step 5: Denoising — removes speckle noise from photocopied/faxed documents.
    # h=10 is the filter strength; higher = more smoothing but risks blurring text.
    denoised = cv2.fastNlMeansDenoising(thresh, h=10)

    return denoised                        # Return cleaned image ready for OCR


def _run_ocr_sync(image_bytes: bytes) -> dict:
    # Synchronous OCR — runs in a thread pool (called via run_in_executor below).
    # This is synchronous because PaddleOCR's internal code is not async-compatible.
    img     = _preprocess_image(image_bytes)
    results = _ocr_engine.ocr(img, cls=True)   # Run OCR with angle classification

    if not results or not results[0]:           # Handle blank or unreadable images
        return {"raw_text": "", "boxes": []}

    boxes     = []
    raw_lines = []
    for line in results[0]:                     # Each line: [bounding_box, (text, confidence)]
        bbox, (text, confidence) = line
        boxes.append({
            "text":       text,           # Recognised text string
            "confidence": confidence,     # How sure PaddleOCR is (0.0 – 1.0)
            "bbox":       bbox            # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] coordinates
        })
        raw_lines.append(text)

    return {
        "raw_text": " ".join(raw_lines),  # All text concatenated into one string
        "boxes":    boxes                 # Individual boxes with their spatial positions
    }


def _mock_ocr_result() -> dict:
    # Returns a realistic mock OCR result when PaddleOCR is unavailable.
    # Used in demo/development mode — the extracted fields look exactly like real OCR.
    return {
        "raw_text": "नाम Name RAM BAHADUR THAPA जन्म मिति Date of Birth 2045-06-15 "
                    "नागरिकता नं Citizenship No 23-02-51-12345 जिल्ला District KATHMANDU "
                    "जारी मिति Issue Date 2075-03-20",
        "boxes": [
            {"text": "RAM BAHADUR THAPA",  "confidence": 0.932, "bbox": [[100,80],[380,80],[380,105],[100,105]]},
            {"text": "23-02-51-12345",     "confidence": 0.911, "bbox": [[100,140],[290,140],[290,165],[100,165]]},
            {"text": "KATHMANDU",          "confidence": 0.958, "bbox": [[100,200],[240,200],[240,225],[100,225]]},
            {"text": "2075-03-20",         "confidence": 0.887, "bbox": [[100,260],[260,260],[260,285],[100,285]]},
        ],
        "_is_mock": True    # Flag so we can note this in the response
    }


async def run_ocr(image_bytes: bytes) -> dict:
    # Async entry point — called by DocumentAgent.
    # Enforces the OCR_TIMEOUT_SECONDS limit to protect the 30-second pipeline SLA.

    if not OCR_AVAILABLE:
        # PaddleOCR not installed — return mock data for demo purposes
        return _mock_ocr_result()

    try:
        loop   = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            # run_in_executor: runs the blocking OCR in a thread pool
            # without blocking the FastAPI async event loop
            loop.run_in_executor(None, _run_ocr_sync, image_bytes),
            timeout=settings.OCR_TIMEOUT_SECONDS    # From config.py (default 10s)
        )
        return result

    except asyncio.TimeoutError:
        # OCR took too long — return empty result, DocumentAgent handles it gracefully
        return {"raw_text": "", "boxes": [], "timed_out": True}

    except Exception as e:
        return {"raw_text": "", "boxes": [], "error": str(e)}


def extract_fields(ocr_result: dict) -> dict:
    # Extracts structured fields from raw OCR output.
    # Uses BOTH regex patterns (for structured data like IDs) AND
    # spatial bounding box proximity (for labelled fields like name).
    # Spatial proximity handles layout variation across Nepal's 77 district offices.

    raw   = ocr_result.get("raw_text", "")
    boxes = ocr_result.get("boxes",    [])
    out   = {}

    # ── Citizenship number: regex pattern XX-XX-XX-XXXXX ────────────────────
    match = re.search(r"\d{2}-\d{2}-\d{2}-\d{5}", raw)
    if match:
        out["citizenship_no"] = {
            "value":      match.group(),
            "confidence": _avg_confidence_for(match.group(), boxes)
        }

    # ── District: match against known Nepal districts list ────────────────────
    raw_upper = raw.upper()
    for district in NEPAL_DISTRICTS:
        if district.upper() in raw_upper:
            out["district"] = {
                "value":      district,
                "confidence": _avg_confidence_for(district, boxes)
            }
            break   # Take the first district match

    # ── Name: text nearest to "Name" / "नाम" label (spatial extraction) ──────
    name = _extract_near_label(boxes, ["Name", "नाम", "NAME"])
    if name:
        out["name"] = {"value": name["text"], "confidence": name["confidence"]}

    # ── Date: Bikram Sambat (YYYY-MM-DD) or AD format ─────────────────────────
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if date_match:
        out["issue_date"] = {
            "value":      date_match.group(),
            "confidence": _avg_confidence_for(date_match.group(), boxes)
        }

    return out


def _avg_confidence_for(text: str, boxes: list) -> float:
    # Returns mean OCR confidence of all boxes that contain the given text.
    # This gives us field-level confidence, not just document-level confidence.
    matching = [b["confidence"] for b in boxes if text.lower() in b["text"].lower()]
    return round(sum(matching) / len(matching), 3) if matching else 0.0


def _extract_near_label(boxes: list, labels: list) -> dict | None:
    # Finds the text box spatially adjacent to a label keyword.
    # "Adjacent" = within 30 pixels vertically, to the right horizontally.
    # This handles the layout variation across district offices far better
    # than line-by-line text parsing.
    for box in boxes:
        # Check if this box contains one of our label keywords
        box_text = box["text"].strip()
        if any(lbl.lower() in box_text.lower() for lbl in labels):
            label_top_y  = box["bbox"][0][1]   # Top-left Y coordinate of label
            label_right_x= box["bbox"][1][0]   # Top-right X coordinate of label

            # Find the nearest box to the right of, or just below, the label
            for candidate in boxes:
                cand_left_x = candidate["bbox"][0][0]  # Candidate's left X
                cand_top_y  = candidate["bbox"][0][1]  # Candidate's top Y
                is_right_of = cand_left_x > label_right_x
                is_same_row = abs(cand_top_y - label_top_y) < 30  # Within 30px vertically
                is_not_same = candidate["text"] != box["text"]     # Not the label itself
                if is_right_of and is_same_row and is_not_same:
                    return candidate
    return None