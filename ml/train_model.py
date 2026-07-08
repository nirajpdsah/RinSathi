# ml/train_model.py
#
# Trains the RinSathi credit scoring model using features that mirror
# REAL banking risk variables — ratios and verified data, not raw
# hypothetical numbers.
#
# KEY CHANGES FROM THE ORIGINAL VERSION:
#   1. Removed doc_confidence — meaningless now that identity is
#      binary-verified via DoNIDCR (always 1.0 on success), not a
#      graded OCR confidence score.
#   2. Added loan_to_income_ratio and loan_to_asset_ratio as EXPLICIT
#      features — these are the actual ratios real banks compute for
#      every loan application, and directly mirror our own Compliance
#      Agent's rules.
#   3. Added num_income_sources — reflects income diversification,
#      a real and recognized credit risk factor.
#   4. Added sector_risk_weight — a small fixed lookup table, similar
#      to how real banks maintain sector exposure risk ratings.
#   5. Added a genuine TRAIN/TEST SPLIT and evaluation metrics —
#      previously the model was never tested on unseen data, so no
#      honest accuracy figure could ever be reported.

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix, classification_report
)
import joblib
import os


# ── Sector risk reference ────────────────────────────────────────────────────
# Mirrors how real banks maintain internal sector exposure risk ratings.
# Lower value = lower perceived risk. These are illustrative but directionally
# realistic — agriculture carries seasonal/climate risk, services and retail
# are generally more stable cash-flow businesses.
SECTOR_RISK_WEIGHT = {
    "agriculture":     0.7,   # seasonal, weather-dependent
    "livestock":       0.65,
    "retail":          0.4,
    "services":        0.35,
    "manufacturing":   0.5,
    "construction":    0.55,
    "transport":       0.5,
    "education":       0.3,
    "healthcare":       0.3,
    "other":           0.5,
}


def generate_synthetic_data(num_samples=3000):
    """
    Generates a synthetic but REALISTIC dataset of Nepali microfinance
    loan applicants, using the same ratio-based features our actual
    pipeline now produces after identity verification, land valuation,
    and income breakdown were implemented.

    We increased sample size from 1,000 to 3,000 — with a train/test
    split, we need enough data left over after holding out a test set
    for the model to still learn robust patterns.
    """
    np.random.seed(42)

    # ── Simulate verified income (post income-agent output) ───────────────────
    monthly_income_npr = np.random.uniform(10000, 120000, num_samples)
    annual_income_npr  = monthly_income_npr * 12

    # ── Simulate requested loan amount ─────────────────────────────────────────
    loan_amount_npr = np.random.uniform(30000, 800000, num_samples)

    # ── Simulate verified land asset value (post NeLIS valuation) ─────────────
    # Many rural applicants have modest land value; a smaller number have
    # significant urban-adjacent holdings — we model this with a skewed
    # distribution rather than a flat uniform one, to reflect real inequality
    # in land value distribution across Nepal.
    total_land_value_npr = np.random.lognormal(mean=13.5, sigma=1.2, size=num_samples)
    total_land_value_npr = np.clip(total_land_value_npr, 0, 50_000_000)

    # Some applicants genuinely own no land at all (renters, landless laborers)
    zero_land_mask = np.random.rand(num_samples) < 0.12
    total_land_value_npr[zero_land_mask] = 0

    # ── Simulate income data reliability ────────────────────────────────────
    income_confidence = np.random.uniform(0.3, 1.0, num_samples)

    # ── Simulate number of distinct income sources (1 to 3) ────────────────
    num_income_sources = np.random.choice([1, 2, 3], size=num_samples,
                                           p=[0.45, 0.35, 0.20])

    # ── Simulate business sector ────────────────────────────────────────────
    sectors = np.random.choice(list(SECTOR_RISK_WEIGHT.keys()), size=num_samples)
    sector_risk_weight = np.array([SECTOR_RISK_WEIGHT[s] for s in sectors])

    # ── Compute the REAL ratios — these are what actually get modeled ─────────
    loan_to_income_ratio = loan_amount_npr / annual_income_npr

    # Avoid division by zero for landless applicants — a zero-asset applicant
    # gets a ratio treated as "infinitely unfavorable", capped at a high value
    # rather than literally infinite, so the model can still learn from it.
    loan_to_asset_ratio = np.where(
        total_land_value_npr > 0,
        loan_amount_npr / np.maximum(total_land_value_npr, 1),
        5.0   # effectively "no meaningful collateral" — a large risk penalty
    )
    loan_to_asset_ratio = np.clip(loan_to_asset_ratio, 0, 5.0)

    # ── Ground truth generation ─────────────────────────────────────────────
    # This formula defines what "risk" genuinely correlates with, based on
    # real credit risk principles: higher loan-to-income = riskier,
    # higher loan-to-asset = riskier (less collateral coverage),
    # more income sources = safer (diversification),
    # higher income confidence = safer (verified, reliable income),
    # higher sector risk weight = riskier.
    base_risk = (
        (loan_to_income_ratio       * 1.8) +
        (loan_to_asset_ratio        * 0.9) +
        (sector_risk_weight         * 0.6) -
        (num_income_sources         * 0.35) -
        (income_confidence          * 0.7)
    )

    probability_of_default = 1 / (1 + np.exp(-base_risk + 2.2))
    defaulted = (np.random.rand(num_samples) < probability_of_default).astype(int)
    is_good_applicant = 1 - defaulted

    df = pd.DataFrame({
        "loan_to_income_ratio":  loan_to_income_ratio,
        "loan_to_asset_ratio":   loan_to_asset_ratio,
        "income_confidence":     income_confidence,
        "num_income_sources":    num_income_sources,
        "sector_risk_weight":    sector_risk_weight,
        "is_good_applicant":     is_good_applicant,
    })

    return df


def train_and_evaluate_model():
    """
    Trains the model on a TRAINING split, then honestly evaluates it
    on a held-out TEST split it has never seen — the only credible way
    to report a real accuracy figure.
    """
    print("Generating synthetic training data with realistic banking ratios...")
    data = generate_synthetic_data(num_samples=3000)

    feature_columns = [
        "loan_to_income_ratio",
        "loan_to_asset_ratio",
        "income_confidence",
        "num_income_sources",
        "sector_risk_weight",
    ]
    X = data[feature_columns]
    y = data["is_good_applicant"]

    # ── THE CRITICAL FIX — Train/Test Split ────────────────────────────────
    # 80% of data trains the model. 20% is held back, completely unseen,
    # to honestly measure how well the model generalizes to new applicants.
    # stratify=y ensures both splits have a similar ratio of good/bad
    # applicants, so the test set is a fair, representative sample.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    print(f"Training samples: {len(X_train)}")
    print(f"Test samples:     {len(X_test)} (held out, never seen during training)")

    pipeline_blueprint = [
        ("scaler",   StandardScaler()),
        ("xgboost",  XGBClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.08,
            random_state=42, eval_metric="logloss"
        )),
    ]
    credit_pipeline = Pipeline(pipeline_blueprint)

    print("\nTraining the RinSathi XGBoost credit model...")
    credit_pipeline.fit(X_train, y_train)

    # ── HONEST EVALUATION ON UNSEEN TEST DATA ──────────────────────────────
    y_pred  = credit_pipeline.predict(X_test)
    y_proba = credit_pipeline.predict_proba(X_test)[:, 1]

    accuracy  = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred)
    recall    = recall_score(y_test, y_pred)
    f1        = f1_score(y_test, y_pred)
    auc       = roc_auc_score(y_test, y_proba)
    cm        = confusion_matrix(y_test, y_pred)

    print("\n" + "="*60)
    print("MODEL EVALUATION — ON HELD-OUT TEST DATA (never seen in training)")
    print("="*60)
    print(f"Accuracy:  {accuracy:.4f}  ({accuracy*100:.1f}%)")
    print(f"Precision: {precision:.4f}  (of predicted 'good', how many truly were)")
    print(f"Recall:    {recall:.4f}  (of actual 'good' applicants, how many we caught)")
    print(f"F1 Score:  {f1:.4f}")
    print(f"ROC-AUC:   {auc:.4f}  (model's ability to rank risk correctly, 0.5=random, 1.0=perfect)")
    print("\nConfusion Matrix:")
    print(f"                  Predicted Bad   Predicted Good")
    print(f"  Actual Bad          {cm[0][0]:>6}          {cm[0][1]:>6}")
    print(f"  Actual Good         {cm[1][0]:>6}          {cm[1][1]:>6}")
    print("\nFull Classification Report:")
    print(classification_report(y_test, y_pred, target_names=["Bad Applicant", "Good Applicant"]))

    # ── Feature importance — which ratios matter most to the model ─────────
    importances = credit_pipeline.named_steps["xgboost"].feature_importances_
    print("Feature Importance (which factors drive the model most):")
    for feat, imp in sorted(zip(feature_columns, importances), key=lambda x: -x[1]):
        print(f"  {feat:<25} {imp:.4f}")

    # ── Save the trained pipeline AND the evaluation metrics together ──────
    os.makedirs("ml", exist_ok=True)
    joblib.dump(credit_pipeline, "ml/credit_model.joblib")

    metrics_record = {
        "accuracy": accuracy, "precision": precision, "recall": recall,
        "f1_score": f1, "roc_auc": auc,
        "test_samples": len(X_test), "train_samples": len(X_train),
        "feature_columns": feature_columns,
    }
    joblib.dump(metrics_record, "ml/model_metrics.joblib")

    print("\n" + "="*60)
    print("Model saved at:   ml/credit_model.joblib")
    print("Metrics saved at: ml/model_metrics.joblib")
    print("="*60)


if __name__ == "__main__":
    train_and_evaluate_model()