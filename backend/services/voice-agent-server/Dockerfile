# Standalone Voice Agent Server Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# - ffmpeg: Audio/video processing
# - libsndfile1: Audio file I/O (required by pipecat)
# - build-essential, git: Required for building Python ML packages
# - curl: Health checks
RUN apt-get update && \
    apt-get install -y \
        ffmpeg \
        libsndfile1 \
        build-essential \
        git \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy and install base backend requirements
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy and install voice agent requirements (pipecat, ML models, etc.)
COPY backend/agent/requirements.txt /app/backend/agent/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/agent/requirements.txt

# Copy and install voice-agent-server requirements
COPY backend/services/voice-agent-server/requirements.txt /app/backend/services/voice-agent-server/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/services/voice-agent-server/requirements.txt

# Copy entire backend codebase (needed for shared modules and voice agent)
COPY backend/ /app/backend/

# Set working directory
WORKDIR /app/backend/services/voice-agent-server

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AGENT_SCRIPT_PATH=/app/backend/agent/voice_assistant.py \
    SERVER_PORT=8001

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the server
CMD ["python3", "main.py"]
