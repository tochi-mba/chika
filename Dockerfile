# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install system deps needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install runtime Python dependencies (cached separately from source changes)
# Using --no-deps on the final install avoids re-downloading deps on code changes.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    "uvicorn[standard]>=0.29.0" \
    websockets>=12.0 \
    pydantic>=2.7.0 \
    python-dotenv>=1.0.0 \
    openai>=1.30.0 \
    anthropic>=0.28.0 \
    httpx>=0.27.0 \
    ddgs>=9.0.0

# Copy application source
COPY . .

# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Install the local package itself without re-fetching dependencies
RUN pip install --no-cache-dir --no-deps .

# Data directories (mounted as volumes in production)
RUN mkdir -p data/sessions data/devices data/profiles

EXPOSE 8000

ENV CHIKA_PROVIDER=anthropic \
    PYTHONUNBUFFERED=1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
