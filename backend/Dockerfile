# Dockerfile - Orchestrator + Worker in One Container
# Runs FastAPI server, Celery worker, and Celery beat together
FROM python:3.11-slim

WORKDIR /app

# Install all system dependencies (orchestrator + worker)
# - supervisor: Process manager for FastAPI + Celery
# - ffmpeg: Audio/video processing for voice agents
# - build-essential, git: Required for building Python ML packages
# - libsndfile1: Audio file I/O (required by pipecat)
# - curl: Health checks and debugging
RUN apt-get update && \
    apt-get install -y \
        supervisor \
        ffmpeg \
        libsndfile1 \
        build-essential \
        git \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy and install shared dependencies first (for better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy and install orchestrator dependencies
COPY backend/services/orchestrator/requirements.txt /app/backend/services/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/services/orchestrator/requirements.txt

# Copy and install worker dependencies
COPY backend/services/worker/requirements.txt /app/backend/services/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/services/worker/requirements.txt

# Copy entire backend codebase to /app/backend
COPY backend/ /app/backend/

# Copy  supervisor configuration
COPY backend/supervisord.conf /app/supervisord.conf

# Create log directories
RUN mkdir -p /var/log/voice-agents /tmp/supervisor

# Set working directory to backend root
WORKDIR /app/backend

# Expose orchestrator port
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    C_FORCE_ROOT=true \
    PYTHONPATH=/app \
    PYTHON_SCRIPT_PATH=/app/backend/agent/voice_assistant.py \
    AGENT_LOG_DIR=/var/log/voice-agents

# Health check: Verify both FastAPI and Celery are responding
# We'll check FastAPI health endpoint since it's more reliable
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/orchestrator/health || exit 1

# Start supervisor (runs FastAPI + Celery worker + Celery beat)
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
