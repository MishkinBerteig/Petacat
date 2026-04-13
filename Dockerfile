# ── Stage 1: Build Python backend ──
FROM python:3.12-slim AS backend
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "sqlalchemy[asyncio]>=2.0" \
    "asyncpg>=0.30" \
    "alembic>=1.14" \
    "pydantic>=2.10" \
    "websockets>=14.0"

COPY server/ server/
COPY seed_data/ seed_data/
COPY alembic/ alembic/
COPY alembic.ini .

# ── Stage 2: Build React frontend ──
FROM node:22-alpine AS frontend
WORKDIR /app/client
COPY client/package.json client/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY client/ .
RUN npm run build

# ── Stage 3: Production image (minimal) ──
FROM python:3.12-slim AS production
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from backend stage
COPY --from=backend /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=backend /usr/local/bin/alembic /usr/local/bin/alembic

# Copy application code
COPY --from=backend /app/server /app/server
COPY --from=backend /app/seed_data /app/seed_data
COPY --from=backend /app/alembic /app/alembic
COPY --from=backend /app/alembic.ini /app/alembic.ini

# Copy built frontend
COPY --from=frontend /app/client/dist /app/static

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
