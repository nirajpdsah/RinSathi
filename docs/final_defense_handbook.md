# RinSathi Mid-Defense Handbook

## Purpose Of This Document

This handbook is a repository-level technical narrative of RinSathi. It is intentionally written as a dense source document for later conversion into a report or PDF handbook. It covers the current codebase as it exists in this workspace, including backend architecture, data contracts, agent flow, mock government integrations, frontend behavior, model training, tests, and operational notes.

The goal is not only to explain what the project does, but also to preserve the small implementation details that matter for defense, documentation, maintenance, and later audit review.

## Project Summary

RinSathi is a FastAPI-based lending orchestration system built for Nepalese microfinance workflows. It implements an end-to-end loan assessment pipeline that:

1. Authenticates clients and officers.
2. Verifies applicant identity against a mock DoNIDCR registry using NIN.
3. Fetches land assets from a mock NeLIS registry using citizenship number.
4. Normalizes income from multiple informal and semi-formal sources.
5. Scores repayment probability using a trained XGBoost model.
6. Applies deterministic NRB-style compliance rules.
7. Produces a final decision of Recommend, Refer, or Reject.
8. Persists the application and its audit trail in PostgreSQL via SQLAlchemy async sessions.
9. Exposes client and officer dashboards through static HTML, CSS, and JavaScript.

The current architecture explicitly uses NIN-based identity verification instead of an OCR/document-image workflow. The project still preserves old-style document-related field names in a few shared contracts for compatibility, but the authoritative identity path is government registry verification.

## Repository Structure

### Top-Level Files

- `main.py` is the FastAPI application entrypoint.
- `config.py` holds environment-driven configuration.
- `alembic.ini` configures Alembic migrations.
- `requirements.txt` lists runtime dependencies.
- `requirements-docker.txt` provides the Docker-focused dependency set.
- `Dockerfile` defines container build/runtime behavior.
- `README.md` provides a shorter overview and quick start.
- `check_cib.py` is a small SQLite inspection script for mock CIB data.

### Backend Packages

- `agents/` contains the five-stage underwriting pipeline.
- `api/` contains API schemas and the loan/income routes.
- `core/` contains security and JWT helpers.
- `db/` contains SQLAlchemy models, base classes, and the async engine/session setup.
- `routers/` contains the web-facing authentication and dashboard routes plus mock government APIs.
- `schemas/` contains authentication request/response schemas.
- `services/` contains reusable auth logic.
- `utils/` contains income parsing and SHAP formatting helpers.
- `mock_databases/` contains the SQLite seeders and generated demo databases.
- `ml/` contains the training script and saved model artifacts.
- `docs/` contains the handbook PDF generator.
- `tests/` contains lightweight verification scripts and regression checks.

### Frontend Assets

- `frontend/index.html` is the public landing page.
- `frontend/assets/css/main.css` is the shared design system.
- `frontend/assets/js/auth.js` manages JWT state and API requests.
- `frontend/assets/js/guard.js` protects authenticated pages.
- `frontend/auth/login.html` is the client Google login page.
- `frontend/auth/officer_login.html` is the officer credential login page.
- `frontend/templates/client/` contains the client dashboard, loan application, guide, and status pages.
- `frontend/templates/officer/` contains the officer dashboard and review pages.

## System Architecture

RinSathi follows a layered architecture with a clear separation between public pages, authenticated dashboards, API routes, service logic, business agents, persistence, and mock external systems.

The runtime path is roughly:

1. The browser loads the static frontend.
2. A user logs in with Google OAuth or officer credentials.
3. The backend issues a JWT containing user identity and role.
4. Protected pages use the token through `auth.js` and `guard.js`.
5. A client submits a loan application through `/api/v1/loan/apply`.
6. The pipeline populates a shared state object and runs the agents.
7. The final outcome is saved to the database and the audit log.
8. Dashboards query the stored application and audit data to render details.

This separation is important because the project uses the same API and data contracts across multiple surfaces: the mobile-like browser UI, the officer dashboard, the client dashboard, and the underlying loan pipeline.

## Application Entry Point

### `main.py`

`main.py` initializes the FastAPI app and controls the application lifecycle.

Key responsibilities:

- Creates the `FastAPI` app instance with a title, description, version, and lifespan handler.
- Enables permissive CORS so browser fetch calls can reach the API.
- Registers API routers under `/api/v1`.
- Mounts the `frontend/` directory as static HTML content at the root path.
- Exposes a `/health` endpoint.
- Instantiates a global `ScoreAgent` for reuse.
- Exposes a second `/api/v1/income/analyze` route directly from `main.py` in addition to the dedicated route module.

Lifecycle behavior:

- On startup, the app prints a banner, creates missing tables via `create_tables()`, and announces the docs and login URLs.
- On shutdown, it disposes of the async SQLAlchemy engine.

Important implementation details:

- The app uses `StaticFiles(directory="frontend", html=True)` so the entire frontend tree is served directly.
- The auth router import is duplicated in the current file, but the final included router variable is the one imported as `router` from `routers.auth`.
- The `/api/v1/income/analyze` route in `main.py` is a pipeline-style helper that constructs a `SharedState`, seeds a few income fields, and runs the global `ScoreAgent`.

### `/health`

The health endpoint returns a small JSON payload:

- `status`: `ok`
- `version`: `1.0.0`
- `database`: `supabase`

This endpoint is intentionally minimal and is useful for deployment checks and simple liveness testing.

## Configuration

### `config.py`

Configuration is handled through a Pydantic `BaseSettings` class. Values are read from `.env` and cached with `lru_cache()` so the settings object is created only once.

Important settings:

- `DATABASE_URL`: required PostgreSQL connection string.
- `SECRET_KEY`: JWT signing secret.
- `ALGORITHM`: JWT signing algorithm, default `HS256`.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: default 1440 minutes, or 24 hours.
- `APPROVE_THRESHOLD`: default `0.65`.
- `REFER_THRESHOLD`: default `0.40`.
- `MIN_KYC_CONFIDENCE`: default `0.70`.
- `MAX_LOAN_TO_ASSET`: default `0.75`.
- `MAX_VEHICLE_LOAN_TO_VALUE`: default `0.85`.
- `AML_TXN_LIMIT_NPR`: default `1_000_000`.
- `AGRI_SECTOR_LIMIT_NPR`: default `500_000`.
- `OCR_TIMEOUT_SECONDS`: default `10.0`.
- `google_client_id`: required client ID used to validate Google login tokens.
- `DONIDCR_URL`: mock government identity verification endpoint in development.
- `NELIS_URL`: mock land registry endpoint in development.
- `CIB_URL`: mock credit bureau endpoint in development.

The comments in the file emphasize that thresholds and secrets must come from the environment, not hardcoded in the agents.

## Database Layer

### `db/session.py`

This file defines the async database engine and request-scoped sessions.

Implementation details:

- Converts the configured PostgreSQL URL into `postgresql+asyncpg`.
- Uses `create_async_engine()` with a small pool, pre-ping, recycle, and SSL-preference connection args.
- Uses `sessionmaker(..., class_=AsyncSession, expire_on_commit=False)`.
- Defines the declarative `Base` class used by all ORM models.
- Exposes `create_tables()` to create tables from SQLAlchemy metadata at startup.
- Exposes `get_db()` as an async FastAPI dependency that yields a session and closes it automatically.

The session file is the bridge between FastAPI request handling and Supabase PostgreSQL.

### `db/models.py`

This file defines the ORM schema for the application.

#### Enums

- `LoanStatus` has four values: `pending`, `approved`, `rejected`, `referred`.
- `DocumentType` has three values: `citizenship`, `lalpurja`, `pan`.

#### `Role`

Stores system roles in the `roles` table.

Fields:

- `id`: UUID primary key.
- `name`: unique role name, such as `client` or `officer`.
- `description`: optional description.

Relationship:

- `users` is the collection of users that belong to the role.

#### `User`

Stores every login-capable account.

Fields:

- `id`: UUID primary key.
- `email`: unique email address.
- `full_name`: display name.
- `role_id`: foreign key to `roles.id`.
- `google_id`: Google subject ID, used for clients.
- `password_hash`: bcrypt hash, used for officers.
- `is_active`: soft disable flag.
- `created_at`: timezone-aware creation timestamp.

Relationships:

- `role` links to the `Role` object.
- `applications` lists applications submitted by this user.
- `reviewed_applications` lists applications reviewed by this user.

#### `Applicant`

Central table for loan applications.

Fields:

- `id`: UUID primary key.
- `full_name`: applicant name.
- `citizenship_no`: optional national citizenship number.
- `district`: optional district string.
- `phone`: optional phone number.
- `loan_amount_npr`: requested amount.
- `sector`: business sector.
- `status`: `LoanStatus` enum.
- `user_id`: client owner of the application.
- `reviewed_by`: officer who made the final human review decision.
- `officer_remarks`: written justification.
- `reviewed_at`: decision timestamp.
- `created_at`: submission timestamp.
- `updated_at`: automatic update timestamp.

Relationships:

- `client` links to the submitting `User`.
- `reviewing_officer` links to the reviewing `User`.
- `documents` links to document rows.
- `audit_logs` links to audit log entries.

#### `Document`

Stores uploaded or extracted documents and OCR output.

Fields:

- `id`: UUID primary key.
- `applicant_id`: required foreign key.
- `document_type`: enum type.
- `extracted_fields`: JSONB structured data.
- `doc_confidence`: float confidence score.
- `manual_review_required`: boolean flag.
- `ocr_raw_text`: raw OCR text.
- `created_at`: timestamp.

Relationship:

- `applicant` links to the owning `Applicant`.

#### `AuditLog`

Stores a trace of every meaningful action.

Fields:

- `id`: UUID primary key.
- `applicant_id`: optional application reference.
- `event_type`: event name such as `PIPELINE_COMPLETED` or `OFFICER_APPROVED`.
- `agent_name`: which agent or user initiated the event.
- `details`: JSONB payload with context.
- `performed_by`: string user ID or `system`.
- `created_at`: timestamp.

Relationship:

- `applicant` links to `Applicant`.

### Persistence Behavior

The application persists both the application row and a full audit log. The audit trail stores the identity data, land data, income summary, SHAP explanation, compliance flags, and decision output so dashboards can reconstruct a detailed application view later.

## Shared State Contract

### `agents/shared_state.py`

`SharedState` is the central object passed through every agent in the pipeline.

Important design features:

- It is a Pydantic v2 `BaseModel` with `validate_assignment=True`.
- Any type mismatch on assignment is rejected immediately.
- It acts as the contract between the identity, income, score, compliance, and decision stages.

Key fields:

- Request identity: `applicant_id`, `loan_amount_npr`, `sector`.
- Identity outputs: `document_verified`, `extracted_fields`, `doc_confidence`, `manual_review_required`, `nin`, `verified_full_name`, `citizenship_no`, `date_of_birth`, `permanent_address`, `sex`.
- Land outputs: `total_land_ropani`, `total_land_aana`, `total_land_parcels`, `total_land_value_npr`.
- Income outputs: `monthly_income_npr`, `income_confidence`, `income_sources`, `name_mismatch_detected`, `income_breakdown`, `total_accumulated_income_npr`.
- Score outputs: `credit_score`, `shap_explanation`.
- Compliance outputs: `compliance_flags`, `is_blacklisted`, `max_dpd_bucket`, `active_loan_count`, `cib_records_count`, `nepal_credit_score`.
- Decision outputs: `final_decision`, `decision_reason`, `audit_trail_path`, `qualification_score`.
- Vehicle loan fields: `loan_type`, `vehicle_make_model`, `vehicle_is_new`, `vehicle_purchase_price_npr`, `vehicle_value_npr`.

The file comments are explicit that field names should remain stable because downstream agents and dashboards depend on them.

## The Five-Agent Pipeline

RinSathi’s core business logic is implemented as five agents executed in sequence or parallel depending on the stage.

### 1. Identity Agent

#### `agents/identity_agent.py`

The Identity Agent replaces the document-image workflow with authoritative registry lookup.

Responsibilities:

- Validate that a NIN exists in the request state.
- Call the mock DoNIDCR verification endpoint.
- Extract authoritative identity fields.
- Query mock NeLIS using the returned citizenship number.
- Query mock CIB using the same citizenship number.
- Estimate vehicle collateral value if the loan type is vehicle.
- Populate shared state fields.
- Never raise an exception outward; always degrade gracefully.

Key behaviors:

- If NIN is missing, it marks verification failed.
- If DoNIDCR returns 404 or 410, the agent returns a failure state and sets `manual_review_required`.
- If DoNIDCR returns success, the agent writes `verified_full_name`, `citizenship_no`, `date_of_birth`, `permanent_address`, and `sex`.
- The `extracted_fields` structure is retained for compatibility with older downstream logic.
- If land lookup fails, the pipeline still continues, but all asset values are set to zero.
- If CIB lookup fails, the applicant is treated as having no bureau history, not as an automatic failure.
- For vehicle loans, if a purchase price exists it is used directly as `vehicle_value_npr`; otherwise a reference value is estimated from model and new/used status.

Important constants and helpers:

- `DONIDCR_URL`, `NELIS_URL`, and `CIB_URL` come from settings.
- `API_TIMEOUT` is `10.0` seconds.
- `VEHICLE_BASE_PRICE` provides a reference table for common vehicle models.
- `estimate_vehicle_value()` applies a depreciation factor of `0.88 ** age_years` with a floor at `25%` of base price for used vehicles.

The identity agent is the first point where the system transitions from applicant-supplied claims to authoritative verified data.

### 2. Income Agent

#### `agents/income_agent.py`

The Income Agent parses and normalizes income signals from three sources:

- eSewa or Khalti transaction history.
- Remittance records.
- Cooperative or savings group ledgers.

Responsibilities:

- Parse each source into a standard income signal list.
- Combine all signals into a `MonthlyIncomeEstimate` using `normalize_to_monthly_estimate()`.
- Compare the name in identity data with names found in income records.
- Set `monthly_income_npr`, `income_confidence`, `income_sources`, and `name_mismatch_detected`.

Key behavior details:

- The agent never raises outward; it catches errors and falls back to a very low confidence result.
- It treats missing or invalid income data as low-confidence, not as an exception.
- Name mismatch reduces confidence by 40 percent and marks `name_mismatch_detected = True`.
- Raw NPR values are preserved as raw values; scaling is deferred to the scoring model.

### 3. Score Agent

#### `agents/score_agent.py`

The Score Agent loads a trained XGBoost pipeline from `ml/credit_model.joblib` and predicts repayment probability.

Core features used by the live model:

- `loan_to_income_ratio`
- `loan_to_asset_ratio`
- `income_confidence`
- `num_income_sources`
- `sector_risk_weight`

Important implementation details:

- If the model file is missing or cannot be loaded, the agent falls back to `0.5` and an empty explanation list.
- The live score is stored as a probability between `0.0` and `1.0`, not multiplied into a 0-1000 score.
- `loan_to_asset_ratio` is capped at `5.0` if the applicant has no asset value.
- `num_income_sources` is at least `1` if the applicant reaches scoring.

Explainability behavior:

- The agent builds a contribution list with rough local effects.
- It sorts contributions by absolute effect.
- It uses `ShapFormatter.generate_human_explanation()` to produce a list of dictionaries with readable text.

Fallback behavior:

- If inference fails, the score is set to `0.5` and the explanation list is emptied.

### 4. Compliance Agent

#### `agents/compliance_agent.py`

The Compliance Agent is a deterministic rule engine, not an ML component.

Responsibilities:

- Reset and rebuild `compliance_flags`.
- Enforce KYC, income, collateral, sector exposure, blacklist, delinquency, AML, and no-income checks.
- Treat compliance flags as higher priority than score in the decision stage.

Rules implemented:

- `KYC_INCOMPLETE` when identity verification requires manual review.
- `INCOME_UNVERIFIABLE` when income confidence is below `0.25`.
- `NAME_MISMATCH` when the income name does not match the identity name.
- `LOAN_TO_ASSET_BREACH` for microfinance if loan amount exceeds `MAX_LOAN_TO_ASSET` times land value.
- `VEHICLE_LOAN_TO_VALUE_BREACH` for vehicle loans if loan exceeds `MAX_VEHICLE_LOAN_TO_VALUE` times vehicle value.
- `NO_VERIFIED_COLLATERAL` or `NO_VERIFIED_VEHICLE_COLLATERAL` when no collateral value exists.
- `SECTOR_EXPOSURE_LIMIT` when agriculture-style exposure exceeds `AGRI_SECTOR_LIMIT_NPR`.
- `CIB_BLACKLISTED` when the applicant is formally blacklisted.
- `SEVERE_DELINQUENCY_HISTORY` when the applicant has a `dpd_90_plus` record.
- `AML_FLAG` when monthly income exceeds `AML_TXN_LIMIT_NPR`.
- `NO_INCOME_SIGNALS` when monthly income is zero but the loan is above `10_000`.
- `SYSTEM_ERROR` on unexpected internal failure.

Important note:

- There is a duplicated agricultural sector exposure check in the current file. The logic still works because the same flag is appended if the condition is true, but it is a sign of duplicated rule logic in the source.

### 5. Decision Agent

#### `agents/decision_agent.py`

The Decision Agent is the final stage of the pipeline. It converts the combined state into one of three verdicts:

- `Recommend`
- `Reject`
- `Refer`

Priority order:

1. Compliance flags override everything.
2. Missing credit score causes manual review.
3. Otherwise a weighted qualification score decides the outcome.

Detailed behavior:

- Any compliance flag triggers either `Reject` or `Refer` depending on the flag severity.
- Hard reject flags include `AML_FLAG`, `NO_INCOME_SIGNALS`, `LOAN_TO_ASSET_BREACH`, `NAME_MISMATCH`, `CIB_BLACKLISTED`, `NO_VERIFIED_VEHICLE_COLLATERAL`, and `VEHICLE_LOAN_TO_VALUE_BREACH`.
- Non-hard flags generally lead to `Refer`.
- If no score is available, the agent returns `Refer` with a manual-review reason.
- When a score is available, it computes a qualification score out of 100 using:
  - 35 percent repayment probability.
  - 20 percent asset coverage ratio.
  - 15 percent income stability.
  - 15 percent credit history score.
  - 15 percent compliance score.

Decision bands:

- `Recommend` when qualification score is at or above `APPROVE_THRESHOLD * 100`.
- `Reject` when qualification score is below `REFER_THRESHOLD * 100`.
- `Refer` for the middle range.

The decision reason is intentionally verbose so that an officer or applicant can understand why the verdict was produced.

## API Layer

### `api/routes/income.py`

This route module exposes the dedicated income analysis endpoints.

#### Request schema: `IncomeAnalyzeRequest`

Fields:

- `applicant_id`: UUID link to an applicant.
- `esewa_data`: optional dict.
- `remittance_data`: optional dict.
- `coop_data`: optional dict.
- `use_mock_data`: boolean, default `False`.

#### Response schema: `IncomeAnalyzeResponse`

Fields:

- `applicant_id`
- `mean_monthly_npr`
- `std_dev_npr`
- `confidence`
- `months_of_data`
- `low_confidence`
- `sources`
- `source_count`
- `processing_time_ms`

#### `POST /income/analyze`

Behavior:

- If `use_mock_data` is true, the route generates mock source data.
- It requires at least one source.
- It builds a `SharedState` object.
- It parses all source payloads directly through utility functions.
- It normalizes the signals and returns the full estimate.

#### `GET /income/mock-data`

Returns sample eSewa, remittance, and cooperative payloads plus a usage note.

This endpoint is useful for frontend experimentation and demonstrates the expected payload shape.

### `api/routes/loan.py`

This is the main underwriting endpoint.

#### `POST /loan/apply`

The loan application route accepts form data and a bearer token.

Form fields:

- `nin`
- `loan_amount_npr`
- `sector`
- `loan_type`
- `vehicle_make_model`
- `vehicle_is_new`
- `vehicle_purchase_price_npr`
- `cashflow_name`
- `esewa_monthly_npr`
- `remittance_monthly_npr`
- `coop_monthly_npr`
- `use_mock_income`

Auth and DB dependencies:

- `credentials` uses `HTTPBearer`.
- `db` is provided by `get_db()`.

Execution flow:

1. Verify the JWT token and extract `user_id`.
2. Validate NIN and loan amount.
3. Check for a duplicate active application for the same user.
4. Create a new `SharedState` with applicant ID, loan amount, sector, and vehicle data.
5. Build or mock the income payloads.
6. Run identity and income agents in parallel using `asyncio.gather()`.
7. Run the score agent.
8. Run the compliance agent.
9. Run the decision agent.
10. Persist the `Applicant` row and a `PIPELINE_COMPLETED` audit log.
11. Return a `LoanDecisionResponse`.

Important response fields:

- `applicant_id`
- `final_decision`
- `decision_reason`
- `credit_score`
- `compliance_flags`
- `monthly_income_npr`
- `income_sources`
- `doc_confidence`
- `verified_name`
- `citizenship_no`
- `land_parcels`
- `total_land_ropani`
- `total_land_aana`
- `pipeline_time_ms`

Database persistence details:

- The applicant row stores the client owner through `user_id`.
- If the final outcome is hard rejected, the row is marked with a system-reviewed explanation and timestamp.
- The audit log contains the decision, identity details, land details, income breakdown, SHAP explanation, bureau signals, and the user ID that initiated the request.

Loan route notes:

- The route defines a helper `build_income_breakdown()` that computes monthly averages and three-month totals per source.
- `sector` is forced to `vehicle_purchase` when the loan type is vehicle.
- `state.total_accumulated_income_npr` is set from the combined source breakdown.
- There is a duplicated `income_breakdown` and `total_accumulated_income_npr` entry in the audit payload; the later one overwrites the earlier value in Python dictionary construction.
- If DB commit fails, the route logs the error, rolls back, and still returns the computed decision.

### `api/routes/loan.py` Response Schema

`LoanDecisionResponse` is the structured pipeline output returned to the client application form. It is designed to provide enough information for the frontend result card and for later auditing.

## Authentication and Security

### `core/security.py`

This file handles JWT creation, JWT verification, and role enforcement.

#### `create_access_token(data)`

- Copies the payload.
- Adds an `exp` timestamp using the configured expiry window.
- Signs the token with `SECRET_KEY` using `HS256`.

#### `verify_token(credentials)`

- Expects `Authorization: Bearer <token>`.
- Decodes and verifies signature and expiry.
- Raises a single generic 401 error for all failure modes.

#### `require_role(required_role)`

- Returns a FastAPI dependency function.
- Verifies the token and ensures the payload role matches the requested role.
- Returns 403 when a client tries to access officer routes or vice versa.

Security philosophy:

- The same generic error message is used intentionally to reduce account or token enumeration risk.

### `services/auth_service.py`

This file contains reusable authentication logic.

#### Password helpers

- `verify_password(plain, hashed)` checks bcrypt hashes.
- `hash_password(plain)` creates bcrypt hashes.

#### `verify_google_token(token)`

- Calls Google’s token info endpoint.
- Checks that the returned `aud` matches the configured `google_client_id`.
- Returns `google_id`, `email`, and `full_name`.
- Raises 401 when Google token verification fails.

#### `get_or_create_client(google_data, db)`

- Searches for an existing user by `google_id`.
- If missing, checks whether the email already exists.
- Loads the `client` role.
- Creates a new client account with no password hash.

#### `authenticate_officer(email, password, db)`

- Searches by email.
- Rejects inactive accounts.
- Ensures a password hash exists.
- Verifies the password.
- Confirms the user has the `officer` role.

The authentication layer deliberately keeps routers thin and service logic centralized.

### `routers/auth.py`

This router exposes the user login and self-info endpoints.

Endpoints:

- `POST /auth/google`
- `POST /auth/officer/login`
- `GET /auth/me`

Helper:

- `build_login_response()` creates a standardized `LoginResponse` for both login flows.

Behavior:

- Google login verifies the Google token, gets or creates the client, loads the role, and returns a JWT plus user object.
- Officer login authenticates credentials and returns the same response shape.
- `/auth/me` validates the JWT and returns the current user profile, including role and active status.

### `schemas/auth.py`

This module defines the request and response schemas used by auth.

Request schemas:

- `GoogleLoginRequest` contains `google_token`.
- `OfficerLoginRequest` contains `email` and `password`.

Response schemas:

- `UserOut` includes `id`, `email`, `full_name`, `role`, `is_active`, and `created_at`.
- `LoginResponse` includes `jwt_token`, `token_type`, and `user`.

### `api/schemas.py`

This file contains a small shared schema module.

- `FieldResult` represents a value/confidence pair for extraction-style data.
- `ErrorResponse` standardizes error payloads.

## Web Routers

### `routers/client.py`

Client-facing dashboard routes.

Endpoints:

- `GET /client/applications`
- `GET /client/applications/{application_id}`
- `GET /client/applications/{application_id}/pdf`

Important design details:

- Every route requires the `client` role.
- Application ownership is enforced using the `user_id` from the JWT.
- Application detail pages reconstruct AI and bureau data from the audit log.

Client summary schema:

- Includes `id`, `loan_amount_npr`, `sector`, `status`, `submitted_at`, `reviewed_at`, and `officer_remarks`.

Client detail schema:

- Includes the application identity, asset, AI, compliance, income, and bureau data.

PDF endpoint details:

- Uses ReportLab.
- Converts UTC timestamps to Nepal Standard Time using a fixed `5:45` offset.
- Produces a multi-section PDF including identity, assets, loan details, income, AI assessment, compliance, and officer decision.

### `routers/officer.py`

Officer-facing dashboard routes.

Endpoints:

- `GET /officer/applications`
- `GET /officer/applications/{application_id}`
- `POST /officer/applications/{application_id}/decision`
- `GET /officer/applications/{application_id}/pdf`

Important behaviors:

- Officers can filter the queue by status.
- Application detail includes the same pipeline data reconstructed from `AuditLog`.
- The decision endpoint validates the decision value and remarks.
- Already final-reviewed applications cannot be reviewed again.
- The officer decision is persisted with `reviewed_by`, `reviewed_at`, and `officer_remarks`.
- Every officer action is logged in `AuditLog`.

The officer PDF route mirrors the client PDF route, but is oriented around review and audit.

### `routers/mock_gov.py`

This router simulates external government systems with SQLite-backed local datasets.

Mock systems:

- DoNIDCR for identity verification.
- NeLIS for land lookup.
- CIB for credit history lookup.

Shared patterns:

- Each database file lives under `mock_databases/`.
- The router reads SQLite files directly.
- It returns realistic HTTP statuses to simulate real government behavior.

#### DoNIDCR endpoint

- `POST /mock/donidcr/verify`
- Request includes `nin`.
- Response includes full identity fields and citizenship number.
- `404` means NIN not found.
- `410` means deceased/inactive.

#### NeLIS endpoint

- `POST /mock/nelis/lookup`
- Request includes `citizenship_no`.
- Returns all parcels for that citizenship number.
- Zero parcels is valid and returns a normal `200` response.
- The endpoint computes total parcels, total land area, and total asset value.

#### CIB endpoint

- `POST /mock/cib/lookup`
- Request includes `citizenship_no`.
- Returns prior loan records, blacklist status, DPD bucket, active loan count, and a simplified Nepal-style score.
- A blacklist forces a near-floor score.

The mock API is central to the demo because the Identity Agent depends on these endpoints exactly as it would depend on the real ones in production.

## Frontend System

### `frontend/assets/css/main.css`

This is the shared style foundation for the entire UI.

Design language:

- Typography uses `Outfit` for headings and `Plus Jakarta Sans` for body text.
- Primary color is a deep navy.
- Accent color is saffron/gold.
- The UI uses white surfaces, light borders, and soft shadows.

Reusable classes:

- `.rinsathi-card`
- `.badge-pending`
- `.badge-approved`
- `.badge-rejected`
- `.badge-referred`
- `.btn-primary`
- `.btn-accent`
- `.form-input`
- `.form-label`
- `.error-msg`
- `.spinner`
- `.icon`

The CSS file is the main visual system that keeps the landing page, login screens, dashboards, and application forms visually aligned.

### `frontend/assets/js/auth.js`

This file manages client-side auth state.

Responsibilities:

- Store JWT and user data in `localStorage`.
- Decode JWT payloads locally for UI routing.
- Check token expiry.
- Clear expired tokens.
- Logout and redirect to the appropriate login page.
- Wrap fetch calls with the Authorization header.

Important constants:

- `TOKEN_KEY = "rinsathi_jwt"`
- `USER_KEY = "rinsathi_user"`
- `API_BASE = window.location.origin + '/api/v1'`

Important behaviors:

- It does not verify JWT signatures in the browser; that remains a server-side responsibility.
- If a response returns 401, the helper clears auth and redirects to the client login page.

### `frontend/assets/js/guard.js`

This file protects role-gated pages.

Responsibilities:

- Verify the user is logged in.
- Verify the token is not expired.
- Verify the role matches the current page.
- Redirect users to the proper login page or dashboard.
- Populate the current user name in the navbar.

The guard is used by client and officer dashboard pages, loan application pages, and review pages.

## Landing And Login Pages

### `frontend/index.html`

The landing page is public and marketing-oriented.

Structure:

- Fixed top navbar.
- Hero section with an AI message and two calls to action.
- How-it-works section.
- Features section.
- Trust/compliance section.
- Call-to-action section.
- Footer.

Important claims presented on the page:

- Identity verification through DoNIDCR.
- Land verification through NeLIS.
- Five verification agents.
- Fast AI assessment time.
- NRB compliance positioning.

### `frontend/auth/login.html`

The client login page uses Google Identity Services.

Flow:

1. The user clicks the Google sign-in button.
2. Google returns a credential token.
3. The token is sent to `/api/v1/auth/google`.
4. The backend verifies the token and creates or finds the client account.
5. The returned JWT is stored in localStorage.
6. The client is redirected to the dashboard.

Notable UI elements:

- Hero-like login box.
- Loading overlay during backend verification.
- Error banner for failed sign-in.
- Link to officer login.

### `frontend/auth/officer_login.html`

The officer login page uses email and password.

Flow:

1. Officer enters credentials.
2. The credentials are posted to `/api/v1/auth/officer/login`.
3. The backend validates the account and role.
4. The JWT and user payload are stored in localStorage.
5. The officer is redirected to the officer dashboard.

It includes:

- A lock icon.
- Error banner.
- Enter-key submission support.
- Loading state on the login button.

## Client Frontend

### `frontend/templates/client/dashboard.html`

This page lists the client’s submitted applications.

Behavior:

- Guards for the `client` role.
- Fetches `/client/applications` on page load.
- Renders an empty state if the user has no applications.
- Shows a card for each application with amount, sector, status, score pill, dates, and officer remarks.
- Supports navigation to the application detail page and the apply form.

Visual features:

- Dark hero banner.
- Dashboard cards with status bars.
- Score pill colors based on credit score band.
- Officer remark block when present.

### `frontend/templates/client/apply.html`

This page is the client’s loan submission form.

Main sections:

- Identity Verification.
- Loan Details.
- Income Sources.
- Error message area.
- Submit section.
- Result card displayed after pipeline completion.

Important fields:

- NIN.
- Loan amount.
- Sector.
- Optional vehicle loan details.
- Optional income source amounts.

Special UI behavior:

- Toggle controls reveal the income amount fields.
- A NIN badge is shown as a visual helper.
- Submission triggers the full pipeline.
- The result card displays score, monthly income, land assets, compliance output, and processing time.
- The page redirects back to the dashboard after a short countdown.

The form is designed to illustrate the direct relationship between user input and the multi-agent backend pipeline.

### `frontend/templates/client/status.html`

This is the detailed application receipt page.

It renders:

- Identity record.
- Land asset record.
- Loan details.
- Income assessment.
- AI credit assessment.
- CIB assessment.
- NRB compliance flags.
- Officer remarks.
- A next-step panel for approved cases.

Important behaviors:

- The page reads the application ID from the URL query string.
- It fetches the application detail from the client API.
- It reconstructs the UI entirely from returned JSON.
- It offers PDF download for approved cases.

Visual logic:

- AI score is shown as a percentage bar.
- CIB score is shown on a 60–960 scale.
- Verdict banners change color based on recommendation.

### `frontend/templates/client/loan-guide.html`

This page explains the application criteria in a structured guide.

It documents:

- Identity and KYC expectations.
- Loan request constraints.
- Income proof requirements.
- Collateral coverage rules.
- Credit and compliance rules.
- Qualification scoring composition.
- Final decision bands.

The guide is a user-facing summary of the actual backend behavior and should remain aligned with the pipeline logic.

## Officer Frontend

### `frontend/templates/officer/dashboard.html`

The officer dashboard shows the application queue.

Behavior:

- Guards for `officer` role.
- Fetches all applications from `/officer/applications`.
- Renders stats cards for pending, referred, approved, and rejected counts.
- Supports filtering by status.
- Each application card links to the review page.

The dashboard emphasizes operational review rather than applicant self-service.

### `frontend/templates/officer/review.html`

This page is the officer’s full review workspace.

Rendered sections:

- Applicant information.
- Verified identity record.
- Land asset record.
- Income assessment.
- AI credit assessment.
- CIB assessment.
- NRB compliance flags.
- Previous officer review, if any.
- A right-hand decision panel.

Officer workflow:

1. Open an application from the queue.
2. Review identity, assets, income, score, compliance, and bureau data.
3. Write remarks.
4. Approve or reject.
5. The backend records the decision and the audit trail.

The page also supports PDF download for archival purposes.

## Mock Data And Seeders

### `mock_databases/README.md`

This file explains the purpose of the SQLite mock databases.

Key points:

- `donidcr.db` simulates DoNIDCR.
- `nelis.db` simulates NeLIS.
- The demo flow is NIN → identity registry → citizenship number → land registry.
- Production would replace mock endpoints with real government integrations.

### `mock_databases/seed_donidcr.py`

Creates and populates the mock identity database.

Highlights:

- Drops and recreates the `citizens` table.
- Inserts 50 citizen records.
- Stores NIN, full name, date of issue, nationality, date of birth, sex, permanent address, citizenship type, citizenship number, and status.
- Builds an index on `citizenship_no` for bridge queries.

Special records:

- `NID-049` is inactive/deceased for rejection demonstrations.
- `NID-050` is valid but has no land.

### `mock_databases/seed_nelis.py`

Creates and populates the mock land registry database.

Highlights:

- Drops and recreates the `land_parcels` table.
- Populates 80 land parcels across 50 citizens.
- Tracks district, land type, and estimated value.
- Uses district-based rates and land-type multipliers.
- Converts aana overflow into ropani for total area calculations.

Important design details:

- NeLIS is queried with citizenship number, not NIN.
- Zero parcels is valid and intentionally represented.

### `mock_databases/seed_cib.py`

Creates and populates the mock CIB database.

Highlights:

- Drops and recreates the `cib_records` table.
- Populates clean histories, active loans, DPD 30, DPD 60, DPD 90+, and blacklisted entries.
- Builds an index on `citizenship_no`.

Important demo cases:

- `NID-009` is blacklisted.
- `NID-013` demonstrates severe delinquency.
- `NID-005` demonstrates mild delinquency.
- Several citizens are intentionally absent from the table to simulate first-time borrowers.

### `mock_databases/update_citizens.py`

This script is a small SQLite maintenance helper that updates status values in the DoNIDCR database.

The current implementation appears to map binary status values to `active` and `deceased`, though the printed count queries use a mixed-case `Deceased` string. It is best treated as a utility script rather than core application logic.

### `check_cib.py`

A small standalone inspection script for the mock CIB database.

It:

- Connects to `mock_databases/cib.db`.
- Prints the total row count.
- Queries one specific citizenship number for inspection.

This is useful for quick local validation of mock data setup.

## Machine Learning

### `ml/train_model.py`

This script trains the credit scoring model.

Model family:

- `XGBClassifier` wrapped in a scikit-learn `Pipeline`.

Features:

- `loan_to_income_ratio`
- `loan_to_asset_ratio`
- `income_confidence`
- `num_income_sources`
- `sector_risk_weight`

Training details:

- Synthetic data is generated to reflect microfinance risk patterns.
- A train/test split of 80/20 is used.
- `StandardScaler` is applied before XGBoost.
- Evaluation metrics include accuracy, precision, recall, F1, ROC-AUC, confusion matrix, and classification report.
- The trained pipeline is saved to `ml/credit_model.joblib`.
- Metrics are saved to `ml/model_metrics.joblib`.

The script emphasizes honest evaluation on held-out data instead of a single training-only score.

### `utils/shap_formatter.py`

This helper converts feature contributions into readable explanations.

Behavior:

- Maps internal feature names to clean labels.
- Formats ratios as `x` multiples.
- Formats confidences and risk weights as percentages.
- Formats counts as integers.
- Converts contribution dictionaries into a list of dictionaries with `feature`, `readable_text`, and `shap_value`.

The file comments explicitly note that the return type matches the `SharedState.shap_explanation` contract.

## Income Parsing Utilities

### `utils/income_parsers.py`

This module defines the parsing and normalization path for all income sources.

#### Parsers

- `parse_esewa(data)` extracts income-style transactions only.
- `parse_remittance(data)` converts USD remittance records into NPR using the record’s exchange rate.
- `parse_cooperative(data)` converts monthly cooperative deposits into signals.

Each parser returns a tuple of signal list and a best-effort name for cross-checking.

#### Normalization

- `normalize_to_monthly_estimate(all_signals)` aggregates the signals into one estimate.
- It computes monthly means and standard deviation.
- It uses coverage, stability, and source diversity to compute confidence.
- It returns a structure with mean monthly NPR, std dev, confidence, months of data, low-confidence flag, sources, and source count.

Notable details:

- Remittances are averaged by month separately from regular monthly sources.
- Zero-signals input returns a minimum confidence of `0.1` instead of zero.
- The function is intentionally friendly to irregular and informal income formats common in microfinance workflows.

#### Cross-validation

- `check_name_consistency(doc_name, income_names)` compares tokenized names using a Jaccard-style overlap.
- It tolerates name format variation like initials or reordered tokens.

#### Mock data generators

- `generate_mock_esewa_data()` builds plausible transaction histories.
- `generate_mock_remittance_data()` builds plausible remittance records.
- `generate_mock_coop_data()` builds plausible savings group ledgers.

These generators support demo flows and testing.

## Tests

### `tests/test_identity_agent.py`

This script performs a simple end-to-end Identity Agent check.

Cases covered:

- Valid NIN with land assets.
- Deceased NIN.
- Non-existent NIN.
- Valid NIN with zero land.

The script prints the resulting verification fields so the operator can visually inspect the behavior.

### `tests/test_income_normalization.py`

This regression test validates that the income normalization behaves as expected for fixed monthly inputs.

It asserts:

- The monthly estimate sums the expected values.
- The returned sources are ordered as expected.

### `tests/test_score.html`

This is a browser-based score agent tester, not a Python unit test.

Behavior:

- Sends a sample payload to `/api/v1/income/analyze`.
- Displays score and probability values in the browser.
- Renders an explanation list.

It is useful as a quick manual UI harness for the ML/income scoring path.

## Documentation Generator

### `docs/generate_handbook_pdf.py`

This script converts `mid_defense_handbook.md` into a PDF.

Key behavior:

- Reads the markdown source file.
- Converts markdown into a line-based PDF stream.
- Applies simple parsing for headings, bullets, numbered items, code blocks, and separators.
- Writes the generated PDF to `RinSathi_Mid_Defense_Handbook.pdf`.

The script is intentionally lightweight and self-contained, which makes it suitable for offline report generation.

## Runtime Data Flow

### Client Application Flow

1. The client signs in with Google.
2. The client lands on the dashboard.
3. The client chooses to apply for a loan.
4. The apply form gathers NIN, loan amount, sector, loan type, optional vehicle details, and optional income amounts.
5. The request is posted to `/api/v1/loan/apply` with the JWT bearer token.
6. The backend validates identity, income, scoring, compliance, and decision logic.
7. The applicant row and audit log are saved.
8. The frontend renders the result and redirects to the dashboard.

### Officer Review Flow

1. The officer signs in with email and password.
2. The officer dashboard loads all applications.
3. The officer opens a specific application.
4. The review page shows the full AI and bureau context.
5. The officer writes remarks and approves or rejects.
6. The application status is updated and logged.
7. The client sees the result on their dashboard and detail page.

## Decision Logic Summary

The system’s final decision is not a single model output. It is a layered scorecard:

- Identity verifies who the person is.
- Income checks whether repayment signals are real and sufficiently diverse.
- Scoring estimates repayment probability.
- Compliance overrides any positive score when required by policy.
- The final weighted qualification score and manual review rules determine the displayed recommendation.

This layered design is deliberate because it mirrors how regulated lending organizations balance automation, policy enforcement, and human review.

## Security And Compliance Notes

- JWTs are signed and verified server-side.
- Role checks are enforced at the dependency layer.
- Officer actions require written remarks.
- Every major pipeline action is logged.
- The system avoids deleting users or audit data to preserve traceability.
- The mock CIB and land systems are intended for demo and defense use, not production deployment.
- The project positions itself around NRB-style compliance, auditability, and explainability.

## Operational Notes

- The app expects the async PostgreSQL connection to be available through `DATABASE_URL`.
- Mock databases must be seeded before the identity and land flows work locally.
- The Google OAuth client ID in `frontend/auth/login.html` must match the backend setting for real login flows.
- The PDF endpoints depend on ReportLab.
- The ML model file must exist under `ml/credit_model.joblib` for the score agent to produce live probabilities.

## File-Level Notes

This section records the purpose of each major file in compact form.

- `main.py`: application assembly, startup/shutdown, API registration, and the extra income-analysis bridge route.
- `config.py`: environment-driven application and policy configuration.
- `db/session.py`: async engine, session factory, table creation, and request dependency.
- `db/models.py`: ORM tables, enums, and relationships.
- `agents/shared_state.py`: pipeline contract object.
- `agents/identity_agent.py`: government identity, land, and CIB verification.
- `agents/income_agent.py`: multi-source income parsing and normalization.
- `agents/score_agent.py`: XGBoost score inference and explanation generation.
- `agents/compliance_agent.py`: deterministic policy checks.
- `agents/decision_agent.py`: final verdict selection and explanation.
- `api/routes/loan.py`: main loan application API.
- `api/routes/income.py`: income analysis API.
- `core/security.py`: JWT creation, verification, and role dependency.
- `services/auth_service.py`: Google token verification, client creation, officer auth.
- `routers/auth.py`: authentication endpoints.
- `routers/client.py`: client dashboard data and PDFs.
- `routers/officer.py`: officer queue, review, and PDFs.
- `routers/mock_gov.py`: fake government endpoints backed by SQLite.
- `schemas/auth.py`: login request/response shapes.
- `api/schemas.py`: shared request/response helpers.
- `utils/income_parsers.py`: parsers, normalization, and test data.
- `utils/shap_formatter.py`: plain-language explanation formatter.
- `ml/train_model.py`: model training and artifact generation.
- `docs/generate_handbook_pdf.py`: markdown-to-PDF generator.
- `mock_databases/seed_donidcr.py`: identity seed data.
- `mock_databases/seed_nelis.py`: land seed data.
- `mock_databases/seed_cib.py`: bureau seed data.
- `mock_databases/update_citizens.py`: data cleanup script.
- `check_cib.py`: quick CIB verification script.
- `frontend/index.html`: landing page.
- `frontend/auth/login.html`: client login UI.
- `frontend/auth/officer_login.html`: officer login UI.
- `frontend/assets/css/main.css`: design system.
- `frontend/assets/js/auth.js`: browser auth manager.
- `frontend/assets/js/guard.js`: browser route guard.
- `frontend/templates/client/apply.html`: loan application form.
- `frontend/templates/client/dashboard.html`: client queue dashboard.
- `frontend/templates/client/status.html`: client application detail page.
- `frontend/templates/client/loan-guide.html`: client criteria guide.
- `frontend/templates/officer/dashboard.html`: officer queue dashboard.
- `frontend/templates/officer/review.html`: officer review workspace.
- `tests/test_identity_agent.py`: identity agent smoke test.
- `tests/test_income_normalization.py`: normalization regression test.
- `tests/test_score.html`: browser-based scoring harness.

## Closing Notes

The current codebase is designed around transparency: every major step has a visible route, a visible state mutation, a visible audit log, and a visible frontend representation. The project is therefore well suited for a defense presentation because the backend logic, mock external systems, and operator dashboards all line up with the same data contract.

This markdown source can be used directly as the basis for a final report or passed through the PDF generator in `docs/generate_handbook_pdf.py`.

## Appendix A: File-By-File Detail

This appendix gives a more granular walkthrough of the main repository files. It is intentionally repetitive in places because the goal is to preserve implementation detail for later reporting and review.

### `main.py`

- Creates the FastAPI application object with title, description, version, and lifespan.
- Loads `settings = get_settings()` once at module import time.
- Defines the lifespan context manager that creates database tables on startup and disposes the engine on shutdown.
- Registers all route modules under `/api/v1`.
- Mounts the frontend directory as a static HTML site.
- Exposes the health endpoint.
- Creates a global `ScoreAgent` instance for reuse.
- Exposes a secondary income-analysis pipeline route directly in the app module.
- Prints local development URLs on startup, including Swagger docs and login pages.

### `config.py`

- Defines the `Settings` class that loads environment variables from `.env`.
- Centralizes every threshold and secret used by the pipeline.
- Keeps mock government URLs in the same place so the code can switch environments without changing agent logic.
- Caches the settings object with `lru_cache()` so repeated imports do not reread the environment.

### `db/session.py`

- Converts the configured PostgreSQL URL into an asyncpg-compatible URL.
- Builds the async SQLAlchemy engine with pooled connections.
- Enables SSL preference and disables prepared statement caching for Supabase pgBouncer compatibility.
- Defines `AsyncSessionLocal` as the request session factory.
- Defines the SQLAlchemy declarative base class used by all models.
- Implements `create_tables()` for startup table creation.
- Implements `get_db()` as the request-scoped session dependency.

### `db/models.py`

- Defines the loan status enum used throughout the application.
- Defines the document type enum used for stored file metadata.
- Stores roles in a normalized `roles` table rather than hardcoding role names everywhere.
- Stores all login-capable users in one table with either `google_id` or `password_hash` depending on account type.
- Stores the main applicant row with ownership, review metadata, timestamps, and status.
- Stores uploaded or extracted documents and OCR-style fields in the documents table.
- Stores every pipeline and officer event in the audit log table.
- Uses UUID primary keys consistently across all core entities.

### `agents/shared_state.py`

- Serves as the typed contract between all pipeline stages.
- Enforces assignment validation so agents cannot silently write wrong types.
- Carries identity, land, income, score, compliance, and decision fields in a single object.
- Preserves legacy field names where compatibility matters, even after the document-based workflow was removed.
- Includes vehicle-loan fields alongside the original land-secured microfinance fields.

### `agents/identity_agent.py`

- Verifies the NIN against the mock identity registry.
- Uses the returned citizenship number to query land and bureau data.
- Writes both authoritative identity fields and compatibility-oriented extracted fields.
- Converts land registry output into totals and a structured land summary.
- Looks up CIB records and populates delinquency and blacklist indicators.
- Estimates vehicle collateral when the application is for a vehicle loan.
- Degrades gracefully on any external failure instead of interrupting the pipeline.

### `agents/income_agent.py`

- Parses three distinct income channels.
- Normalizes heterogeneous records into one monthly estimate.
- Cross-checks identity name consistency against the names observed in income records.
- Penalizes confidence if names do not align.
- Writes monthly income, confidence, and source list back into shared state.
- Returns safe fallback values if anything unexpected happens.

### `agents/score_agent.py`

- Loads the trained XGBoost model from disk.
- Reconstructs the same ratio features used during training.
- Treats the credit score as a probability, not a scaled integer score.
- Builds a contribution list that becomes a human explanation.
- Uses the SHAP formatter helper to convert contributions into officer-friendly language.
- Falls back to neutral scoring if the model is unavailable or inference fails.

### `agents/compliance_agent.py`

- Clears the flag list at the start of each run.
- Applies KYC, income, collateral, sector, bureau, AML, and zero-income checks.
- Treats vehicle financing differently from land-secured microfinance.
- Uses threshold values from configuration instead of hardcoded constants.
- Appends all detected issues so the decision stage can decide between refer and reject.
- Never raises outward; it always returns a state object.

### `agents/decision_agent.py`

- Gives compliance the highest priority.
- Converts compliance flags into human-readable reasons.
- Distinguishes hard-reject flags from flags that only require manual review.
- Builds a weighted qualification score when no compliance issue blocks the path.
- Applies the configured approval and refer thresholds.
- Produces verbose decision reasons for audit and applicant visibility.

### `api/routes/loan.py`

- Receives the main loan submission form.
- Validates JWT identity before the request can proceed.
- Rejects duplicate active applications for the same client.
- Builds mock or direct income payloads from the submitted fields.
- Runs identity and income in parallel, then score, compliance, and decision in sequence.
- Persists both the application record and a rich audit payload.
- Returns the decision data needed by the frontend result card.

### `api/routes/income.py`

- Provides a dedicated endpoint for standalone income analysis.
- Accepts applicant ID plus one or more source payloads.
- Supports a mock-data mode for demos and debugging.
- Returns both summary and timing information.
- Exposes a mock-data endpoint that shows the expected payload shapes.

### `api/schemas.py`

- Provides a generic field/value confidence structure.
- Standardizes an error response format.
- Keeps lightweight API contracts separate from business logic.

### `core/security.py`

- Creates JWT access tokens with expiration.
- Verifies bearer tokens on protected requests.
- Encodes user ID, email, full name, role, and expiry in the token payload.
- Enforces route-level role access through a dependency factory.
- Uses a single generic unauthorized message for all token failures.

### `schemas/auth.py`

- Defines the Google login request contract.
- Defines the officer login request contract.
- Defines the safe user projection returned to the frontend.
- Defines the common login response that includes token and user payload.

### `services/auth_service.py`

- Verifies Google ID tokens against Google’s tokeninfo endpoint.
- Checks that the token audience matches the configured Google client ID.
- Creates client accounts on first login.
- Prevents duplicate accounts with the same email.
- Authenticates officers using bcrypt password hashes.
- Confirms officer role membership before allowing dashboard access.

### `routers/auth.py`

- Exposes client and officer login endpoints.
- Exposes a self-profile endpoint for the current user.
- Reuses the same login response builder for both auth modes.
- Keeps the router thin by pushing auth logic into the service module.

### `routers/client.py`

- Returns the client’s own application history only.
- Returns full application detail reconstructed from the audit log.
- Generates a detailed PDF version of the application.
- Converts timestamps to Nepal Standard Time for presentation.
- Uses ownership checks so a client cannot read another client’s data.

### `routers/officer.py`

- Returns the officer queue with optional status filtering.
- Returns full application detail for review.
- Accepts final officer decisions with mandatory remarks.
- Prevents re-reviewing applications that already reached a final status.
- Generates a detailed PDF for archival or print use.

### `routers/mock_gov.py`

- Simulates the DoNIDCR identity registry.
- Simulates the NeLIS land registry.
- Simulates the CIB credit bureau.
- Uses SQLite files under `mock_databases/`.
- Returns realistic HTTP statuses, including 404 and 410 for identity failures.
- Computes bureau score, land value, and aggregate totals server-side.

### `utils/income_parsers.py`

- Parses eSewa/Khalti-style transaction histories.
- Parses remittance transfer records and converts currency to NPR.
- Parses cooperative savings ledgers.
- Aggregates the signals into a monthly estimate and confidence score.
- Computes coverage, stability, and diversity metrics for the confidence value.
- Generates mock payloads for demo flows.

### `utils/shap_formatter.py`

- Converts model contribution data into readable narratives.
- Formats ratios, percentages, and counts appropriately.
- Returns a list of dictionaries that matches the shared state contract.
- Preserves feature name and contribution magnitude for audit readability.

### `ml/train_model.py`

- Generates synthetic training data that mirrors microfinance risk logic.
- Trains a pipeline with scaling plus XGBoost classification.
- Evaluates the model on held-out test data.
- Prints standard classification metrics and a confusion matrix.
- Saves the trained pipeline and the evaluation metrics as joblib artifacts.

### `docs/generate_handbook_pdf.py`

- Reads the markdown handbook source from disk.
- Converts markdown into paginated PDF text.
- Supports simple headings, bullets, numbered lists, and code blocks.
- Writes a standalone PDF file for defense use.

### `mock_databases/seed_donidcr.py`

- Drops and recreates the mock identity table.
- Inserts 50 citizens with realistic identity and address data.
- Keeps an index on citizenship number for bridge queries.
- Includes a deceased/inactive demo record and a zero-land demo record.

### `mock_databases/seed_nelis.py`

- Drops and recreates the mock land parcel table.
- Inserts 80 land parcel rows across the citizen base.
- Adds district, land type, and estimated value to each parcel.
- Applies district and land-type multipliers when calculating value.
- Normalizes land area so aana overflow is carried into ropani.

### `mock_databases/seed_cib.py`

- Drops and recreates the mock bureau table.
- Inserts clean, active, delinquent, and blacklisted records.
- Uses real-looking Nepali lender names and status values.
- Leaves some citizens without bureau rows to represent first-time borrowers.

### `mock_databases/update_citizens.py`

- Performs a small maintenance update on the DoNIDCR mock database.
- Appears intended for status cleanup or normalization.
- Is not part of the main runtime path.

### `check_cib.py`

- Opens the mock CIB database.
- Prints total row counts.
- Queries one fixed citizenship number for inspection.
- Serves as a quick data sanity script.

### `frontend/index.html`

- Acts as the public landing page.
- Explains the five-agent workflow and project value proposition.
- Provides client and officer login entry points.
- Includes a trust/compliance section and a marketing CTA section.
- Uses a dark, high-contrast hero section with saffron accents.

### `frontend/auth/login.html`

- Implements Google-based client authentication.
- Displays a loading overlay while the token is verified.
- Shows errors from backend login rejection.
- Redirects authenticated clients directly to the dashboard.

### `frontend/auth/officer_login.html`

- Implements email/password officer authentication.
- Supports Enter-key submission.
- Shows a spinner while credentials are checked.
- Redirects authenticated officers directly to the officer dashboard.

### `frontend/assets/css/main.css`

- Defines the project-wide visual system.
- Standardizes colors, typography, borders, shadows, buttons, inputs, cards, and badges.
- Provides the icon sizing rules used by multiple pages.
- Keeps the UI consistent across landing, auth, client, and officer screens.

### `frontend/assets/js/auth.js`

- Stores token and user info in browser localStorage.
- Decodes JWT payloads for local UI logic.
- Checks expiry before protected page rendering continues.
- Adds the bearer token to API requests automatically.
- Forces logout on a 401 response.

### `frontend/assets/js/guard.js`

- Blocks pages when the user is not authenticated.
- Blocks pages when the role does not match the required role.
- Redirects users to the correct login or dashboard page.
- Exposes a helper to display the current user’s name.

### `frontend/templates/client/apply.html`

- Presents the loan application form.
- Organizes the UI into identity, loan, and income sections.
- Supports toggles for multiple income sources.
- Displays a pipeline result card after submission.
- Sends form data to the backend using the shared API helper.

### `frontend/templates/client/dashboard.html`

- Shows the client’s submitted applications.
- Renders status badges, scores, dates, and officer remarks.
- Displays an empty state when no applications exist.
- Links to the loan guide and application form.

### `frontend/templates/client/status.html`

- Shows the full application detail page.
- Renders identity, asset, income, AI, compliance, bureau, and officer review data.
- Includes a PDF download button for approved applications.
- Uses the application’s status to control the hero banner and colors.

### `frontend/templates/client/loan-guide.html`

- Explains the user-facing rules before applying.
- Mirrors the actual backend decision bands and compliance concepts.
- Helps applicants understand the requirements before form submission.

### `frontend/templates/officer/dashboard.html`

- Shows the officer queue in card form.
- Provides status filter tabs.
- Displays queue statistics for pending, referred, approved, and rejected items.
- Sends the officer into the review page for a specific application.

### `frontend/templates/officer/review.html`

- Displays the full review workspace for one application.
- Separates applicant data from the decision panel.
- Shows the AI verdict, score gauge, bureau view, and compliance list.
- Requires remarks before final decision submission.
- Supports PDF download and post-review navigation.

### `tests/test_identity_agent.py`

- Runs a handful of smoke tests against the identity agent.
- Covers valid, deceased, missing, and zero-land cases.
- Prints the resulting state so the operator can inspect fields manually.

### `tests/test_income_normalization.py`

- Verifies that monthly source values normalize as expected.
- Checks the returned source ordering.
- Serves as a regression guard for the income aggregation path.

### `tests/test_score.html`

- Provides a browser-based ML/income scoring sandbox.
- Submits a sample payload to the backend.
- Displays score and explanation results in the page.
- Is useful for visual debugging and demo rehearsals.

## Appendix Summary

The repository is intentionally cohesive: each major file has a specific role, but the system only works because the contracts line up across files. The appendix above is meant to make those relationships explicit so the report can be derived later without needing to reconstruct the codebase again.