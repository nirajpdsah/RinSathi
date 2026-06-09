# ── main.py ───────────────────────────────────────────────────────────────────
# FastAPI application entry point. This file:
# 1. Creates the FastAPI app with metadata (shown in /docs)
# 2. Registers all route modules (auth, documents, etc.)
# 3. Configures CORS (allows browser fetch() calls)
# 4. Handles startup/shutdown lifecycle events (DB tables, ML model loading)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware   # Allows browser to call our API
from fastapi.templating import Jinja2Templates       # Serves HTML files from /templates
from fastapi.staticfiles import StaticFiles          # Serves CSS/JS from /static
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from contextlib import asynccontextmanager           # For startup/shutdown lifecycle
from db.session import create_tables                 # Creates Supabase tables on startup
from api.routes import documents                     # Document Agent route
from config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ───────────────────────────────────────────────────────────────
    # Code here runs ONCE when the server starts (before any requests arrive)
    print("Starting ACLO API...")
    await create_tables()          # Creates all tables in Supabase if they don't exist yet
    # You'll see the tables appear in Supabase Table Editor after this runs
    print("Database tables ready (Supabase)")
    print("ACLO API running at http://localhost:8000")
    print("API docs at     http://localhost:8000/docs")

    yield   # Application runs here — control returns after server shuts down

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    print("ACLO API shutting down.")


app = FastAPI(
    title       = "ACLO API",
    description = (
        "Autonomous Credit & Lending Orchestrator — "
        "5-agent AI pipeline for rural Nepal microfinance credit assessment. "
        "Built with FastAPI, PostgreSQL (Supabase), XGBoost, PaddleOCR, and SHAP."
    ),
    version     = "1.0.0",
    lifespan    = lifespan,        # Attach our startup/shutdown manager
    docs_url    = "/docs",         # Swagger UI available at /docs
    redoc_url   = "/redoc",        # ReDoc alternative at /redoc
)

# CORS: allows the browser (on a different port) to call our API
# Without this, fetch() from login.html would be blocked by browser security
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],     # Allow all origins (restrict in production)
    allow_credentials = True,
    allow_methods     = ["*"],     # Allow GET, POST, PUT, DELETE etc.
    allow_headers     = ["*"],     # Allow Authorization, Content-Type etc.
)

# Register route modules — each module handles one group of endpoints
# prefix="/api/v1" namespaces everything: /api/v1/document/upload
app.include_router(documents.router, prefix="/api/v1")

# Serve frontend templates
templates = Jinja2Templates(directory="frontend/templates")

@app.get("/", include_in_schema=False)  # include_in_schema=False hides from /docs
async def serve_login(request: Request):
    # Serves the login page when someone visits http://localhost:8000/
    return templates.TemplateResponse("login.html", {"request": request})