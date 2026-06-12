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
