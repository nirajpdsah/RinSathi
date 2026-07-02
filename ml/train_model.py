# ml/train_model.py

# Import NumPy to help us generate structured random numbers for our fake applicants
import numpy as np
# Import Pandas to organize our generated numbers into a clean table structure (DataFrame)
import pandas as pd
# Import the actual XGBoost algorithm that will learn patterns from our data
from xgboost import XGBClassifier
# Import Pipeline to bundle our scaling and machine learning steps into a single object
from sklearn.pipeline import Pipeline
# Import StandardScaler to normalize numeric values so big numbers don't confuse the AI
from sklearn.preprocessing import StandardScaler
# Import joblib so we can save our trained AI model onto the computer disk as a file
import joblib
# Import os to make sure we can create folders on your computer safely
import os

def generate_synthetic_data(num_samples=1000):
    """
    This function creates a fake, realistic dataset of 1,000 Nepali loan applicants
    to train our AI model on, simulating alternative financial signals.
    """
    # Set a fixed random seed so that running this script always creates the exact same data
    np.random.seed(42)
    
    # Simulate requested loan amounts in Nepali Rupees (ranging mostly from 50k to 500k NPR)
    loan_amount_npr = np.random.uniform(50000, 500000, num_samples)
    
    # Simulate normalized monthly income from the Income Agent (ranging from 15k to 90k NPR)
    monthly_income_npr = np.random.uniform(15000, 90000, num_samples)
    
    # Simulate the Income Agent's confidence score (ranging from 40% up to 100% reliability)
    income_confidence = np.random.uniform(0.4, 1.0, num_samples)
    
    # Simulate identity verification confidence (ranging from 50% to 100%)
    doc_confidence = np.random.uniform(0.5, 1.0, num_samples)
    
    # Calculate a logical mathematical probability of default based on these inputs
    # Higher income and higher reliability reduce risk; massive loans relative to income increase risk
    base_risk = (loan_amount_npr / (monthly_income_npr * 12)) * 0.5 - (income_confidence * 0.3) - (doc_confidence * 0.2)
    
    # Convert that risk score into a clean probability curve between 0 and 1
    probability_of_default = 1 / (1 + np.exp(-base_risk))
    
    # Decide if the fake applicant successfully paid back the loan (1) or defaulted (0)
    # If their risk probability is higher than a random threshold, they are marked as a default
    defaulted = (np.random.rand(num_samples) < probability_of_default).astype(int)
    
    # Flip the binary labels: 1 means Good Applicant (Repays Loan), 0 means Bad Applicant (Defaults)
    # This matches the handbook standard where higher machine learning scores mean higher repayment safety
    is_good_applicant = 1 - defaulted

    # Pack all these separate data columns into a clean, labeled pandas data table
    df = pd.DataFrame({
        "loan_amount_npr": loan_amount_npr,
        "monthly_income_npr": monthly_income_npr,
        "income_confidence": income_confidence,
        "doc_confidence": doc_confidence,
        "is_good_applicant": is_good_applicant
    })
    
    # Return the completed data table back to the script
    return df

def train_and_save_model():
    """
    This function takes the fake data, feeds it to the XGBoost machine learning 
    algorithm, builds a protected pipeline, and saves it to a file.
    """
    # Call our function above to generate a fresh table of 1,000 applicant profiles
    data = generate_synthetic_data(num_samples=1000)
    
    # Separate the input features (the clues) that the AI will look at to make a decision
    X = data[["loan_amount_npr", "monthly_income_npr", "income_confidence", "doc_confidence"]]
    
    # Separate the target column (the correct answer) that the AI is trying to learn to predict
    y = data["is_good_applicant"]
    
    # Create an isolated step-by-step pipeline blueprint for our machine learning execution
    pipeline_blueprint = [
        # Step A: Scale the numbers so features like large loan amounts don't overshadow small confidence percentages
        ("scaler", StandardScaler()),
        # Step B: Attach the core XGBoost classifier algorithm to perform the statistical learning
        ("xgboost", XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42))
    ]
    
    # Initialize the formal scikit-learn Pipeline wrapper container using our blueprint steps
    credit_pipeline = Pipeline(pipeline_blueprint)
    
    # Execute the training loop: the pipeline scales the variables and teaches XGBoost patterns from the data
    print("Training the RinSathi XGBoost credit model...")
    credit_pipeline.fit(X, y)
    
    # Ensure that the 'ml/' folder exists inside your directory before trying to write to it
    os.makedirs("ml", exist_ok=True)
    
    # Save the fully trained, operational pipeline file onto your computer disk
    joblib.dump(credit_pipeline, "ml/credit_model.joblib")
    # Print a success confirmation statement to the terminal logs
    print("Success! Model trained and saved cleanly at: ml/credit_model.joblib")

# This special condition checks if this file is being run directly from the terminal prompt
if __name__ == "__main__":
    # If run directly, kick off the training function automatically
    train_and_save_model()