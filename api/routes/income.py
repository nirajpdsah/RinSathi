# api/routes/income.py
# FastAPI route for the Income Agent endpoint.
# Accepts income data from up to three sources, runs the Income Agent pipeline,
# returns a structured MonthlyIncomeEstimate with confidence scoring.

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid
import time

from agents.shared_state  import SharedState
from agents.income_agent  import IncomeAgent
from utils.income_parsers import (
    generate_mock_esewa_data,
    generate_mock_remittance_data,
    generate_mock_coop_data,
)

router = APIRouter()   # Router registered in main.py with prefix /api/v1
agent  = IncomeAgent() # Instantiate once — not per-request


# ── Request schema ─────────────────────────────────────────────────────────────
class IncomeAnalyzeRequest(BaseModel):
    applicant_id:    uuid.UUID         # Links to an existing applicant
    esewa_data:      Optional[dict] = None   # eSewa/Khalti transaction JSON
    remittance_data: Optional[dict] = None   # Remittance records JSON
    coop_data:       Optional[dict] = None   # Cooperative ledger JSON
    use_mock_data:   bool           = False  # True = generate realistic mock data (for demo)


# ── Response schema ────────────────────────────────────────────────────────────
class IncomeAnalyzeResponse(BaseModel):
    applicant_id:      uuid.UUID
    mean_monthly_npr:  float       # Estimated monthly income in raw NPR
    std_dev_npr:       float       # Standard deviation — measure of income stability
    confidence:        float       # 0.0-1.0 overall confidence in this estimate
    months_of_data:    int         # How many months of data were provided
    low_confidence:    bool        # True if data quality is insufficient
    sources:           list[str]   # Which sources contributed to this estimate
    source_count:      int         # Number of distinct income sources
    processing_time_ms:int         # How long analysis took


@router.post(
    "/income/analyze",
    response_model=IncomeAnalyzeResponse,
    summary="Analyse applicant income signals",
    description=(
        "Accepts income data from eSewa, remittance records, and cooperative ledger. "
        "Normalises all signals into a MonthlyIncomeEstimate with confidence scoring. "
        "Cross-validates applicant name against Document Agent output for fraud detection. "
        "Set use_mock_data=true to generate realistic test data without real records."
    ),
    tags=["Income Agent"],
)
async def analyze_income(req: IncomeAnalyzeRequest):

    # ── Step 1: Handle mock data mode ─────────────────────────────────────────
    # use_mock_data=True generates realistic Nepali income data for demos
    # This is how we test the endpoint without real eSewa API access
    esewa_data      = req.esewa_data
    remittance_data = req.remittance_data
    coop_data       = req.coop_data

    if req.use_mock_data:
        esewa_data      = generate_mock_esewa_data()
        remittance_data = generate_mock_remittance_data()
        coop_data       = generate_mock_coop_data()

    # ── Step 2: Validate at least one income source is provided ───────────────
    if not any([esewa_data, remittance_data, coop_data]):
        raise HTTPException(
            status_code=422,
            detail="At least one income source is required: esewa_data, remittance_data, or coop_data. "
                   "Set use_mock_data=true to generate test data."
        )

    # ── Step 3: Create SharedState for this request ───────────────────────────
    # In Sprint 2b we create a fresh state per request.
    # In Sprint 3 the full /loan/apply endpoint will carry state across all agents.
    state = SharedState(
        applicant_id    = req.applicant_id,
        loan_amount_npr = 0.0,      # Not known at income analysis stage
        sector          = "unknown" # Not known at income analysis stage
    )

   # -- Step 4: Parse signals and run normalization directly -----------------
    # We run parsers here (not just through agent) so we have the full estimate
    # dict available for the API response. The agent writes the summary to
    # SharedState; the route returns the complete breakdown to the caller.
    from utils.income_parsers import (
        parse_esewa, parse_remittance, parse_cooperative,
        normalize_to_monthly_estimate, check_name_consistency,
    )

    all_signals  = []
    income_names = []

    if esewa_data:
        sigs, name = parse_esewa(esewa_data)
        all_signals.extend(sigs)
        if name: income_names.append(name)

    if remittance_data:
        sigs, name = parse_remittance(remittance_data)
        all_signals.extend(sigs)
        if name: income_names.append(name)

    if coop_data:
        sigs, name = parse_cooperative(coop_data)
        all_signals.extend(sigs)
        if name: income_names.append(name)

    start_ms = time.perf_counter()
    estimate  = normalize_to_monthly_estimate(all_signals)
    elapsed_ms= int((time.perf_counter() - start_ms) * 1000)

    # Write summary fields to SharedState (used by Score Agent downstream)
    state.monthly_income_npr = estimate["mean_monthly_npr"]
    state.income_confidence  = estimate["confidence"]
    state.income_sources     = estimate["sources"]

    # -- Step 5: Build complete response from full estimate dict --------------
    return IncomeAnalyzeResponse(
        applicant_id      = state.applicant_id,
        mean_monthly_npr  = estimate["mean_monthly_npr"], 
        std_dev_npr       = estimate["std_dev_npr"],
        confidence        = estimate["confidence"],
        months_of_data    = estimate["months_of_data"],
        low_confidence    = estimate["low_confidence"],
        sources           = estimate["sources"],
        source_count      = estimate["source_count"],
        processing_time_ms= elapsed_ms,
    )

@router.get(
    "/income/mock-data",
    summary="Generate mock income data for testing",
    description="Returns realistic mock eSewa, remittance, and cooperative data. "
                "Use this to understand the expected input format for /income/analyze.",
    tags=["Income Agent"],
)
async def get_mock_income_data():
    # Returns sample data so you can see exactly what format the endpoint expects.
    # Paste this output into the esewa_data/remittance_data/coop_data fields of
    # the /income/analyze endpoint to test without real data.
    return {
        "sample_esewa_data":      generate_mock_esewa_data(),
        "sample_remittance_data": generate_mock_remittance_data(),
        "sample_coop_data":       generate_mock_coop_data(),
        "usage_note": (
            "Copy any of these samples into the corresponding field of POST /income/analyze. "
            "Or simply set use_mock_data=true in the request body."
        ),
    }
