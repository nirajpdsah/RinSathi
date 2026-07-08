# utils/shap_formatter.py
#
# Translates raw model feature contributions into plain-language sentences
# for loan officers and auditors.
#
# UPDATED to match the five real-world ratio features the retrained
# XGBoost model actually uses: loan_to_asset_ratio, loan_to_income_ratio,
# income_confidence, num_income_sources, sector_risk_weight.
#
# CRITICAL FIX: generate_human_explanation() now returns a list of
# DICTIONARIES, not plain strings — matching SharedState's contract:
#   shap_explanation: Optional[list[dict]] = None
# Returning plain strings caused Pydantic validation to reject the
# assignment outright, since validate_assignment=True strictly enforces
# this shape on every write.

class ShapFormatter:
    """
    Converts raw feature contribution numbers into human-readable
    explanations that loan officers and NRB auditors can understand
    without any machine learning background.
    """

    @staticmethod
    def translate_features(feature_name: str, value: float) -> str:
        """
        Converts internal feature names into clean, readable labels,
        formatted appropriately for what kind of number they represent.
        """
        mapping = {
            "loan_to_asset_ratio":  "Loan-to-asset ratio",
            "loan_to_income_ratio": "Loan-to-income ratio",
            "income_confidence":    "Income record reliability",
            "num_income_sources":   "Number of income sources",
            "sector_risk_weight":   "Business sector risk level",
        }
        clean_name = mapping.get(feature_name, feature_name)

        # Ratios — show as a multiple, e.g. "0.42x"
        if feature_name in ("loan_to_asset_ratio", "loan_to_income_ratio"):
            return f"{clean_name} ({value:.2f}x)"

        # Confidence and risk weight — both are 0.0-1.0, show as percentage
        if feature_name in ("income_confidence", "sector_risk_weight"):
            return f"{clean_name} ({round(value * 100, 1)}%)"

        # Count-based — show as a plain integer
        if feature_name == "num_income_sources":
            return f"{clean_name} ({int(value)})"

        return f"{clean_name} ({value})"

    @staticmethod
    def generate_human_explanation(feature_contributions: list) -> list[dict]:
        """
        Takes raw feature contributions and returns a list of dictionaries,
        each containing the feature name, a readable sentence, and the
        underlying shap_value — matching SharedState's documented contract.

        Returns:
            [
                {
                    "feature": "loan_to_asset_ratio",
                    "readable_text": "Loan-to-asset ratio (0.42x) supports...",
                    "shap_value": -0.21
                },
                ...
            ]
        """
        narrative_report = []

        for item in feature_contributions:
            name   = item["feature"]
            val    = item["raw_value"]
            impact = item["shap_value"]

            readable_title = ShapFormatter.translate_features(name, val)

            if impact < 0:
                templates = {
                    "loan_to_asset_ratio": (
                        f"{readable_title} is high relative to verified land value, "
                        "so it lowered the repayment estimate."
                    ),
                    "loan_to_income_ratio": (
                        f"{readable_title} is high relative to annual income, "
                        "so it lowered the repayment estimate."
                    ),
                    "income_confidence": (
                        f"{readable_title} is low, which means the income records need "
                        "closer checking."
                    ),
                    "num_income_sources": (
                        f"{readable_title} is limited, meaning income relies on a single "
                        "stream rather than diversified sources."
                    ),
                    "sector_risk_weight": (
                        f"{readable_title} is relatively high for this business sector, "
                        "so it lowered the repayment estimate."
                    ),
                }
                sentence = templates.get(
                    name, f"{readable_title} lowered the repayment estimate."
                )
            else:
                templates = {
                    "loan_to_asset_ratio": (
                        f"{readable_title} is well covered by verified land value, "
                        "which helped the repayment estimate."
                    ),
                    "loan_to_income_ratio": (
                        f"{readable_title} is comfortable relative to annual income, "
                        "which helped the repayment estimate."
                    ),
                    "income_confidence": (
                        f"{readable_title} is strong, so the income estimate is easier "
                        "to trust."
                    ),
                    "num_income_sources": (
                        f"{readable_title} reflects diversified income, which reduces "
                        "reliance on any single source."
                    ),
                    "sector_risk_weight": (
                        f"{readable_title} is relatively low for this business sector, "
                        "which helped the repayment estimate."
                    ),
                }
                sentence = templates.get(
                    name, f"{readable_title} helped improve the repayment estimate."
                )

            # Return a DICTIONARY, not a plain string — matches SharedState contract
            narrative_report.append({
                "feature":       name,
                "readable_text": sentence,
                "shap_value":    round(impact, 4),
            })

        return narrative_report