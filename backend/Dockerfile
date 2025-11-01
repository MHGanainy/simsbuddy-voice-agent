# Backend Orchestrator Dockerfile - Railway Compatible
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies: ffmpeg and supervisor for multi-process management
RUN apt-get update && \
    apt-get install -y supervisor ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy and install shared dependencies first (for better layer caching)
COPY requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy and install orchestrator dependencies
COPY orchestrator/requirements.txt /app/backend/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/orchestrator/requirements.txt

# Copy and install agent dependencies (needed for subprocess spawning)
COPY agent/requirements.txt /app/backend/agent/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/agent/requirements.txt

# Copy entire backend codebase to /app/backend (consistent with docker-compose volume mount)
COPY . /app/backend/

# Copy supervisor configuration
COPY supervisord.conf /app/supervisord.conf

# Create log directories (use /tmp for Railway ephemeral storage)
RUN mkdir -p /tmp/supervisor

# Set working directory to orchestrator (for uvicorn and celery commands)
WORKDIR /app/backend/orchestrator

# Expose port (Railway will inject $PORT at runtime)
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    C_FORCE_ROOT=true \
    PYTHONPATH=/app \
    PYTHON_SCRIPT_PATH=/app/backend/agent/voice_assistant.py

# Start supervisor (runs FastAPI + Celery worker + Celery beat)
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
