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
