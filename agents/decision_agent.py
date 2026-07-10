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
        manual_review_required — identity verification quality flag
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
            if state.compliance_flags:
                flag_descriptions = {
                    "KYC_INCOMPLETE":        "the identity document is not clear enough to verify automatically",
                    "INCOME_UNVERIFIABLE":   "the income records are not strong enough for an automatic decision",
                    "LOAN_TO_ASSET_BREACH":  "the requested loan is too high compared with the estimated asset value",
                    "SECTOR_EXPOSURE_LIMIT": "the requested agriculture loan is above the current sector limit",
                    "AML_FLAG":              "the income amount is unusually high and needs a standard financial safety review",
                    "NO_INCOME_SIGNALS":     "no usable income record was found for this loan request",
                    "NAME_MISMATCH":         "the name on the cashflow record does not match the identity document",
                    "SYSTEM_ERROR":          "Pipeline error — manual verification required",
                    "CIB_BLACKLISTED":            "the applicant is formally blacklisted with Nepal's Credit Information Bureau (CIB) for a prior serious default",
                    "SEVERE_DELINQUENCY_HISTORY": "the applicant has a history of severe payment delinquency (90+ days past due) with a prior lender",
                }
                reasons = [
                    flag_descriptions.get(flag, flag)
                    for flag in state.compliance_flags
                ]
                hard_reject_flags = {
                    "AML_FLAG",
                    "NO_INCOME_SIGNALS",
                    "LOAN_TO_ASSET_BREACH",
                    "NAME_MISMATCH",
                    "CIB_BLACKLISTED",
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
                return state

            # ── PRIORITY 2: Missing credit score → cannot auto-decide ──────────
            if state.credit_score is None:
                state.final_decision  = "Refer"
                state.decision_reason = (
                    "This application needs manual review because the repayment rating could "
                    "not be calculated from the available information. A loan officer should "
                    "check the documents and income records."
                )
                return state

            # ── PRIORITY 3: Weighted scorecard decision ────────────────────────
            # Auditable layer. ML credit_score is 35%, asset coverage 20%,
            # income stability 15%, credit history 15%, compliance 15%.
            score          = state.credit_score
            income         = state.monthly_income_npr or 0.0
            loan           = state.loan_amount_npr    or 0.0
            land_value     = state.total_land_value_npr or 0.0

            asset_coverage_ratio = (
                min(land_value / loan, 1.0) if loan > 0 else 0.0
            )
            income_stability_score = state.income_confidence or 0.0
            compliance_score = 1.0

            # ── Credit history score — from CIB check via IdentityAgent ────────
            if state.is_blacklisted:
                credit_history_score = 0.0
            elif state.max_dpd_bucket == "dpd_90_plus":
                credit_history_score = 0.3
            elif state.max_dpd_bucket == "dpd_60":
                credit_history_score = 0.6
            elif state.max_dpd_bucket == "dpd_30":
                credit_history_score = 0.8
            else:
                credit_history_score = 1.0

            qualification_score = (
                (score                   * 0.35) +
                (asset_coverage_ratio    * 0.20) +
                (income_stability_score  * 0.15) +
                (credit_history_score    * 0.15) +
                (compliance_score        * 0.15)
            ) * 100

            state.qualification_score = round(qualification_score, 1)

            APPROVE_LINE = settings.APPROVE_THRESHOLD * 100
            REFER_LINE   = settings.REFER_THRESHOLD * 100

            if qualification_score >= APPROVE_LINE:
                state.final_decision = "Recommend"
                state.decision_reason = (
                    f"Qualification score is {qualification_score:.1f}/100 "
                    f"(ML repayment probability {score*100:.1f}% weighted 35%, "
                    f"asset coverage {asset_coverage_ratio*100:.0f}% weighted 20%, "
                    f"income reliability {income_stability_score*100:.0f}% weighted 15%, "
                    f"credit history {credit_history_score*100:.0f}% weighted 15%, "
                    f"clean compliance record weighted 15%). Estimated monthly income "
                    f"NPR {income:,.0f} against requested loan NPR {loan:,.0f}. "
                    "This is a recommendation for the loan officer, not a final approval."
                )
            elif qualification_score < REFER_LINE:
                state.final_decision = "Reject"
                state.decision_reason = (
                    f"Qualification score is {qualification_score:.1f}/100, below the "
                    f"minimum required {REFER_LINE:.0f}/100. Stronger income verification "
                    "or additional collateral may improve a future assessment."
                )
            else:
                state.final_decision = "Refer"
                state.decision_reason = (
                    f"Qualification score is {qualification_score:.1f}/100, within the "
                    "manual review range. A loan officer should examine the supporting "
                    "documents before making a final decision."
                )

        except Exception:
            state.final_decision  = "Refer"
            state.decision_reason = "System error during decision processing. Manual review required."

        return state
