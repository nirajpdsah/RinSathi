# test_native_ocr.py
import cv2
import numpy as np
from utils.ocr import get_ocr_engine, _preprocess_image

def run_diagnostic():
    print("=== STARTING NATIVE DIAGNOSTIC TESTING ===")
    
    # 1. Read your test image file directly from disk
    image_path = "test_image.jpg"
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        print(f"Successfully loaded {image_path} ({len(image_bytes)} bytes)")
    except Exception as e:
        print(f"Error loading image file: {e}")
        return

    # 2. Run your specific OpenCV preprocessing pipeline
    print("Running image preprocessing operations...")
    try:
        processed_img = _preprocess_image(image_bytes)
        cv2.imwrite("diagnostic_processed.jpg", processed_img)
        print("Preprocessing complete. Diagnostic image exported to 'diagnostic_processed.jpg'")
    except Exception as e:
        print(f"Preprocessing failed: {e}")
        return

    # 3. Fire up the engine directly on the main process thread
    print("Initializing PaddleOCR core engine...")
    engine = get_ocr_engine()
    if not engine:
        print("Failed to load engine singleton block.")
        return

    print("Executing native OCR scanning pass...")
    try:
        # Call our updated, type-safe processing handler directly
        from utils.ocr import _run_ocr_sync
        results = _run_ocr_sync(image_bytes)
        
        print("\n" + "="*50)
        print("!!! NATIVE OCR REAL TEXT OUTPUT !!!")
        print("RAW STRING EXTRACTION:")
        print(results.get("raw_text", "--- NO TEXT EXTRACTED ---"))
        print("="*50 + "\n")
    except Exception as e:
        print(f"Core engine scanning failed: {e}")

if __name__ == "__main__":
    run_diagnostic()