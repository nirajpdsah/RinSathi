# main.py
# FastAPI application entry point.
# Registers routes, configures middleware, manages startup/shutdown lifecycle.

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db.session import create_tables
from api.routes import documents, income, loan
from config import get_settings
from agents.score_agent import ScoreAgent
from routers import auth as auth_router
from routers.auth import router as auth_router
from routers.mock_gov import router as mock_gov_router

settings = get_settings()

# Serve HTML templates (Jinja2)
templates = Jinja2Templates(directory="frontend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ───────────────────────────────────────────────────────────────
    # Everything here runs ONCE when uvicorn starts, before any request arrives.
    print("Starting RinSathi ACLO API...")

    # Create all Supabase tables if they don't exist yet
    await create_tables()
    print("Database tables ready (Supabase)")

    # Warm up PaddleOCR — loads models into memory now, not on first request.
    from utils.ocr import warm_up_ocr
    await warm_up_ocr()

    print("ACLO API ready")
    print("  Local:     http://127.0.0.1:8000")
    print("  API docs:  http://127.0.0.1:8000/docs")
    print("  Dashboard: http://127.0.0.1:8000/dashboard")

    yield   # Server runs here — code after yield runs on shutdown

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    print("ACLO API shutting down.")


# SINGLE APP INITIALIZATION
app = FastAPI(
    title="RinSathi ACLO API",
    description=(
        "Autonomous Credit and Lending Orchestrator — "
        "5-agent AI pipeline for rural Nepal microfinance credit assessment. "
        "Stack: FastAPI, PostgreSQL (Supabase), PaddleOCR, XGBoost, SHAP."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware — allows browser fetch() calls from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules namespaces under /api/v1 cleanly
app.include_router(documents.router, prefix="/api/v1")
app.include_router(income.router,    prefix="/api/v1")
app.include_router(loan.router,      prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(mock_gov_router, prefix="/api/v1")


# ── FRONTEND CONTROLLERS ───────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root(request: Request):
    # Serves login page at http://localhost:8000/
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/apply", response_class=HTMLResponse, include_in_schema=False)
async def get_application_page(request: Request):
    return templates.TemplateResponse(request=request, name="apply.html")

@app.get("/dashboard", response_class=HTMLResponse, tags=["Frontend UI"])
async def read_dashboard(request: Request):
    """
    Renders the beautiful, multi-agent underwriting dashboard 
    directly from frontend/templates/dashboard.html
    """
    template_path = os.path.join("frontend", "templates", "dashboard.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


# ── CORE BACKEND & HEALTH CHECKS ───────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    from utils.ocr import OCR_AVAILABLE
    return {
        "status":   "ok",
        "version":  "1.0.0",
        "ocr_mode": "paddleocr" if OCR_AVAILABLE else "mock",
        "database": "supabase",
    }

# Initialize the ScoreAgent ONCE at the application/global level (Startup rule)
score_agent_instance = ScoreAgent()

@app.post("/api/v1/income/analyze", tags=["Income Analysis Core"])
async def analyze_income_and_score(request_data: dict):
    """
    This live API route executes both the Income parsing pipeline (Sprint 2a)
    and passes data directly to the ML Score Agent pipeline (Sprint 2b).
    """
    try:
        from agents.shared_state import SharedState
        snapshot_state = SharedState()
         
        snapshot_state.loan_amount_npr = float(request_data.get("loan_amount_npr", 250000))
        snapshot_state.monthly_income_npr = float(request_data.get("monthly_income_npr", 45666.67))
        snapshot_state.income_confidence = float(request_data.get("income_confidence", 0.644))
        snapshot_state.doc_confidence = float(request_data.get("doc_confidence", 0.85))

        print("FastAPI Controller: Invoking ScoreAgent machine learning pipeline...")
        score_metrics = await score_agent_instance.run(snapshot_state)
        
        return {
            "status": "PIPELINE_SUCCESS",
            "income_summary": {
                "mean_monthly_npr": snapshot_state.monthly_income_npr,
                "data_reliability_score": snapshot_state.income_confidence
            },
            "credit_score_summary": {
                "credit_score": snapshot_state.credit_score,
                "probability_of_repayment": snapshot_state.credit_score,
                "score_data_confidence": getattr(snapshot_state, "score_confidence", 1.0)
            },
            "explainable_ai_narratives": getattr(snapshot_state, "shap_explanations", [])
        }

    except Exception as general_error:
        print(f"FastAPI Controller: Critical exception caught during execution: {str(general_error)}")
        return {"status": "PIPELINE_ERROR", "detail": str(general_error)}