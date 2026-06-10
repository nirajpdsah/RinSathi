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
    return templates.TemplateResponse(
    request=request,
    name="login.html"
)

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
