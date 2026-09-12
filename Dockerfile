# Trendora Backend API Container (FastAPI)
# Reference only — optional future deployment (local container testing or cloud
# hosting). Not required for normal local development (see docs/DEPLOYMENT.md).

FROM python:3.12-slim

WORKDIR /app

# System libraries: gcc + libpq for building/using psycopg against PostgreSQL.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and application source.
COPY pyproject.toml .
COPY src/trendora ./src/trendora

# Install the package with dev extras (includes the FastAPI runtime deps).
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Bind on all interfaces inside the container. Override with -e UVICORN_PORT=...
CMD ["uvicorn", "trendora.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# Build:  docker build -t trendora-api .
# Run:    docker run --env-file .env -p 8000:8000 trendora-api
# Deploy: see docs/DEPLOYMENT.md
