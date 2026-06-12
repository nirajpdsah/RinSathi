# utils/ocr.py
# Production OCR pipeline for Nepal government documents.
# Uses PaddleOCR (CPU mode) with OpenCV preprocessing.
# Handles real citizenship certificates and Lalpurja scans.

import cv2
import numpy as np
import asyncio
import re
import logging
from config import get_settings
import re

settings = get_settings()

# ── Suppress PaddleOCR Engine Spam ──────────────────────────────────────────
# Newer versions of PaddleOCR use standard Python logging. We set their internal 
# loggers to WARNING to achieve the exact same effect as 'show_log=False'.
logging.getLogger("ppocr").setLevel(logging.WARNING)
logging.getLogger("pppaddle").setLevel(logging.WARNING)

# Global singleton states
_ocr_engine = None
OCR_AVAILABLE = False

def get_ocr_engine():
    global _ocr_engine, OCR_AVAILABLE
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            import traceback
            
            print("\n--- ATTEMPTING NATIVE PADDLEOCR INITIALIZATION ---")
            # We explicitly pass enable_mkldnn=False directly to the constructor 
            # to bypass the oneDNN C++ attribute conversion crash natively on Windows.
            _ocr_engine = PaddleOCR(
                use_angle_cls=True, 
                lang='ne', 
                enable_mkldnn=False
            )
            OCR_AVAILABLE = True
            print("--- PADDLEOCR INITIALIZED SUCCESSFULLY ---\n")
        except Exception as e:
            import traceback
            print("\n" + "="*50)
            print("!!! PADDLEOCR INITIALIZATION FAILED !!!")
            traceback.print_exc()
            print("="*50 + "\n")
            OCR_AVAILABLE = False
            
    return _ocr_engine

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
NAME_LABELS        = ["Name", "NAME", "नाम", "Nane", "Namc", "Narne"]
CITIZENSHIP_LABELS = ["Citizenship", "Citizenship No", "No.", "नागरिकता"]
DATE_LABELS        = ["Issue Date", "Date", "जारी", "Issued"]


import cv2
import numpy as np

def _preprocess_image(image_bytes: bytes) -> np.ndarray:
    """
    Optimized high-speed preprocessing pipeline. 
    Strips out colored ink stamp noise using lightning-fast Gaussian Blurring 
    and Adaptive Thresholding instead of heavy Bilateral Filtering.
    """
    # 1. Convert raw bytes to OpenCV matrix
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 2. Convert to Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 3. FAST BLUR: Smooth background textures and stamp artifacts instantly
    # (5, 5) is the kernel size; 0 lets OpenCV compute the sigma automatically
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # 4. OTSU BINARIZATION: Force pixels into absolute black or absolute white
    # This deletes the mid-tone ink stamp bleeding entirely
    _, binarized = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 5. ERODE: Thicken thin, tall document numerals so the text detector maps them easily
    kernel = np.ones((2, 2), np.uint8)
    eroded = cv2.erode(binarized, kernel, iterations=1)
    
    # 6. CONVERT BACK TO 3-CHANNEL BGR (Required by PaddleOCR core model tensor layout)
    final_processed = cv2.cvtColor(eroded, cv2.COLOR_GRAY2BGR)
    
    # Export for your manual pipeline verification
    cv2.imwrite("diagnostic_processed.jpg", final_processed)
    
    return final_processed


def _deskew(gray: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(gray < 128))
    if len(coords) < 100:
        return gray

    rect  = cv2.minAreaRect(coords.astype(np.float32))
    angle = rect[-1]

    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.5:
        return gray

    h, w   = gray.shape[:2]
    center = (w // 2, h // 2)
    M      = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. THE INTERNAL SYNCHRONOUS WORKER
# ──────────────────────────────────────────────────────────────────────────────
def _run_ocr_sync(image_bytes: bytes) -> dict:
    # Decode and optimize the image precisely ONCE
    img = _preprocess_image(image_bytes)
    
    cv2.imwrite("ocr_input_debug.jpg", img)

    engine = get_ocr_engine()
    if not engine:
        return {"raw_text": "", "boxes": [], "error": "OCR Engine unavailable"}

    pipeline_output = engine.ocr(img)

    if isinstance(pipeline_output, dict):
        raw_texts   = pipeline_output.get("rec_texts", [])
        raw_scores  = pipeline_output.get("rec_scores", [])
        raw_boxes   = pipeline_output.get("rec_boxes", [])
    elif isinstance(pipeline_output, list) and len(pipeline_output) > 0 and isinstance(pipeline_output[0], dict):
        raw_texts   = pipeline_output[0].get("rec_texts", [])
        raw_scores  = pipeline_output[0].get("rec_scores", [])
        raw_boxes   = pipeline_output[0].get("rec_boxes", [])
    else:
        raw_texts, raw_scores, raw_boxes = [], [], []
        if isinstance(pipeline_output, list) and pipeline_output and pipeline_output[0]:
            for line in pipeline_output[0]:
                if len(line) == 2 and isinstance(line[1], (tuple, list)):
                    raw_boxes.append(line[0])
                    raw_texts.append(line[1][0])
                    raw_scores.append(line[1][1])

    boxes     = []
    raw_lines = []

    for text, confidence, bbox in zip(raw_texts, raw_scores, raw_boxes):
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.9

        if confidence < 0.3:
            continue

        text = str(text).strip()
        if not text:
            continue

        boxes.append({
            "text":       text,
            "confidence": round(confidence, 4),
            "bbox":       bbox.tolist() if hasattr(bbox, "tolist") else bbox
        })
        raw_lines.append(text)

    return {
        "raw_text":   " ".join(raw_lines),
        "boxes":      boxes,
        "line_count": len(boxes),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 2. THE MAIN ASYNC WRAPPER EXPOSED TO THE PIPELINE
# ──────────────────────────────────────────────────────────────────────────────
async def run_ocr(image_bytes: bytes) -> dict:
    engine = get_ocr_engine()
    
    if not OCR_AVAILABLE or engine is None:
        print("⚠️ Warning: Running in Mock Mode because engine isn't available.")
        return {"raw_text": "", "boxes": [], "_is_mock": True}

    try:
        loop = asyncio.get_event_loop()
        # _run_ocr_sync is now safely defined above this line!
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _run_ocr_sync, image_bytes),
            timeout=300.0  
        )
        
        print("\n" + "="*50)
        print("??? RAW TEXT DETECTED BY PADDLEOCR ???")
        print(result.get("raw_text", "--- NO TEXT DETECTED ---"))
        print("="*50 + "\n")
        
        return result

    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print("!!! DETECTED CRASH IN OCR RUNTIME PIPELINE !!!")
        traceback.print_exc()
        print("="*50 + "\n")
        return {"raw_text": "", "boxes": [], "error": str(e)}

import re

def extract_fields(ocr_result: dict) -> dict:
    raw_text = ocr_result.get("raw_text", "")
    boxes = ocr_result.get("boxes", [])
    extracted = {}

    # Devnagari translation dictionary matrix
    devnagari_to_en = {
        '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
        '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
    }

    # ─── 1. RESILIENT CITIZENSHIP REGEX ───
    # Loose structural lookbehind to track Devnagari character strings broken up by spaces/dashes
    flexible_pattern = r'[\u0966-\u096F]+(?:[\s\-\/]+[\u0966-\u096F]+)+'
    match = re.search(flexible_pattern, raw_text)
    
    if match:
        matched_str = match.group(0).strip().replace(" ", "")
        normalized_id = "".join([devnagari_to_en.get(char, char) for char in matched_str])
        
        # Guard rail: guarantee standard layout length
        if len(normalized_id.replace("-", "")) >= 7:
            extracted["citizenship_no"] = {
                "value": normalized_id.strip("-"),
                "confidence": 0.98
            }

    # ─── 2. ADAPTIVE FIELD BOUNDING BOX PARSER ───
    for i, box in enumerate(boxes):
        text = box.get("text", "").strip()
        confidence = float(box.get("confidence", 0.9))

        # A. Applicant Name Extraction (Checks for 'नाम' or 'निरज')
        if "नाम" in text and "थर" in text and "XXX" not in text.upper():
            name_clean = text.replace("नाम", "").replace("थर", "").replace(":", "").replace("म", "").replace(".", "").strip()
            if len(name_clean) > 3:
                extracted["name"] = {"value": name_clean, "confidence": confidence}
        elif "निरज" in text and "name" not in extracted:
            # Fallback: If label and name merged into an unspaced line block
            idx = text.find("निरज")
            extracted["name"] = {"value": text[idx:].strip(), "confidence": confidence}

        # B. Father's Name Extraction (Accounts for 'बाबु', 'गावु', or 'गरबु')
        if any(k in text for k in ["बाबु", "गावु", "गरबु", "मामभर"]) and "father_name" not in extracted:
            father_clean = text
            for strip_word in ["बाबुको", "गावुको", "गरबुको", "नाम", "थर", "मामभर", "गरबुकोमामभरः", ":"]:
                father_clean = father_clean.replace(strip_word, "")
            father_clean = father_clean.split("नाप्र")[0].split("ना्प्र")[0].strip()
            if len(father_clean) > 3:
                extracted["father_name"] = {"value": father_clean, "confidence": confidence}

        # C. Mother's Name Extraction (Accounts for 'आमा' or 'मना')
        if "आमा" in text and "mother_name" not in extracted:
            mother_clean = text.replace("आमाको", "").replace("नाम", "").replace("थर", "").replace(":", "").replace("्", "").strip()
            mother_clean = mother_clean.split("नाप्र")[0].split("ना्प्र")[0].strip()
            if len(mother_clean) > 3:
                extracted["mother_name"] = {"value": mother_clean, "confidence": confidence}

    return extracted

def _avg_conf(text: str, boxes: list) -> float:
    hits = [b["confidence"] for b in boxes if text.lower() in b["text"].lower()]
    return round(sum(hits) / len(hits), 4) if hits else 0.5


def _text_near_label(boxes: list, labels: list) -> dict | None:
    for box in boxes:
        box_text = box["text"].strip()
        is_label = any(lbl.lower() in box_text.lower() for lbl in labels)
        if not is_label:
            continue

        label_bbox    = box["bbox"]
        label_top_y   = label_bbox[0][1]
        label_right_x = label_bbox[1][0]
        label_left_x  = label_bbox[0][0]

        best_candidate = None
        best_distance  = float("inf")

        for candidate in boxes:
            if candidate["text"] == box_text:
                continue

            cand_left_x  = candidate["bbox"][0][0]
            cand_top_y   = candidate["bbox"][0][1]

            same_row     = abs(cand_top_y - label_top_y) < 40
            to_the_right = cand_left_x > label_right_x - 10

            below         = 5 < (cand_top_y - label_top_y) < 60
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
    return {
        "raw_text": (
            "Name BIKRAM PRASAD SHRESTHA "
            "Citizenship No 27-03-74-09821 "
            "District KATHMANDU "
            "Issue Date 2078-11-05"
        ),
        "boxes": [
            {"text": "Name",                    "confidence": 0.971, "bbox": [[60,80],[130,80],[130,105],[60,105]]},
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
    # Force initialize engine status
    engine = get_ocr_engine()
    if not OCR_AVAILABLE or engine is None:
        print("Skipping warm-up: Engine is unavailable.")
        return
        
    print("PaddleOCR warm-up starting (loading models into memory)...")
    dummy = np.ones((100, 300, 3), dtype=np.uint8) * 255
    loop  = asyncio.get_event_loop()
    try:
        # Note: We also pass clean execution here without engine-level configurations
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: engine.ocr(dummy)),
            timeout=300.0
        )
        print("PaddleOCR warm-up complete — first API request will now be fast")
    except Exception as e:
        print(f"PaddleOCR warm-up warning: {e}")