# agents/compliance_agent.py
# Compliance Agent: fourth agent in the ACLO pipeline.
# Checks the applicant's data against NRB Unified Directives 2080.
# THIS IS NOT ML. It is a deterministic rule engine — pure Python conditions.
# All thresholds come from config.py, never hardcoded here.
#
# Design rule: NEVER raises exceptions. NEVER blocks the pipeline.
# On any rule violation, it appends a flag to compliance_flags and continues.
# The Decision Agent reads compliance_flags and acts on them.

from agents.shared_state import SharedState   # Central data contract
from config import get_settings               # All thresholds from .env

settings = get_settings()


class ComplianceAgent:
    """
    Checks applicant data against NRB regulatory requirements.

    Reads from SharedState:
        monthly_income_npr  — for loan-to-income ratio check
        income_confidence   — for KYC quality check
        doc_confidence      — for KYC document quality check
        manual_review_required — direct KYC flag from identity verification
        extracted_fields    — for loan_amount and sector
        loan_amount_npr     — the requested loan amount
        sector              — applicant's business sector

    Writes to SharedState:
        compliance_flags    — list of NRB violation codes found
                             Empty list = all checks passed = clean applicant

    Defence note: Compliance Agent has HIGHEST PRIORITY in the pipeline.
    If compliance_flags is non-empty, Decision Agent outputs Refer or Reject
    REGARDLESS of what the credit score says. This is a regulatory requirement —
    a clean credit score does not override an NRB compliance breach.
    """

    async def run(self, state: SharedState) -> SharedState:
        # Always returns state. Appends violation codes to compliance_flags.
        # Each check is independent — one failure does not stop other checks.
        try:
            state.compliance_flags = []   # Reset flags at start of compliance run

            # ── Check 1: KYC — Document quality ───────────────────────────────
            # If identity verification flagged manual review, identity confidence was too low.
            # NRB requires verified identity before any credit decision.
            if state.manual_review_required:
                state.compliance_flags.append("KYC_INCOMPLETE")
                # Note: this does NOT stop other checks. We continue to catch
                # ALL violations in one pass, not just the first one found.

            # ── Check 2: KYC — Income confidence ──────────────────────────────
            # Very low income confidence means we cannot verify the income claims.
            # Below 0.25 suggests either no data or highly unreliable data.
            income_conf = state.income_confidence or 0.0
            if income_conf < 0.25:
                state.compliance_flags.append("INCOME_UNVERIFIABLE")

            if state.name_mismatch_detected:
                state.compliance_flags.append("NAME_MISMATCH")

            # ── Check 3: Loan-to-asset ratio ──────────────────────────────────
            # NRB Unified Directive: loan cannot exceed 75% of asset value.
            # loan_to_asset = loan_amount / estimated_asset_value
            # We estimate asset value from income (simplified for Sprint 3;
            # full implementation uses land value from the identity verification flow).
            loan_amount    = state.loan_amount_npr or 0.0
            monthly_income = state.monthly_income_npr or 0.0

            if loan_amount > 0 and monthly_income > 0:
                # Simplified proxy: annual income × 10 as rough asset estimate
                # In production: replace with actual land value from Lalpurja
                estimated_assets = monthly_income * 12 * 10
                loan_to_asset    = loan_amount / estimated_assets

                if loan_to_asset > settings.MAX_LOAN_TO_ASSET:
                    # Loan amount exceeds NRB's 75% loan-to-asset limit
                    state.compliance_flags.append("LOAN_TO_ASSET_BREACH")

            # ── Check 4: Agricultural sector exposure limit ───────────────────
            # NRB caps agricultural sector lending to prevent over-concentration.
            # AGRI_SECTOR_LIMIT_NPR from config (default NPR 500,000).
            sector = (state.sector or "").lower()
            is_agricultural = any(
                keyword in sector
                for keyword in ["agriculture", "farming", "agri", "crop", "livestock"]
            )
            if is_agricultural and loan_amount > settings.AGRI_SECTOR_LIMIT_NPR:
                state.compliance_flags.append("SECTOR_EXPOSURE_LIMIT")

            # ── Check 5: AML — unusually large single income signal ────────────
            # Anti-Money Laundering: flag if any single signal suggests
            # an unusually large one-time cash deposit (structuring risk).
            # In production: check each individual transaction.
            # Here we use monthly income as a proxy for simplicity.
            if monthly_income > settings.AML_TXN_LIMIT_NPR:
                # Monthly income above NPR 1,000,000 — flag for review
                state.compliance_flags.append("AML_FLAG")

            # ── Check 6: Zero income with non-trivial loan request ─────────────
            # If Income Agent found no income signals and loan > NPR 10,000,
            # this is likely a data submission error or attempt to game the system.
            if monthly_income == 0.0 and loan_amount > 10_000:
                state.compliance_flags.append("NO_INCOME_SIGNALS")

        except Exception:
            # Safety net — if something breaks, flag for human review
            # rather than letting a potentially non-compliant application through.
            if "SYSTEM_ERROR" not in state.compliance_flags:
                state.compliance_flags.append("SYSTEM_ERROR")

        return state   # Always return state — never raise
