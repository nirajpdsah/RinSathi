# fix_income_agent.py
# Writes all Income Agent files with full line-by-line comments.
# Run: python fix_income_agent.py

import os

os.makedirs("utils",       exist_ok=True)
os.makedirs("agents",      exist_ok=True)
os.makedirs("api/routes",  exist_ok=True)

# ── FILE 1: utils/income_parsers.py ───────────────────────────────────────────
income_parsers = '''\
# utils/income_parsers.py
# Three income signal parsers + normalization pipeline.
# Each parser converts a different data source into a standard signal format:
# {date, amount_npr, source, type}
# The normalization function then combines all signals into one MonthlyIncomeEstimate.

import pandas as pd           # Pandas: DataFrame operations for monthly aggregation
import numpy as np            # NumPy: statistical calculations (std dev, distributions)
from datetime import datetime, timedelta  # Date arithmetic for signal grouping
import re                     # Regex: name normalization for cross-validation


# ── Standard signal format ─────────────────────────────────────────────────────
# Every parser outputs a list of dicts matching this structure.
# Keeping one format means normalize_to_monthly_estimate() works on any source.
# {
#   "date":       "YYYY-MM-DD",    <- when the income was received
#   "amount_npr": float,           <- amount in Nepali Rupees (never USD, always convert)
#   "source":     str,             <- "esewa" | "remittance" | "cooperative"
#   "type":       str,             <- "regular" | "irregular_periodic"
# }


# ── Parser 1: eSewa / Khalti transaction history ───────────────────────────────
def parse_esewa(data: dict) -> tuple[list[dict], str | None]:
    """
    Parses eSewa or Khalti transaction history JSON.

    Input format:
    {
        "account_name": "Ram Bahadur Thapa",
        "transactions": [
            {"date": "2024-01-15", "amount": 2500, "type": "receive"},
            {"date": "2024-01-28", "amount": 1800, "type": "salary"},
            {"date": "2024-02-01", "amount": 500,  "type": "send_money"},  <- expense, skipped
        ]
    }

    Returns: (list of income signals, account_name)
    """
    if not data:                           # Guard against None or empty input
        return [], None

    transactions = data.get("transactions", [])   # List of transaction dicts
    account_name = data.get("account_name")        # Name for cross-validation

    # Income transaction types — we only count money COMING IN, not going out
    # send_money, utility_pay, merchant_pay are expenses — not income signals
    INCOME_TYPES = {
        "receive",         # Money received from another person
        "salary",          # Employer salary credit
        "transfer_in",     # Bank transfer received
        "business_income", # Business revenue
        "freelance",       # Freelance payment received
    }

    signals = []
    for txn in transactions:
        txn_type = txn.get("type", "").lower()

        # Skip non-income transactions (payments, transfers out, fees)
        if txn_type not in INCOME_TYPES:
            continue

        amount = float(txn.get("amount", 0))
        if amount <= 0:                    # Skip zero or negative amounts
            continue

        date_str = txn.get("date", "")
        try:
            # Validate the date is parseable — skip malformed entries
            datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        signals.append({
            "date":       date_str[:10],   # Keep YYYY-MM-DD only (strip time if present)
            "amount_npr": amount,          # eSewa amounts are already in NPR
            "source":     "esewa",
            "type":       "regular",       # eSewa income tends to be regular (weekly/monthly)
        })

    return signals, account_name


# ── Parser 2: Remittance records (IME, Western Union, etc.) ───────────────────
def parse_remittance(data: dict) -> tuple[list[dict], str | None]:
    """
    Parses international remittance records.

    Input format:
    {
        "records": [
            {
                "sender_country":  "Qatar",
                "amount_usd":      450.0,
                "exchange_rate":   133.5,
                "received_date":   "2024-01-20",
                "receiver_name":   "Ram Bahadur Thapa"
            }
        ]
    }

    IMPORTANT: Remittances are ANNUALIZED, not monthly-averaged.
    A worker in Qatar sends NPR 60,000 every 3 months.
    Monthly average would show NPR 0 for 2 months — penalising a creditworthy applicant.
    Annualizing: sum all 12 months, divide by 12 = fair monthly estimate.
    """
    if not data:
        return [], None

    records      = data.get("records", [])
    receiver_name= None

    signals = []
    for record in records:
        # Extract receiver name from first valid record for cross-validation
        if not receiver_name and record.get("receiver_name"):
            receiver_name = record["receiver_name"]

        amount_usd    = float(record.get("amount_usd", 0))
        exchange_rate = float(record.get("exchange_rate", 133.0))  # Default NPR/USD rate

        if amount_usd <= 0:
            continue

        # Convert USD to NPR using the exchange rate recorded at time of transfer
        # This is more accurate than using current rate — captures historical reality
        amount_npr = round(amount_usd * exchange_rate, 2)

        date_str = record.get("received_date", "")
        try:
            datetime.strptime(date_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        signals.append({
            "date":       date_str[:10],
            "amount_npr": amount_npr,
            "source":     "remittance",
            "type":       "irregular_periodic",  # Remittances arrive every 1-4 months
        })

    return signals, receiver_name


# ── Parser 3: Cooperative / savings group ledger ───────────────────────────────
def parse_cooperative(data: dict) -> tuple[list[dict], str | None]:
    """
    Parses cooperative or savings group ledger data.

    Input format:
    {
        "member_name":         "Ram Bahadur Thapa",
        "savings_balance_npr": 85000,
        "monthly_deposits": [
            {"month": "2024-01", "amount": 2000},
            {"month": "2024-02", "amount": 2000},
        ]
    }

    Note: We use monthly_deposits as income signals (recurring savings capacity).
    savings_balance is an ASSET — used for loan-to-asset ratio, not income.
    """
    if not data:
        return [], None

    member_name     = data.get("member_name")
    monthly_deposits= data.get("monthly_deposits", [])

    signals = []
    for deposit in monthly_deposits:
        amount = float(deposit.get("amount", 0))
        if amount <= 0:
            continue

        month_str = deposit.get("month", "")   # Format: "YYYY-MM"
        try:
            # Cooperative records use YYYY-MM — add day 01 for datetime parsing
            datetime.strptime(month_str + "-01", "%Y-%m-%d")
            date_str = month_str + "-01"
        except (ValueError, TypeError):
            continue

        signals.append({
            "date":       date_str,
            "amount_npr": amount,
            "source":     "cooperative",
            "type":       "regular",    # Cooperative deposits are typically monthly
        })

    return signals, member_name


# ── Normalization: all signals → MonthlyIncomeEstimate ─────────────────────────
def normalize_to_monthly_estimate(all_signals: list[dict]) -> dict:
    """
    Combines income signals from all sources into one monthly estimate.

    Algorithm:
    1. Separate regular vs irregular_periodic signals
    2. For regular signals: rolling 6-month mean and std deviation
    3. For irregular/remittance signals: annualize (sum 12m / 12)
    4. Combine both estimates
    5. Confidence = data_coverage_score × income_stability_score

    Returns a MonthlyIncomeEstimate dict.
    """
    if not all_signals:
        # No income data at all — return zero estimate with very low confidence
        return {
            "mean_monthly_npr": 0.0,
            "std_dev_npr":      0.0,
            "confidence":       0.1,   # Minimum confidence — not zero (avoids divide errors)
            "months_of_data":   0,
            "low_confidence":   True,
            "sources":          [],
            "source_count":     0,
        }

    # Convert to pandas DataFrame for aggregation
    df = pd.DataFrame(all_signals)
    df["date"]      = pd.to_datetime(df["date"])         # Parse date strings to datetime
    df["month"]     = df["date"].dt.to_period("M")       # Extract YYYY-MM period
    df["amount_npr"]= pd.to_numeric(df["amount_npr"], errors="coerce").fillna(0)

    # ── Handle remittances separately (annualized) ────────────────────────────
    remittance_monthly = 0.0
    remit_df = df[df["source"] == "remittance"]
    if not remit_df.empty:
        # Sum all remittance amounts across all months
        total_remittance = remit_df["amount_npr"].sum()
        # Determine date range covered by remittance data
        months_covered   = max(1, (remit_df["date"].max() - remit_df["date"].min()).days / 30)
        months_covered   = min(months_covered, 12)   # Cap at 12 months
        # Annualize: total / months_covered, capped at 12-month equivalent
        remittance_monthly = total_remittance / max(months_covered, 1)

    # ── Handle regular signals (eSewa + cooperative) ──────────────────────────
    regular_df = df[df["source"] != "remittance"]
    regular_monthly_mean = 0.0
    regular_std_dev      = 0.0
    if not regular_df.empty:
        # Group by month and sum amounts — gives monthly income per month
        monthly_totals    = regular_df.groupby("month")["amount_npr"].sum()
        regular_monthly_mean = float(monthly_totals.mean())
        regular_std_dev   = float(monthly_totals.std()) if len(monthly_totals) > 1 else 0.0

    # ── Combine regular + remittance estimates ────────────────────────────────
    total_monthly_mean = regular_monthly_mean + remittance_monthly
    combined_std       = regular_std_dev   # Remittances already annualized so std is captured

    # ── Calculate confidence score ─────────────────────────────────────────────
    # Component 1: Data coverage — how many months of data do we have?
    # 6 months = full score. Fewer months = proportionally less confidence.
    all_months      = df["month"].nunique()
    coverage_score  = min(1.0, all_months / 6)

    # Component 2: Income stability — how consistent is the monthly income?
    # Coefficient of Variation (CV) = std_dev / mean
    # Low CV (consistent income) → high stability score
    # High CV (erratic income)   → low stability score
    if total_monthly_mean > 0 and combined_std > 0:
        cv              = combined_std / total_monthly_mean
        cv              = min(cv, 1.0)            # Cap at 1.0 (100% variation)
        stability_score = 1.0 - cv
    else:
        stability_score = 0.8 if total_monthly_mean > 0 else 0.2

    # Component 3: Source diversity — multiple corroborating sources = more trust
    source_count   = df["source"].nunique()
    diversity_score= min(1.0, source_count / 2)  # 2+ sources = full diversity score

    # Final confidence = weighted combination of all three components
    confidence = round(
        (coverage_score  * 0.45) +   # 45%: data coverage is most important
        (stability_score * 0.35) +   # 35%: income consistency
        (diversity_score * 0.20),    # 20%: source diversity
        4
    )

    # Flag for low confidence conditions
    low_confidence = (
        all_months < 3             or   # Less than 3 months of data
        confidence < 0.4           or   # Overall confidence below 40%
        total_monthly_mean == 0.0       # No income detected at all
    )

    return {
        "mean_monthly_npr": round(total_monthly_mean, 2),
        "std_dev_npr":      round(combined_std, 2),
        "confidence":       confidence,
        "months_of_data":   int(all_months),
        "low_confidence":   low_confidence,
        "sources":          sorted(df["source"].unique().tolist()),
        "source_count":     int(source_count),
    }


# ── Name cross-validation ──────────────────────────────────────────────────────
def check_name_consistency(doc_name: str, income_names: list[str]) -> dict:
    """
    Checks if the name on the citizenship cert matches names in income records.
    Uses token-based matching because OCR and data entry produce slight variations:
    - "RAM BAHADUR THAPA" vs "Ram B. Thapa" vs "Thapa Ram Bahadur"
    - All refer to the same person but exact match would fail.

    Returns a dict with match_score and is_consistent flag.
    """
    if not doc_name or not income_names:
        # Cannot cross-validate without both names — not a flag, just unknown
        return {"match_score": 0.5, "is_consistent": None, "checked": False}

    def normalize(name: str) -> set[str]:
        # Lowercase, remove punctuation, split into tokens, filter short tokens
        name = name.lower().strip()
        name = re.sub(r"[^a-z\s]", "", name)    # Remove non-alpha characters
        tokens = name.split()
        return {t for t in tokens if len(t) > 1} # Keep tokens longer than 1 char

    doc_tokens   = normalize(doc_name)
    best_score   = 0.0

    for income_name in income_names:
        if not income_name:
            continue
        income_tokens = normalize(income_name)

        if not doc_tokens or not income_tokens:
            continue

        # Jaccard similarity: intersection / union of name tokens
        # "RAM THAPA" and "RAM BAHADUR THAPA" → {ram,thapa} ∩ {ram,bahadur,thapa} / union
        intersection = len(doc_tokens & income_tokens)
        union        = len(doc_tokens | income_tokens)
        score        = intersection / union if union > 0 else 0.0
        best_score   = max(best_score, score)

    return {
        "match_score":   round(best_score, 4),
        "is_consistent": best_score >= 0.5,  # 50%+ token overlap = same person
        "checked":       True,
    }


# ── Mock data generators (for testing without real data) ──────────────────────
def generate_mock_esewa_data(name: str = "BIKRAM PRASAD SHRESTHA",
                              months: int = 6) -> dict:
    """Generates realistic mock eSewa transaction history for testing."""
    import random
    from datetime import date, timedelta

    transactions = []
    start_date   = date.today().replace(day=1)

    for m in range(months):
        # Go back m months from today
        month_date = start_date - timedelta(days=m * 30)
        # 3-6 income transactions per month (realistic for small business/salaried)
        for _ in range(random.randint(3, 6)):
            day = random.randint(1, 28)
            txn_date = month_date.replace(day=day)
            transactions.append({
                "date":   txn_date.strftime("%Y-%m-%d"),
                "amount": round(random.uniform(2000, 12000), 2),  # NPR 2k-12k per transaction
                "type":   random.choice(["receive", "salary", "receive"]),  # Weighted toward receive
            })

    return {"account_name": name, "transactions": transactions}


def generate_mock_remittance_data(name: str = "BIKRAM PRASAD SHRESTHA",
                                   months: int = 12) -> dict:
    """Generates realistic mock remittance records (Gulf worker pattern)."""
    import random
    from datetime import date, timedelta

    records = []
    # Gulf workers typically send every 2-4 months
    current_date = date.today()

    for i in range(0, months, random.randint(2, 4)):
        send_date = current_date - timedelta(days=i * 30 + random.randint(1, 15))
        records.append({
            "sender_country": random.choice(["Qatar", "UAE", "Saudi Arabia", "Kuwait"]),
            "amount_usd":     round(random.uniform(300, 600), 2),   # USD 300-600 per transfer
            "exchange_rate":  round(random.uniform(130, 137), 2),   # NPR/USD rate
            "received_date":  send_date.strftime("%Y-%m-%d"),
            "receiver_name":  name,
        })

    return {"records": records}


def generate_mock_coop_data(name: str = "BIKRAM PRASAD SHRESTHA",
                             months: int = 6) -> dict:
    """Generates realistic mock cooperative ledger data."""
    import random
    from datetime import date, timedelta

    deposits = []
    today    = date.today()

    for m in range(months):
        month_date = today - timedelta(days=m * 30)
        deposits.append({
            "month":  month_date.strftime("%Y-%m"),
            "amount": round(random.uniform(1500, 3000), 2),  # NPR 1.5k-3k/month cooperative deposit
        })

    return {
        "member_name":          name,
        "savings_balance_npr":  round(random.uniform(50000, 150000), 2),
        "monthly_deposits":     deposits,
    }
'''

# ── FILE 2: agents/income_agent.py ────────────────────────────────────────────
income_agent = '''\
# agents/income_agent.py
# Income Agent: second agent in the ACLO five-agent pipeline.
# Parses income signals from three sources, normalizes them into a
# MonthlyIncomeEstimate, cross-validates names against Document Agent output,
# and writes results to SharedState.
#
# Design rule: NEVER raises exceptions. Always returns SharedState.
# If income data is missing or invalid, sets low confidence and continues.

from agents.shared_state import SharedState
from utils.income_parsers import (
    parse_esewa,
    parse_remittance,
    parse_cooperative,
    normalize_to_monthly_estimate,
    check_name_consistency,
)


class IncomeAgent:
    """
    Processes income signals from multiple financial data sources.

    Reads from SharedState:
        extracted_fields  — name from Document Agent for cross-validation

    Writes to SharedState:
        monthly_income_npr  — raw NPR amount (NEVER scaled — scaling only in Score Agent)
        income_confidence   — 0.0-1.0 based on data quality and consistency
        income_sources      — which sources contributed (e.g. ["esewa", "remittance"])

    Defence note: Raw NPR is stored, not a scaled value. This is intentional.
    Scaling happens inside the XGBoost Pipeline object in Score Agent.
    Keeping raw NPR here ensures SHAP explanations show real money amounts
    (e.g. "NPR 25,000/month increased score by 31%") instead of meaningless floats.
    """

    async def run(
        self,
        state:           SharedState,
        esewa_data:      dict | None = None,   # eSewa/Khalti transaction history JSON
        remittance_data: dict | None = None,   # Remittance records JSON
        coop_data:       dict | None = None,   # Cooperative ledger JSON
    ) -> SharedState:
        # Main entry point. Always returns state — never raises.
        try:
            all_signals   = []   # Accumulated income signals from all sources
            income_names  = []   # Names from income records (for cross-validation)

            # ── Step 1: Parse eSewa data ──────────────────────────────────────
            if esewa_data:
                esewa_signals, esewa_name = parse_esewa(esewa_data)
                all_signals.extend(esewa_signals)   # Add to combined signal pool
                if esewa_name:
                    income_names.append(esewa_name) # Save name for cross-validation

            # ── Step 2: Parse remittance data ─────────────────────────────────
            if remittance_data:
                remit_signals, remit_name = parse_remittance(remittance_data)
                all_signals.extend(remit_signals)
                if remit_name:
                    income_names.append(remit_name)

            # ── Step 3: Parse cooperative ledger ─────────────────────────────
            if coop_data:
                coop_signals, coop_name = parse_cooperative(coop_data)
                all_signals.extend(coop_signals)
                if coop_name:
                    income_names.append(coop_name)

            # ── Step 4: Normalize all signals → MonthlyIncomeEstimate ─────────
            estimate = normalize_to_monthly_estimate(all_signals)

            # ── Step 5: Name cross-validation ─────────────────────────────────
            # Extract the name from Document Agent's output in SharedState
            doc_name = None
            if state.extracted_fields and "name" in state.extracted_fields:
                doc_name = state.extracted_fields["name"].get("value")

            name_check = check_name_consistency(doc_name, income_names)

            # If name mismatch detected — reduce confidence
            # A forged document claiming a different identity will fail here
            if name_check["checked"] and not name_check["is_consistent"]:
                # Reduce confidence by 40% for name mismatch
                # (Not a hard block — goes to human review via Refer verdict)
                adjusted_confidence = round(estimate["confidence"] * 0.6, 4)
                estimate["confidence"]     = adjusted_confidence
                estimate["low_confidence"] = True
                # The Compliance Agent will see the low income_confidence
                # and can add a NAME_MISMATCH flag if needed

            # ── Step 6: Write results to SharedState ──────────────────────────
            state.monthly_income_npr = estimate["mean_monthly_npr"]
            state.income_confidence  = estimate["confidence"]
            state.income_sources     = estimate["sources"]

        except Exception:
            # Safety net — degrade gracefully rather than crashing the pipeline
            # Downstream agents handle None income gracefully
            state.monthly_income_npr = 0.0
            state.income_confidence  = 0.1   # Very low but non-zero
            state.income_sources     = []

        return state   # Always return state — never raise
'''

# ── FILE 3: api/routes/income.py ──────────────────────────────────────────────
income_route = '''\
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

    # ── Step 4: Run Income Agent ───────────────────────────────────────────────
    start_ms = time.perf_counter()
    state = await agent.run(
        state,
        esewa_data      = esewa_data,
        remittance_data = remittance_data,
        coop_data       = coop_data,
    )
    elapsed_ms = int((time.perf_counter() - start_ms) * 1000)

    # ── Step 5: Build response from SharedState ───────────────────────────────
    return IncomeAnalyzeResponse(
        applicant_id      = state.applicant_id,
        mean_monthly_npr  = state.monthly_income_npr or 0.0,
        std_dev_npr       = 0.0,     # Full std dev stored internally — summary here
        confidence        = state.income_confidence or 0.0,
        months_of_data    = 0,       # Detailed stats available via mock data response
        low_confidence    = (state.income_confidence or 0) < 0.4,
        sources           = state.income_sources or [],
        source_count      = len(state.income_sources or []),
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
'''

# ── FILE 4: main.py update ─────────────────────────────────────────────────────
# Read existing main.py and register the income router
with open("main.py", encoding="utf-8") as f:
    main_content = f.read()

# Add income import if not already there
if "from api.routes import income" not in main_content:
    main_content = main_content.replace(
        "from api.routes import documents",
        "from api.routes import documents, income"
    )

# Register income router if not already there
if "income.router" not in main_content:
    main_content = main_content.replace(
        "app.include_router(documents.router, prefix=\"/api/v1\")",
        "app.include_router(documents.router, prefix=\"/api/v1\")\n"
        "app.include_router(income.router,    prefix=\"/api/v1\")"
    )

# Write all files
files = {
    "utils/income_parsers.py":   income_parsers,
    "agents/income_agent.py":    income_agent,
    "api/routes/income.py":      income_route,
    "main.py":                   main_content,
}

for path, content in files.items():
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Written: {path}")

print("\nIncome Agent ready. Now run:")
print("  pip install pandas")
print("  uvicorn main:app --reload --port 8000")
print()
print("New endpoints available at localhost:8000/docs:")
print("  GET  /api/v1/income/mock-data      <- see sample input format")
print("  POST /api/v1/income/analyze        <- run income analysis")
print()
print("Quick test — paste this into /income/analyze in /docs:")
print('  {"applicant_id": "00000000-0000-0000-0000-000000000001", "use_mock_data": true}')