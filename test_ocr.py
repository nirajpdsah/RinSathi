print("Importing PaddleOCR...")
from paddleocr import PaddleOCR
print("Import OK")

# ========================================================
# FIX 1: Switched language to 'ne' & fixed deprecated arg
# ========================================================
ocr = PaddleOCR(
    lang='ne',                       # Crucial: Loads Devanagari support for Nepali text
    use_textline_orientation=False,  # Disables heavy server unwarping models
    cpu_threads=4,                   # Distributes processing across CPU cores
    text_det_limit_side_len=960,     # Fixed: Replaced deprecated det_limit_side_len
    enable_mkldnn=False              # Bypasses the PaddlePaddle 3.3.0 framework bug
)
print("Engine initialised OK")

# Test on any image file
TEST_IMAGE = "test_image.jpg"

import os
if not os.path.exists(TEST_IMAGE):
    print(f"\nNo test image found at {TEST_IMAGE}")
    print("Create a test image first:")
    print("  - Take a photo of any document with your phone")
    print("  - Copy it to D:\\RinSathi\\")
    print("  - Rename it to test_image.jpg")
    print("\nOCR engine is working -- just needs an image to process.")
else:
    print(f"\nRunning OCR on {TEST_IMAGE}...")
    result = list(ocr.predict(TEST_IMAGE))

    # ========================================================
    # FIX 2: Universal dictionary fallback for PaddleX formats
    # ========================================================
    if result:
        for res in result:
            # Safely unpack the internal layout data
            data = res.json.get('res', res.json)
            
            # Fallback checking for plural vs singular pipeline keys
            texts = data.get('rec_texts', data.get('rec_text', []))
            boxes = data.get('rec_polys', data.get('dt_polys', []))
            scores = data.get('rec_scores', data.get('rec_score', data.get('dt_scores', [])))
            
            if texts:
                print(f"\nExtracted {len(texts)} text regions:\n")
                for box, text, score in zip(boxes, texts, scores):
                    print(f"  {score:.3f}  |  {text}")
            else:
                print("No text detected -- language model found no matching script elements.")
    else:
        print("No text detected -- try a clearer image")