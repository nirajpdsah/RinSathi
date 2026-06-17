# agents/decision_agent.py
# Decision Agent: fifth and final agent in the ACLO pipeline.
# Reads the complete SharedState and issues one of three verdicts:
#   Approve — fully automated approval
#   Reject  — fully automated rejection
#   Refer   — route to human loan officer for manual review
#
# PRIORITY ORDER IS STRICT. Do not reorder these checks.
# Compliance always overrides score. Missing data always routes to Refer.

from agents.shared_state import SharedState   # Central data contract
from config import get_settings               # Score thresholds from config

settings = get_settings()


class DecisionAgent:
    """
    Issues the final credit decision for a loan application.

    Reads from SharedState:
        compliance_flags  — any NRB violations (overrides everything)
        credit_score      — XGBoost repayment probability (0.0-1.0)
        manual_review_required — Document Agent quality flag
        monthly_income_npr — used in decision_reason text
        loan_amount_npr   — used in decision_reason text

    Writes to SharedState:
        final_decision   — "Approve" | "Reject" | "Refer"
        decision_reason  — human-readable explanation for the loan officer

    Defence note:
    This 3-verdict design is intentional. Banking regulators (NRB) require
    human oversight for edge cases. A binary Approve/Reject system would be
    a regulatory violation for ambiguous cases. The Refer path is the
    Human-in-the-Loop mechanism that satisfies NRB audit requirements.
    """

    async def run(self, state: SharedState) -> SharedState:
        try:
            # ── PRIORITY 1: Compliance flags override EVERYTHING ───────────────
            # Even a perfect credit score cannot override an NRB rule violation.
            # This is the most important rule in the entire pipeline.
            if state.compliance_flags:
                # Build a readable summary of which rules were violated
                flag_descriptions = {
                    "KYC_INCOMPLETE":        "Identity document quality below KYC threshold",
                    "INCOME_UNVERIFIABLE":   "Income data insufficient for reliable assessment",
                    "LOAN_TO_ASSET_BREACH":  "Loan amount exceeds NRB 75% loan-to-asset limit",
                    "SECTOR_EXPOSURE_LIMIT": "Agricultural loan amount exceeds NRB sector cap",
                    "AML_FLAG":              "Income pattern flagged for AML review",
                    "NO_INCOME_SIGNALS":     "No income data provided for non-trivial loan",
                    "SYSTEM_ERROR":          "Pipeline error — manual verification required",
                }
                # Build reason string from all flags found
                reasons = [
                    flag_descriptions.get(flag, flag)   # Use description or raw flag code
                    for flag in state.compliance_flags
                ]
                state.final_decision  = "Refer"
                state.decision_reason = (
                    f"Referred for manual review. "
                    f"Compliance flags: {'; '.join(reasons)}."
                )
                return state   # Stop here — no further checks needed

            # ── PRIORITY 2: Missing credit score → cannot auto-decide ──────────
            # If Score Agent failed or returned None, we have no basis for
            # an automated decision. Route to human review.
            if state.credit_score is None:
                state.final_decision  = "Refer"
                state.decision_reason = (
                    "Referred: credit score could not be calculated. "
                    "Manual assessment required."
                )
                return state

            # ── PRIORITY 3: Score-based decision ──────────────────────────────
            # APPROVE_THRESHOLD = 0.65 from config (credit_score >= 0.65 → Approve)
            # REFER_THRESHOLD   = 0.40 from config (credit_score >= 0.40 → Refer)
            # Below REFER_THRESHOLD → Reject
            score   = state.credit_score
            income  = state.monthly_income_npr or 0.0
            loan    = state.loan_amount_npr    or 0.0

            if score >= settings.APPROVE_THRESHOLD:
                state.final_decision = "Recommend"
                state.decision_reason = (
                    f"Credit rating is {score * 100:.1f}%. The applicant is in a good position "
                    f"for this loan based on verified monthly income of NPR {income:,.0f} "
                    f"against a requested amount of NPR {loan:,.0f}. Final confirmation must "
                    f"come from the loan officer."
                )
            elif score < settings.REFER_THRESHOLD:
                state.final_decision = "Reject"
                state.decision_reason = (
                    f"Rejected. Credit rating is {score * 100:.1f}%, below the minimum "
                    f"acceptable threshold of {settings.REFER_THRESHOLD * 100:.0f}%."
                )
            else:
                state.final_decision = "Refer"
                state.decision_reason = (
                    f"Credit rating is {score * 100:.1f}%. The case needs loan officer "
                    f"review before any approval decision."
                )

        except Exception:
            # Safety net — unknown error → route to human, never auto-approve
            state.final_decision  = "Refer"
            state.decision_reason = "System error during decision processing. Manual review required."

        return state   # Always return state — never raise
