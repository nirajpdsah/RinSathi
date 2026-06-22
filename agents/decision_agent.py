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
                    "KYC_INCOMPLETE":        "the identity document is not clear enough to verify automatically",
                    "INCOME_UNVERIFIABLE":   "the income records are not strong enough for an automatic decision",
                    "LOAN_TO_ASSET_BREACH":  "the requested loan is too high compared with the estimated asset value",
                    "SECTOR_EXPOSURE_LIMIT": "the requested agriculture loan is above the current sector limit",
                    "AML_FLAG":              "the income amount is unusually high and needs a standard financial safety review",
                    "NO_INCOME_SIGNALS":     "no usable income record was found for this loan request",
                    "NAME_MISMATCH":         "the name on the cashflow record does not match the identity document",
                    "SYSTEM_ERROR":          "Pipeline error — manual verification required",
                }
                # Build reason string from all flags found
                reasons = [
                    flag_descriptions.get(flag, flag)   # Use description or raw flag code
                    for flag in state.compliance_flags
                ]
                hard_reject_flags = {
                    "AML_FLAG",
                    "NO_INCOME_SIGNALS",
                    "LOAN_TO_ASSET_BREACH",
                    "NAME_MISMATCH",
                }
                state.final_decision  = "Reject" if any(
                    flag in hard_reject_flags for flag in state.compliance_flags
                ) else "Refer"
                if state.final_decision == "Reject":
                    state.decision_reason = (
                        "This application has been rejected because "
                        f"{'; '.join(reasons)}. A loan officer should review the documents "
                        "and supporting records before the applicant reapplies or proceeds."
                    )
                else:
                    state.decision_reason = (
                        "This application needs manual review because "
                        f"{'; '.join(reasons)}. A loan officer can verify the details and "
                        "decide the next step."
                    )
                return state   # Stop here — no further checks needed

            # ── PRIORITY 2: Missing credit score → cannot auto-decide ──────────
            # If Score Agent failed or returned None, we have no basis for
            # an automated decision. Route to human review.
            if state.credit_score is None:
                state.final_decision  = "Refer"
                state.decision_reason = (
                    "This application needs manual review because the repayment rating could "
                    "not be calculated from the available information. A loan officer should "
                    "check the documents and income records."
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
                    f"The repayment rating is {score * 100:.1f}%. The applicant appears able "
                    f"to support this request, with estimated monthly income of NPR {income:,.0f} "
                    f"and a requested loan amount of NPR {loan:,.0f}. This is a recommendation "
                    "for the loan officer, not a final approval."
                )
            elif score < settings.REFER_THRESHOLD:
                state.final_decision = "Reject"
                state.decision_reason = (
                    f"This application has been rejected because the repayment "
                    f"rating is {score * 100:.1f}%, which is below the minimum required level "
                    f"of {settings.REFER_THRESHOLD * 100:.0f}%. Stronger or clearer income "
                    "records may improve a future assessment."
                )
            else:
                state.final_decision = "Refer"
                state.decision_reason = (
                    f"The repayment rating is {score * 100:.1f}%. This is close to the review "
                    "range, so a loan officer should look at the supporting documents before "
                    "making a final decision."
                )

        except Exception:
            # Safety net — unknown error → route to human, never auto-approve
            state.final_decision  = "Refer"
            state.decision_reason = "System error during decision processing. Manual review required."

        return state   # Always return state — never raise
