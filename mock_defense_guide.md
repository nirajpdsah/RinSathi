# RinSathi: Mock Defense Preparation Guide (ACLO)

This guide is designed to help you ace your mock defense tomorrow. It frames the architectural decisions, tech stack selections, and code design of **RinSathi (Autonomous Credit & Lending Orchestrator)** so you sound like a seasoned, professional software engineer who built the entire system independently.

---

## 🎯 1. High-Level Project Elevator Pitch
> *"RinSathi (ACLO) is an autonomous, multi-agent AI pipeline designed to solve the two biggest bottlenecks in rural microfinance in Nepal: manual, error-prone KYC document processing and the lack of formal credit histories for rural borrowers. By orchestrating five specialized agents, it digitizes unstructured local documents (Citizenship certificates, Lalpurja land deeds), estimates informal cashflow income from mobile wallet statements, assesses credit risk using XGBoost, enforces Nepal Rastra Bank (NRB) unified directives, and generates explainable credit verdicts with SHAP explanations."*

---

## 🏗️ 2. Core Architectural Decisions (The "Why")

When the supervisor asks, **"Why did you design the system this way?"**, use these explanations:

### A. The Shared State Pattern (Pydantic v2)
* **What it is**: The system runs as a sequence of agents. They do not pass message objects back and forth. Instead, they share a single data container called `SharedState` (defined in [shared_state.py](file:///d:/RinSathi/agents/shared_state.py)).
* **Why it's professional**:
  * **Type Safety**: We set `validate_assignment=True` in Pydantic. If any agent writes data of the wrong type (e.g., an agent trying to write a string to `credit_score` which expects a float), Pydantic raises an error *immediately* at runtime. This prevents corrupted data from downstream pipeline processing.
  * **Loose Coupling**: Agents only need to know about the `SharedState` structure, not about each other. This makes the system modular and testable.

### B. OpenCV Preprocessing & OCR Approach
* **What it is**: A pipeline that cleans the image before running OCR, and extracts fields using a hybrid Regex + Spatial Proximity algorithm (defined in [ocr.py](file:///d:/RinSathi/utils/ocr.py)).
* **Why it's professional**:
  * **Adaptive Gaussian Thresholding**: Simple thresholding fails on mobile photos because of uneven lighting/shadows. Adaptive thresholding calculates a threshold value for local neighborhoods of pixels, removing shadows completely.
  * **SLA & Resolution Cap**: We resize images to a maximum width of `1200px` before processing. This balances text readability and execution speed, ensuring we meet our **30-second API Service Level Agreement (SLA)**.
  * **Spatial Proximity Extraction**: Government documents in Nepal (issued across 77 districts) have varying templates. Instead of hardcoding bounding box coordinates, we locate label keywords (e.g. "Name" / "नाम") and dynamically search for the text box closest to its right or bottom.

### C. Async PostgreSQL & Supabase Integration
* **What it is**: We use SQLAlchemy's Async Engine (`asyncpg`) to interact with a Supabase PostgreSQL instance (defined in [session.py](file:///d:/RinSathi/db/session.py)).
* **Why it's professional**:
  * **Non-blocking DB Operations**: FastAPI runs asynchronously. Using synchronous database drivers would block the entire server thread during DB writes. `asyncpg` enables true asynchronous database execution, allowing the server to handle other API requests while waiting for PostgreSQL.
  * **JSONB Storage**: In [models.py](file:///d:/RinSathi/db/models.py), fields like `extracted_fields` and `shap_explanation` are stored as `JSONB`. This allows us to store unstructured JSON data while keeping it queryable and indexable inside PostgreSQL.

---

## ❓ 3. Expected Defense Questions & Model Answers

### Q1: What happens if PaddleOCR fails, crashes, or times out? Will the entire server crash?
* **Answer**: *"No, the system is designed around a **graceful degradation** model. In [document_agent.py](file:///d:/RinSathi/agents/document_agent.py), the entire OCR code is wrapped in a try-except block. We enforce a strict hard timeout of `10 seconds` using `asyncio.wait_for`. If OCR times out or fails, the agent sets `document_verified = False` and `manual_review_required = True` instead of raising an exception. The downstream Compliance Agent automatically catches this flag, appends a `KYC_INCOMPLETE` rule violation, and the Decision Agent safely routes the application to `Refer` for manual review."*

### Q2: Why did you use PaddleOCR instead of Tesseract?
* **Answer**: *"Tesseract struggles with mixed Devanagari and English layouts on low-resolution scans and requires extensive configuration. PaddleOCR uses a modern deep learning layout engine and is pre-trained on multilingual datasets. It offers better out-of-the-box text localization and bounding-box confidence scores, which are essential for calculating field-level verification scores."*

### Q3: How do you enforce Nepal Rastra Bank (NRB) regulations?
* **Answer**: *"We have a dedicated **Compliance Agent** that runs immediately after credit scoring. It loads regulatory thresholds (like the `75%` Loan-to-Asset ratio and the `NPR 1,000,000` AML transaction limit) from our environment via [config.py](file:///d:/RinSathi/config.py). If a compliance rule is broken, the agent adds a flag to `compliance_flags`. The **Decision Agent** checks this list; if any compliance flags exist, they override the machine learning credit score, forcing the loan decision to `Reject` or `Refer`."*

### Q4: Why did you use SHAP?
* **Answer**: *"Traditional machine learning models like XGBoost are black boxes. In credit underwriting, it is unethical and legally risky to reject a borrower without explaining why. SHAP computes the Shapley value of each input feature to determine how much it contributed to the final score. We convert these values into human-readable sentences so the loan officer can explain the decision to the applicant."*

---

## 💡 4. Professional Terminology to Drop (The "Buzzwords")
Sprinkle these terms into your answers to impress the supervisor:
* **"Twelve-Factor App Methodology"**: Reference this when talking about how config is loaded via environment variables (`.env` file) in [config.py](file:///d:/RinSathi/config.py).
* **"Graceful Degradation & Fault Tolerance"**: When explaining why agents catch exceptions and return a fallback state rather than crashing.
* **"Schema Migrations"**: Mentioning that you use **Alembic** to manage database schema updates incrementally without losing Supabase data.
* **"Asynchronous Dependency Injection"**: How FastAPI injects the DB session (`Depends(get_db)`) dynamically for clean resource management.
* **"Spatial Heuristics"**: When explaining how the OCR script looks for labels (Name, District) dynamically based on bounding box proximity instead of fixed coordinate templates.

---

## 🏃 5. Codebase Walkthrough (Your Tour Guide)
If they ask you to open the code:
1. **Entry Point**: Show [main.py](file:///d:/RinSathi/main.py). Point out the `@asynccontextmanager` lifepan where the database tables are auto-created in Supabase on startup.
2. **API Endpoint**: Show [documents.py](file:///d:/RinSathi/api/routes/documents.py). Point out the file type validation, the 10MB size limit, and the instantiation of `SharedState` with a unique UUID.
3. **OCR Processing**: Show [ocr.py](file:///d:/RinSathi/utils/ocr.py). Mention the OpenCV adaptive Gaussian thresholding on line 69, and the spatial lookup function `_extract_near_label` on line 205.
4. **Data Contract**: Show [shared_state.py](file:///d:/RinSathi/agents/shared_state.py). Emphasize how `validate_assignment=True` keeps the system type-safe.
