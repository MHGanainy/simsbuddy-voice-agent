# Backend Orchestrator Dockerfile - FastAPI Server Only
FROM python:3.11-slim

WORKDIR /app

# Install minimal system dependencies for orchestrator
# - supervisor: Process manager for FastAPI
# - curl: Health checks and debugging
RUN apt-get update && \
    apt-get install -y supervisor curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy and install shared dependencies first (for better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy and install orchestrator dependencies only
# Note: Includes Celery as a client for publishing tasks to worker queue
COPY backend/orchestrator/requirements.txt /app/backend/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/orchestrator/requirements.txt

# Copy entire backend codebase to /app/backend (consistent with docker-compose volume mount)
COPY backend/ /app/backend/

# Copy supervisor configuration
COPY backend/supervisord.conf /app/supervisord.conf

# Create log directories (use /tmp for Railway ephemeral storage)
RUN mkdir -p /tmp/supervisor

# Set working directory to orchestrator (for uvicorn commands)
WORKDIR /app/backend/orchestrator

# Expose port (Railway will inject $PORT at runtime)
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Health check: Verify FastAPI is responding
# Check every 30s, timeout after 5s, start checking after 10s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start supervisor (runs FastAPI only - workers run in separate service)
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
