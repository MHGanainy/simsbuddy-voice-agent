#!/bin/bash

# =============================================================================
# Local Celery Development Runner
# =============================================================================
# This script starts all components locally (without Docker) for development.
# Requires: Python 3.10+, Node.js 18+, Redis running on localhost:6379
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}==============================================================================${NC}"
echo -e "${GREEN}  Celery-Based Voice Agent Orchestrator - Local Development${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}ERROR: .env file not found!${NC}"
    echo -e "Please create .env file from .env.celery.example:"
    echo -e "${YELLOW}  cp .env.celery.example .env${NC}"
    echo -e "Then edit .env and add your API keys."
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Override paths for local development
export PYTHON_SCRIPT_PATH="$(pwd)/voice-assistant-project/voice_assistant.py"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

# Check Redis is running
echo -e "${YELLOW}[1/5] Checking Redis connection...${NC}"
if ! redis-cli -u "$REDIS_URL" ping > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Cannot connect to Redis at $REDIS_URL${NC}"
    echo -e "Please start Redis:"
    echo -e "${YELLOW}  brew services start redis     # macOS${NC}"
    echo -e "${YELLOW}  sudo systemctl start redis    # Linux${NC}"
    echo -e "${YELLOW}  docker run -p 6379:6379 redis:7-alpine  # Docker${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Redis is running${NC}"
echo ""

# Install Python dependencies
echo -e "${YELLOW}[2/5] Installing Python dependencies...${NC}"
cd voice-assistant-project
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Python dependencies installed${NC}"
echo ""

# Install Node.js dependencies
echo -e "${YELLOW}[3/5] Installing Node.js dependencies...${NC}"
cd orchestrator
if [ ! -d "node_modules" ]; then
    npm install
fi
echo -e "${GREEN}✓ Node.js dependencies installed${NC}"
echo ""

# Start Celery worker in background
echo -e "${YELLOW}[4/5] Starting Celery worker...${NC}"
celery -A tasks worker --beat --loglevel=info --concurrency=4 > celery.log 2>&1 &
CELERY_PID=$!
echo -e "${GREEN}✓ Celery worker started (PID: $CELERY_PID)${NC}"
echo -e "  Logs: tail -f orchestrator/celery.log"
echo ""

# Start Express API
echo -e "${YELLOW}[5/5] Starting Express API...${NC}"
echo -e "${GREEN}✓ Express API starting on port ${PORT:-8080}${NC}"
echo ""

echo -e "${GREEN}==============================================================================${NC}"
echo -e "${GREEN}  Services are running!${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo ""
echo -e "Express API:    http://localhost:${PORT:-8080}"
echo -e "Health check:   http://localhost:${PORT:-8080}/api/health"
echo ""
echo -e "Celery worker:  PID $CELERY_PID"
echo -e "Celery logs:    tail -f orchestrator/celery.log"
echo ""
echo -e "To stop:"
echo -e "  Press Ctrl+C to stop Express API"
echo -e "  Kill Celery: kill $CELERY_PID"
echo ""
echo -e "${YELLOW}Starting Express API...${NC}"
echo ""

# Trap Ctrl+C to cleanup
trap "echo ''; echo 'Stopping services...'; kill $CELERY_PID 2>/dev/null; echo 'Done'; exit" INT TERM

# Start Express API (foreground)
node celery-orchestrator.js
