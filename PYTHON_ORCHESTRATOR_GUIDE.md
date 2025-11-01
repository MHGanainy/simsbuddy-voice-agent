# Python FastAPI Orchestrator Guide

## Overview

This guide covers the new Python FastAPI orchestrator that replaces the Node.js Express orchestrator. The Python version provides the same functionality with a simpler, more unified tech stack.

## What Changed

### Before (Node.js)
- **Orchestrator**: Node.js + Express
- **Port**: 8080
- **Dockerfile**: `Dockerfile.orchestrator`
- **Stack**: Node.js + Python (mixed)

### After (Python)
- **Orchestrator**: Python + FastAPI
- **Port**: 8000
- **Dockerfile**: `Dockerfile.orchestrator-python`
- **Stack**: Pure Python

## Files Created/Modified

### New Files
1. **`voice-assistant-project/orchestrator/main.py`**
   - FastAPI application
   - Endpoints: `/api/session/start`, `/api/session/end`, `/health`
   - LiveKit token generation using `livekit-api` Python package
   - Celery task integration

2. **`Dockerfile.orchestrator-python`**
   - Python 3.10 base image
   - Supervisor for multi-process management (FastAPI + Celery worker + Celery beat)
   - Exposes port 8000

3. **`PYTHON_ORCHESTRATOR_GUIDE.md`** (this file)

### Modified Files
1. **`voice-assistant-project/requirements.txt`**
   - Added: `fastapi==0.109.0`
   - Added: `uvicorn[standard]==0.27.0`
   - Added: `livekit-api==0.6.1`

2. **`docker-compose.celery.yml`**
   - Changed Dockerfile: `Dockerfile.orchestrator-python`
   - Changed port mapping: `8000:8000` (was `8080:8080`)
   - Changed healthcheck URL: `http://localhost:8000/health`
   - Changed frontend API URL: `http://localhost:8000`

## Architecture

```
┌─────────────────────────────────────────┐
│   Docker Container: orchestrator        │
│                                         │
│  ┌────────────────────────────────┐    │
│  │  Supervisor (Process Manager)  │    │
│  └────────────────────────────────┘    │
│           │                             │
│           ├─► FastAPI (port 8000)       │
│           │   - POST /api/session/start │
│           │   - POST /api/session/end   │
│           │   - GET /health             │
│           │                             │
│           ├─► Celery Worker             │
│           │   - spawn_voice_agent       │
│           │   - health_check_agents     │
│           │   - cleanup_stale_agents    │
│           │                             │
│           └─► Celery Beat               │
│               - prewarm_agent_pool      │
│                                         │
└─────────────────────────────────────────┘
         │
         ▼
    Redis (Message Broker)
```

## API Endpoints

### 1. POST /api/session/start

Start a new voice assistant session.

**Request:**
```json
{
  "userName": "John Doe",
  "voiceId": "Ashley",
  "openingLine": "Hello! How can I help you today?"
}
```

**Response:**
```json
{
  "success": true,
  "sessionId": "session_1730462400000_abc123xyz",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "serverUrl": "wss://your-instance.livekit.cloud",
  "roomName": "session_1730462400000_abc123xyz",
  "message": "Session created. Voice agent is being spawned."
}
```

### 2. POST /api/session/end

End a voice assistant session.

**Request:**
```json
{
  "sessionId": "session_1730462400000_abc123xyz"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Session session_1730462400000_abc123xyz end acknowledged. Note: Cleanup not yet implemented."
}
```

### 3. GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "livekit_url": "wss://your-instance.livekit.cloud",
  "livekit_configured": true,
  "celery_available": true
}
```

## Setup and Testing

### Prerequisites

1. **Environment Variables**

Create a `.env` file in the project root with:

```bash
# LiveKit Configuration
LIVEKIT_URL=wss://your-instance.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

# AI Service API Keys
GROQ_API_KEY=your_groq_api_key
ASSEMBLY_API_KEY=your_assemblyai_api_key
INWORLD_API_KEY=your_inworld_api_key

# Redis Configuration
REDIS_URL=redis://localhost:6379/0
```

### Step 1: Start the Services

```bash
# Make sure you're in the project root
cd /Users/elganayni/mg/livekit-demo

# Start all services (Redis + Orchestrator + Frontend)
docker-compose -f docker-compose.celery.yml up --build
```

**Expected Output:**
```
voice-agent-redis         | Ready to accept connections
voice-agent-orchestrator  | INFO:     Started server process
voice-agent-orchestrator  | INFO:     Uvicorn running on http://0.0.0.0:8000
voice-agent-orchestrator  | [celery] Connected to redis://redis:6379/0
voice-agent-frontend      | VITE ready in 500ms
```

### Step 2: Test Health Check

```bash
curl http://localhost:8000/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "livekit_url": "wss://your-instance.livekit.cloud",
  "livekit_configured": true,
  "celery_available": true
}
```

### Step 3: Test Session Start

```bash
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "TestUser",
    "voiceId": "Ashley",
    "openingLine": "Hello! This is a test."
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "sessionId": "session_1730462400000_abc123xyz",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MzA0Njk2MDAsImlzcyI6IkFQSUxpZm0zbXhLSk1keCIsIm5iZiI6MTczMDQ2MjQwMCwic3ViIjoiVGVzdFVzZXIiLCJ2aWRlbyI6eyJjYW5QdWJsaXNoIjp0cnVlLCJjYW5QdWJsaXNoRGF0YSI6dHJ1ZSwiY2FuU3Vic2NyaWJlIjp0cnVlLCJyb29tIjoic2Vzc2lvbl8xNzMwNDYyNDAwMDAwX2FiYzEyM3h5eiIsInJvb21Kb2luIjp0cnVlfX0.xxx",
  "serverUrl": "wss://your-instance.livekit.cloud",
  "roomName": "session_1730462400000_abc123xyz",
  "message": "Session created. Voice agent is being spawned."
}
```

### Step 4: Verify Celery Task

Check the orchestrator logs to see the Celery task being triggered:

```bash
docker logs voice-agent-orchestrator -f
```

**Expected Log Output:**
```
[Session] Started session session_1730462400000_abc123xyz for user TestUser
[Session] Celery task ID: 12345678-1234-1234-1234-123456789abc
[Session] Voice: Ashley, Opening line: Hello! This is a test.

[celery] Task spawn_voice_agent[12345678-1234-1234-1234-123456789abc] received
[celery] Spawning agent for session session_1730462400000_abc123xyz
[celery] Command: ['python3', '/app/voice-assistant-project/voice_assistant.py', '--room', 'session_1730462400000_abc123xyz', '--voice-id', 'Ashley', '--opening-line', 'Hello! This is a test.']
```

### Step 5: Test Session End

```bash
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "session_1730462400000_abc123xyz"
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "message": "Session session_1730462400000_abc123xyz end acknowledged. Note: Cleanup not yet implemented."
}
```

## Interactive API Documentation

FastAPI provides automatic interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

You can test all endpoints directly from the browser!

## Troubleshooting

### Issue: "Module 'tasks' not found"

**Solution:** Make sure you're running from the `orchestrator` directory:
```bash
cd voice-assistant-project/orchestrator
uvicorn main:app --reload
```

### Issue: "livekit-api not installed"

**Solution:** Install dependencies:
```bash
pip install -r requirements.txt
```

### Issue: Port 8000 already in use

**Solution:** Stop existing services or change the port in `docker-compose.celery.yml`:
```bash
# Check what's using port 8000
lsof -i :8000

# Stop Docker containers
docker-compose -f docker-compose.celery.yml down
```

### Issue: Celery tasks not running

**Solution:** Verify Redis is running and Celery worker is connected:
```bash
# Check Redis
docker logs voice-agent-redis

# Check Celery worker logs
docker exec voice-agent-orchestrator cat /var/log/supervisor/celery-worker.log
```

## Development Workflow

### Local Development (without Docker)

1. **Start Redis:**
   ```bash
   docker run -d -p 6379:6379 redis:7-alpine
   ```

2. **Start Celery Worker:**
   ```bash
   cd voice-assistant-project/orchestrator
   celery -A tasks worker --loglevel=info
   ```

3. **Start Celery Beat:**
   ```bash
   cd voice-assistant-project/orchestrator
   celery -A tasks beat --loglevel=info
   ```

4. **Start FastAPI:**
   ```bash
   cd voice-assistant-project/orchestrator
   uvicorn main:app --reload --port 8000
   ```

### Testing with curl

Save this as `test-session.sh`:

```bash
#!/bin/bash

# Test health check
echo "Testing health endpoint..."
curl http://localhost:8000/health
echo -e "\n"

# Start session
echo "Starting session..."
RESPONSE=$(curl -s -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "TestUser",
    "voiceId": "Ashley",
    "openingLine": "Hello from test script!"
  }')

echo $RESPONSE | jq .
SESSION_ID=$(echo $RESPONSE | jq -r '.sessionId')
echo -e "\nSession ID: $SESSION_ID\n"

# Wait 5 seconds
echo "Waiting 5 seconds..."
sleep 5

# End session
echo "Ending session..."
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d "{\"sessionId\": \"$SESSION_ID\"}"
echo -e "\n"
```

Make it executable and run:
```bash
chmod +x test-session.sh
./test-session.sh
```

## Next Steps

1. **Implement session cleanup** in `POST /api/session/end`:
   - Kill voice agent process
   - Clean up Redis state
   - Disconnect from LiveKit room

2. **Add session status endpoint** (`GET /api/session/:id`):
   - Poll for agent readiness
   - Return current session state

3. **Add authentication**:
   - JWT tokens
   - User management

4. **Add monitoring**:
   - Prometheus metrics
   - Grafana dashboards

5. **Add tests**:
   - Unit tests for endpoints
   - Integration tests for Celery tasks

## Comparison with Node.js Version

| Feature | Node.js | Python FastAPI |
|---------|---------|----------------|
| Language | JavaScript | Python |
| Framework | Express | FastAPI |
| Port | 8080 | 8000 |
| Token Generation | `livekit-server-sdk` | `livekit-api` |
| API Docs | None | Auto-generated (Swagger) |
| Type Safety | None | Pydantic models |
| Async Support | Callbacks | async/await |
| Pre-warming | ✅ | ❌ (not yet implemented) |
| Rate Limiting | ✅ | ❌ (not yet implemented) |
| Session Cleanup | ✅ | ❌ (not yet implemented) |

## Conclusion

The Python FastAPI orchestrator provides a simpler, more unified architecture while maintaining compatibility with the existing Celery worker infrastructure. The migration path is straightforward, and the automatic API documentation makes it easier to integrate with frontend applications.
