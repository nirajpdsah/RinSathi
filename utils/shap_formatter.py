# utils/shap_formatter.py

class ShapFormatter:
    """
    This utility takes raw mathematical numbers from SHAP and translates them
    into plain English sentences that human loan officers and auditors can read.
    """
    
    @staticmethod
    def translate_features(feature_name: str, value: float) -> str:
        """
        Converts technical database column names into beautiful, human-friendly terms.
        """
        # Dictionary mapping the internal code terms to clean, readable labels
        mapping = {
            "loan_amount_npr": "Requested Loan Amount",
            "monthly_income_npr": "Normalized Monthly Income",
            "income_confidence": "Income Data Reliability Score",
            "doc_confidence": "Document Verification Confidence"
        }
        
        # Get the clean name from our map; if it's not found, default back to the original name
        clean_name = mapping.get(feature_name, feature_name)
        
        # If the value looks like a raw currency amount over 1,000, format it with commas
        if value > 1000:
            return f"{clean_name} (NPR {int(value):,})"
        # If the value is a fraction under 1.0 (like our confidence metrics), format it as a percentage
        elif 0.0 <= value <= 1.0 and "confidence" in feature_name:
            return f"{clean_name} ({round(value * 100, 1)}%)"
        
        # Return the basic text format for anything else
        return f"{clean_name} ({value})"

    @staticmethod
    def generate_human_explanation(feature_contributions: list) -> list:
        """
        Takes a list of raw feature weights and builds an array of simple narrative sentences.
        """
        narrative_report = []
        
        # Loop through each item in our calculated contributions list
        for item in feature_contributions:
            name = item["feature"]          # e.g., 'loan_amount_npr'
            val = item["raw_value"]         # e.g., 350000
            impact = item["shap_value"]     # e.g., -0.15 (negative means bad impact)
            
            # Translate the technical column name to human terms using our function above
            readable_title = ShapFormatter.translate_features(name, val)
            
            # Scenario A: The factor had a negative mathematical impact on the credit decision
            if impact < 0:
                sentence = f"CRITICAL RISK: {readable_title} actively dragged down the repayment score by pushing it lower."
            # Scenario B: The factor had a positive mathematical impact on the credit decision
            else:
                sentence = f"POSITIVE SIGNAL: {readable_title} provided strong verification, pushing the repayment score higher."
                
            # Add the newly built sentence to our final report collection
            narrative_report.append(sentence)
            
        # Return the collection of sentences back to the pipeline
        return narrative_report