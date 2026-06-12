import uuid
from typing import Dict, Optional
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from pydantic import BaseModel
from utils.ocr import run_ocr, extract_fields

# Create the standard APIRouter instance mapped by main.py
router = APIRouter(tags=["Documents"])

# ─── 1. THE ORDER BOOK (IN-MEMORY CACHE) ───
jobs_db: Dict[str, dict] = {}

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None

# ─── 2. THE BACKGROUND WORKER ───
async def ocr_worker_task(job_id: str, image_bytes: bytes):
    """
    Independent background task that processes the image binarization 
    and PaddleOCR extraction away from the active client request thread.
    """
    jobs_db[job_id]["status"] = "processing"
    
    try:
        # Run optimized Gaussian-Otsu filter and text line detection
        ocr_result = await run_ocr(image_bytes)
        
        if "error" in ocr_result:
            jobs_db[job_id]["status"] = "failed"
            jobs_db[job_id]["error"] = ocr_result["error"]
            return

        # Extract the fields with coordinates and XXX guard active
        final_payload = extract_fields(ocr_result)
        
        jobs_db[job_id]["status"] = "completed"
        jobs_db[job_id]["result"] = final_payload
        
    except Exception as e:
        jobs_db[job_id]["status"] = "failed"
        jobs_db[job_id]["error"] = str(e)

# ─── 3. DECOUPLED UPLOAD ENDPOINT ───
# Note: Router uses "/" here because main.py prefixes it with "/api/v1/document"
@router.post("/document/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        job_id = str(uuid.uuid4())
        
        jobs_db[job_id] = {
            "status": "pending",
            "result": None,
            "error": None
        }
        
        # Dispatch task execution
        background_tasks.add_task(ocr_worker_task, job_id, image_bytes)
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Document uploaded successfully. Processing started in background."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initiate background job: {str(e)}")

# ─── 4. POLLING ENDPOINT ───
@router.get("/document/result/{job_id}", response_model=JobStatusResponse)
async def get_ocr_result(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job ID tracking ticket not found.")
        
    job_data = jobs_db[job_id]
    return JobStatusResponse(
        job_id=job_id,
        status=job_data["status"],
        result=job_data["result"],
        error=job_data["error"]
    )