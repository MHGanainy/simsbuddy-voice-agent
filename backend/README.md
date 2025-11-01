# Backend - Voice Assistant Orchestrator & Agent

This directory contains the Python backend services for the LiveKit voice assistant project.

## Architecture

```
backend/
├── orchestrator/       # FastAPI server + Celery workers for session orchestration
│   ├── main.py        # FastAPI app - REST API for sessions and LiveKit tokens
│   ├── tasks.py       # Celery tasks - agent spawning, pool management, cleanup
│   └── celeryconfig.py # Celery configuration
└── agent/             # Voice assistant bot (Pipecat + LiveKit)
    └── voice_assistant.py  # Voice agent implementation
```

## Components

### 1. Orchestrator (`backend/orchestrator/`)

**FastAPI Server (`main.py`)**
- Generates LiveKit access tokens for sessions
- Manages session lifecycle (start, end, cleanup)
- Handles LiveKit webhooks for session events
- Provides health check endpoints

**Celery Workers (`tasks.py`)**
- Spawns voice agent processes via subprocess
- Maintains pre-warmed agent pool for faster connections
- Monitors agent health and cleans up stale sessions
- Tracks agent PIDs in Redis for lifecycle management

**Key Features:**
- Async task execution with Celery
- Redis for state management and task queuing
- Session tracking and cleanup
- LiveKit webhook validation
- Agent pool pre-warming

### 2. Agent (`backend/agent/`)

**Voice Assistant (`voice_assistant.py`)**
- Pipecat-based voice bot using LiveKit transport
- Speech-to-Text: AssemblyAI
- LLM: Groq (Llama models)
- Text-to-Speech: Inworld AI
- Smart turn detection for natural conversations
- Graceful shutdown handling

## API Endpoints

### Session Management

**POST `/api/token`**
Generate LiveKit access token for a session.
```json
Request:
{
  "sessionId": "session_123",
  "userId": "user_456"
}

Response:
{
  "token": "eyJhbGc...",
  "url": "wss://livekit.example.com"
}
```

**POST `/api/session/start`**
Start a voice assistant session.
```json
Request:
{
  "sessionId": "session_123",
  "userId": "user_456",
  "config": {
    "voice": "inworld-male-1",
    "systemPrompt": "You are a helpful assistant..."
  }
}

Response:
{
  "success": true,
  "sessionId": "session_123",
  "taskId": "celery-task-id"
}
```

**POST `/api/session/end`**
End a session and cleanup agent.
```json
Request:
{
  "sessionId": "session_123"
}

Response:
{
  "success": true,
  "message": "Session ended successfully"
}
```

**POST `/livekit/webhook`**
LiveKit webhook endpoint (authenticated with webhook secret).

**GET `/health`**
Health check endpoint.

**GET `/stats`**
System statistics (sessions, agents, pool status).

## Environment Variables

### Required

**LiveKit Credentials:**
- `LIVEKIT_URL` - LiveKit server URL
- `LIVEKIT_API_KEY` - LiveKit API key
- `LIVEKIT_API_SECRET` - LiveKit API secret

**AI Service API Keys:**
- `GROQ_API_KEY` - Groq API key for LLM
- `ASSEMBLY_API_KEY` - AssemblyAI API key for STT
- `INWORLD_API_KEY` - Inworld AI API key for TTS

**Redis:**
- `REDIS_URL` - Redis connection URL (default: `redis://localhost:6379/0`)

### Optional

**Orchestrator Configuration:**
- `MAX_BOTS` - Maximum concurrent bots (default: 50)
- `SESSION_TIMEOUT` - Session timeout in ms (default: 1800000)
- `BOT_STARTUP_TIMEOUT` - Agent startup timeout in seconds (default: 30)
- `PREWARM_POOL_SIZE` - Pre-warmed agent pool size (default: 3)

**Internal Paths:**
- `PYTHON_SCRIPT_PATH` - Path to voice_assistant.py (default: `/app/backend/agent/voice_assistant.py`)
- `PYTHONPATH` - Python module search path (default: `/app`)

## Dependencies

### Shared (`requirements.txt`)
- python-dotenv - Environment variable management
- loguru - Logging
- aiohttp - Async HTTP client
- redis - Redis client

### Orchestrator (`orchestrator/requirements.txt`)
- fastapi - Web framework
- uvicorn - ASGI server
- celery - Distributed task queue
- livekit-api - LiveKit SDK

### Agent (`agent/requirements.txt`)
- pipecat-ai[livekit] - Voice agent framework
- assemblyai - Speech-to-text
- groq - LLM (Llama models)
- torch, transformers - ML dependencies for VAD
- onnxruntime - Optimized inference

## Development

### Running Locally

1. Install dependencies:
```bash
cd backend
pip install -r requirements.txt
pip install -r orchestrator/requirements.txt
pip install -r agent/requirements.txt
```

2. Set environment variables:
```bash
export LIVEKIT_URL="wss://your-livekit-server.com"
export LIVEKIT_API_KEY="your-api-key"
export LIVEKIT_API_SECRET="your-api-secret"
export GROQ_API_KEY="your-groq-key"
export ASSEMBLY_API_KEY="your-assembly-key"
export INWORLD_API_KEY="your-inworld-key"
export REDIS_URL="redis://localhost:6379/0"
export PYTHONPATH=/path/to/project/root
```

3. Start Redis:
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

4. Run orchestrator (FastAPI + Celery):
```bash
cd backend/orchestrator

# Terminal 1: FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Celery worker
celery -A tasks worker --loglevel=info

# Terminal 3: Celery beat (scheduled tasks)
celery -A tasks beat --loglevel=info
```

### Testing Agent Spawning

```bash
# Test voice assistant directly
cd backend/agent
python voice_assistant.py \
  --url wss://your-livekit-server.com \
  --token "your-access-token" \
  --session-id "test-session"
```

## Architecture Details

### Session Flow

1. **Client requests token** → POST `/api/token`
2. **Orchestrator generates LiveKit token** with session metadata
3. **Client starts session** → POST `/api/session/start`
4. **Celery task spawns agent** as subprocess
5. **Agent connects to LiveKit** room and starts conversation
6. **Client ends session** → POST `/api/session/end`
7. **Orchestrator terminates agent** and cleans up Redis state

### Agent Pool Management

- **Pre-warmed Pool**: Celery beat task maintains N ready agents
- **Faster Connection**: Pre-warmed agents connect immediately
- **Health Checks**: Periodic tasks verify agent processes are running
- **Cleanup**: Stale sessions are automatically cleaned up after timeout

### State Management (Redis)

**Session Data:**
```
session:{sessionId} → {
  "userId": "user_123",
  "status": "active",
  "agentPid": 12345,
  "createdAt": 1234567890,
  "config": {...}
}
```

**Agent PID Tracking:**
```
agent:{sessionId}:pid → "12345"
```

**Session Logs:**
```
session:{sessionId}:logs → ["log1", "log2", ...]
```

## Troubleshooting

### Common Issues

**1. Import errors: "No module named 'backend.orchestrator'"**
- Ensure `PYTHONPATH=/app` is set
- Verify `__init__.py` files exist in all packages

**2. Agent spawn failures**
- Check `PYTHON_SCRIPT_PATH` points to correct location
- Verify all AI API keys are set
- Check Redis connection

**3. Celery tasks not executing**
- Verify Redis is running and accessible
- Check Celery worker logs
- Ensure `celeryconfig.py` is loaded correctly

**4. LiveKit connection errors**
- Verify `LIVEKIT_URL` is accessible
- Check API key/secret are correct
- Ensure token is not expired

## Monitoring

### Logs

When running in Docker with supervisor:
- FastAPI: `/var/log/supervisor/fastapi.log`
- Celery Worker: `/var/log/supervisor/celery-worker.log`
- Celery Beat: `/var/log/supervisor/celery-beat.log`

### Metrics

Check `/stats` endpoint for:
- Active sessions count
- Pre-warmed agent pool status
- Redis connection status
- Agent process counts

## Production Deployment

See root `README.md` for deployment instructions.

Key considerations:
- Set appropriate `MAX_BOTS` based on server capacity
- Configure `PREWARM_POOL_SIZE` based on expected traffic
- Monitor Redis memory usage
- Use process manager (supervisor) for resilience
- Implement proper logging and monitoring
