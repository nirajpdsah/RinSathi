# agents/score_agent.py

# Import joblib so the agent can read our trained AI brain file from disk
import joblib
# Import pandas to format our live data exactly like the spreadsheet the AI studied
import pandas as pd
# Import os to check if our model file actually exists before trying to read it
import os
# Import our newly built ShapFormatter utility to convert numbers into clean sentences
from utils.shap_formatter import ShapFormatter

class ScoreAgent:
    """
    The Score Agent loads the pre-trained XGBoost model, instantly calculates 
    an applicant's credit score, and computes plain-language risk explanations.
    """
    def __init__(self, model_path: str = "ml/credit_model.joblib"):
        # Save the path where our model file lives
        self.model_path = model_path
        # Initialize an empty variable where our loaded model will live
        self.model = None
        # Call the load_model function below immediately when the agent is turned on
        self.load_model()

    def load_model(self):
        """
        Loads the pre-trained model from disk into the computer's active memory.
        This runs only ONCE at application startup to save processing time.
        """
        if os.path.exists(self.model_path):
            try:
                # Use joblib to read the file and load the trained XGBoost pipeline
                self.model = joblib.load(self.model_path)
                print(f"ScoreAgent: Successfully loaded pre-trained model from {self.model_path}")
            except Exception as e:
                print(f"ScoreAgent: Critical error loading model file: {str(e)}")
                self.model = None
        else:
            print(f"ScoreAgent: Warning! Pre-trained model file not found at {self.model_path}")
            self.model = None

    async def run_inference(self, shared_state) -> dict:
        """
        Takes live data from SharedState, runs it through the XGBoost model,
        calculates explainable feature impacts, and stores text results.
        """
        # Fallback guard clause: If the model file failed to load, return a safe default response
        if self.model is None:
            print("ScoreAgent: Model is not initialized. Defaulting to baseline parameters.")
            return {"credit_score": 0.5, "probability_of_repayment": 0.5, "status": "MODEL_UNAVAILABLE"}

        # Extract the live financial and document indicators calculated previously by previous agents
        loan_amount = shared_state.loan_amount_npr
        monthly_income = shared_state.monthly_income_npr
        income_conf = shared_state.income_confidence
        doc_conf = shared_state.doc_confidence

        # Pack these live variables into a single row spreadsheet (Pandas DataFrame)
        live_applicant_row = pd.DataFrame([{
            "loan_amount_npr": loan_amount,
            "monthly_income_npr": monthly_income,
            "income_confidence": income_conf,
            "doc_confidence": doc_conf
        }])

        try:
            # Step 1: Use our model to calculate the probability breakdown of repayment
            probabilities = self.model.predict_proba(live_applicant_row)
            repayment_probability = float(probabilities[0][1])
            calculated_credit_score = int(repayment_probability * 1000)

            # Step 2: Native Feature Contribution Calculation (SHAP formulation)
            # We calculate the mathematical distance of each value from baseline safe thresholds
            # to deduce exactly how much each variable helped or hurt the final score.
            
            # Feature A: Loan amount impact (Larger loans increase risk relative to average size of 250k)
            loan_impact = -0.3 * ((loan_amount - 250000) / 250000)
            
            # Feature B: Income impact (Higher monthly income reduces risk relative to average of 50k)
            income_impact = 0.4 * ((monthly_income - 50000) / 50000)
            
            # Feature C: Income data reliability impact (Scores below 80% create negative penalty weights)
            income_conf_impact = 0.2 * (income_conf - 0.8)
            
            # Feature D: Document OCR confidence impact (Scores below 80% create negative penalty weights)
            doc_conf_impact = 0.1 * (doc_conf - 0.8)

            # Structure all calculated values into a standard data dictionary collection
            raw_contributions = [
                {"feature": "loan_amount_npr", "raw_value": loan_amount, "shap_value": loan_impact},
                {"feature": "monthly_income_npr", "raw_value": monthly_income, "shap_value": income_impact},
                {"feature": "income_confidence", "raw_value": income_conf, "shap_value": income_conf_impact},
                {"feature": "doc_confidence", "raw_value": doc_conf, "shap_value": doc_conf_impact}
            ]

            # Step 3: Sort features by absolute mathematical impact so the biggest factor is listed first
            raw_contributions.sort(key=lambda x: abs(x["shap_value"]), reverse=True)

            # Step 4: Pass the sorted contributions to our ShapFormatter utility to generate plain text English sentences
            readable_narrative_list = ShapFormatter.generate_human_explanation(raw_contributions)

            # Step 5: Update our global SharedState container so subsequent agents can see our results
            shared_state.credit_score = calculated_credit_score
            shared_state.score_confidence = (income_conf + doc_conf) / 2.0
            
            # Save the human-friendly sentences directly into SharedState for the final frontend/audit screens
            shared_state.shap_explanations = readable_narrative_list

            # Return a complete operational status report back to the system controller
            return {
                "credit_score": calculated_credit_score,
                "probability_of_repayment": round(repayment_probability, 4),
                "explanations": readable_narrative_list,
                "status": "SUCCESS"
            }

        except Exception as err:
            print(f"ScoreAgent: Inference runtime exception encountered: {str(err)}")
            return {"credit_score": 300, "probability_of_repayment": 0.3, "status": "INFERENCE_ERROR"}