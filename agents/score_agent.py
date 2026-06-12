# agents/score_agent.py

# Import joblib so the agent can read our trained AI brain file from disk
import joblib
# Import pandas to format our live data exactly like the spreadsheet the AI studied
import pandas as pd
# Import os to check if our model file actually exists before trying to read it
import os

class ScoreAgent:
    """
    The Score Agent is responsible for loading the pre-trained XGBoost model 
    and instantly calculating an applicant's repayment probability score.
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
        # Check if the credit_model.joblib file actually exists on the computer
        if os.path.exists(self.model_path):
            try:
                # Use joblib to read the file and load the trained XGBoost pipeline
                self.model = joblib.load(self.model_path)
                print(f"ScoreAgent: Successfully loaded pre-trained model from {self.model_path}")
            except Exception as e:
                # If the file is corrupted, print an error message to the terminal
                print(f"ScoreAgent: Critical error loading model file: {str(e)}")
                self.model = None
        else:
            # If the file is missing entirely, print a clear warning statement
            print(f"ScoreAgent: Warning! Pre-trained model file not found at {self.model_path}")
            self.model = None

    async def run_inference(self, shared_state) -> dict:
        """
        Takes the live data saved in SharedState, runs it through the XGBoost model,
        and returns the final credit score metrics.
        """
        # Fallback guard clause: If the model file failed to load, return a safe default response
        if self.model is None:
            print("ScoreAgent: Model is not initialized. Defaulting to baseline parameters.")
            return {"credit_score": 0.5, "probability_of_repayment": 0.5, "status": "MODEL_UNAVAILABLE"}

        # Extract the live alternative financial indicators calculated previously by our Income Agent
        loan_amount = shared_state.loan_amount_npr
        monthly_income = shared_state.monthly_income_npr
        income_conf = shared_state.income_confidence
        doc_conf = shared_state.doc_confidence

        # Pack these live variables into a single row spreadsheet (Pandas DataFrame)
        # CRITICAL: The column names must match the exact labels the model studied during training
        live_applicant_row = pd.DataFrame([{
            "loan_amount_npr": loan_amount,
            "monthly_income_npr": monthly_income,
            "income_confidence": income_conf,
            "doc_confidence": doc_conf
        }])

        try:
            # Step 1: Use our model to calculate the probability breakdown of repayment
            # predict_proba returns an array like [[Probability of Default, Probability of Repayment]]
            probabilities = self.model.predict_proba(live_applicant_row)
            
            # Extract the probability of repayment (index 1) as a clear decimal value
            repayment_probability = float(probabilities[0][1])
            
            # Step 2: Convert the probability float into a standard credit score gauge out of 1000
            # For example, an 85% probability becomes an ACLO credit score of 850
            calculated_credit_score = int(repayment_probability * 1000)

            # Step 3: Update our global SharedState container so subsequent agents can see our results
            shared_state.credit_score = calculated_credit_score
            shared_state.score_confidence = (income_conf + doc_conf) / 2.0  # Average data reliability metric

            # Return a summary dictionary back to the controller pipeline
            return {
                "credit_score": calculated_credit_score,
                "probability_of_repayment": round(repayment_probability, 4),
                "status": "SUCCESS"
            }

        except Exception as err:
            # Operational fallback: If an unexpected calculation error occurs, log it safely without crashing
            print(f"ScoreAgent: Inference runtime exception encountered: {str(err)}")
            return {"credit_score": 300, "probability_of_repayment": 0.3, "status": "INFERENCE_ERROR"}