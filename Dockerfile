# ── Base image ────────────────────────────────────────────────────────────
# Slim Python 3.12 on Debian — small footprint, matches your local Python version
FROM python:3.12-slim

# ── System dependencies ──────────────────────────────────────────────────
# psycopg2 needs the PostgreSQL client library to compile/run correctly
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory inside the container ───────────────────────────────
WORKDIR /app

# ── Install Python dependencies first ─────────────────────────────────────
# Copying requirements before the rest of the code means Docker can cache
# this layer — if only your code changes (not dependencies), rebuilds are
# much faster since this expensive step gets skipped.
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# ── Copy the rest of the application code ─────────────────────────────────
COPY . .

# ── Expose the port FastAPI/Uvicorn will listen on ────────────────────────
EXPOSE 8000

# ── Startup command ────────────────────────────────────────────────────────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]