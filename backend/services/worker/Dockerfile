# Worker Service Dockerfile - Celery Workers + Agent Spawning
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing and ML models
# - ffmpeg: Audio/video processing for voice agents
# - supervisor: Process manager for Celery worker + beat
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

# Copy and install worker-specific dependencies (includes Celery + agent deps)
COPY backend/services/worker/requirements.txt /app/backend/services/worker/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/services/worker/requirements.txt

# Copy entire backend codebase to maintain monorepo structure
# This ensures all imports work correctly (backend.shared, backend.agent, etc.)
COPY backend/ /app/backend/

# Copy worker supervisord configuration
COPY backend/services/worker/supervisord.conf /app/supervisord.conf

# Create directories for logs and temporary files
RUN mkdir -p /var/log/voice-agents /tmp/supervisor

# Set working directory to worker (for celery commands in supervisord)
WORKDIR /app/backend/services/worker

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    C_FORCE_ROOT=true \
    PYTHONPATH=/app \
    PYTHON_SCRIPT_PATH=/app/backend/agent/voice_assistant.py \
    AGENT_LOG_DIR=/var/log/voice-agents

# Health check: Verify Celery worker is responding
# Check every 60s, timeout after 15s, start checking after 90s (for startup)
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD python3 /app/backend/services/worker/healthcheck.py || exit 1

# Start supervisor (runs Celery worker + Celery beat)
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
