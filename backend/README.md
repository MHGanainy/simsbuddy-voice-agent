# Backend - Voice Assistant Orchestrator & Agent

This directory contains the Python backend services for the LiveKit voice assistant project.

## Architecture

```
backend/
├── common/            # Shared utilities
│   ├── __init__.py
│   └── logging_config.py # Structured logging (console/JSON)
├── orchestrator/      # FastAPI server + Celery workers for session orchestration
│   ├── main.py        # FastAPI app - REST API for sessions and LiveKit tokens
│   ├── tasks.py       # Celery tasks - agent spawning, pool management, cleanup
│   └── celeryconfig.py # Celery configuration
├── agent/             # Voice assistant bot (Pipecat + LiveKit)
│   └── voice_assistant.py # Voice agent implementation
├── Dockerfile         # Backend container image (multi-process)
└── supervisord.conf   # Process manager for Railway (PORT-aware)
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
- **NEW: Dynamic system prompts** per session
- **NEW: Opening line conversation history** tracking
- **NEW: Duration tracking** for billing (seconds + minutes)

### 2. Agent (`backend/agent/`)

**Voice Assistant (`voice_assistant.py`)**
- Pipecat-based voice bot using LiveKit transport
- Speech-to-Text: AssemblyAI (fully configurable with 12 parameters)
- LLM: Groq (Llama models, configurable with 7 parameters)
- Text-to-Speech: Inworld AI (voice-specific speed optimization)
- Smart turn detection for natural conversations
- Graceful shutdown handling
- **Centralized configuration section** (lines 44-115) for all agent parameters
- **Critical rules** automatically appended to all system prompts

**Agent Configuration Section:**
Located in `voice_assistant.py` lines 44-115, includes:
- Context Aggregator Settings (timeouts for responses and interruptions)
- TTS Configuration (streaming, temperature, voice-specific speeds)
- STT Configuration (AssemblyAI parameters: sample rate, encoding, model, VAD, confidence)
- LLM Configuration (Groq: model, streaming, tokens, temperature, penalties)
- Critical Rules (static rules for TTS-friendly responses)

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

**POST `/orchestrator/session/start`**
Start a voice assistant session with optional customization.
```json
Request:
{
  "userName": "user_456",
  "voiceId": "Ashley",                    # Optional (default: "Ashley")
  "openingLine": "Hello! Welcome!",       # Optional (default: auto-generated)
  "systemPrompt": "You are a helpful..."  # Optional (default: generic assistant)
}

Response:
{
  "success": true,
  "sessionId": "session_1762018728198_xyz",
  "token": "eyJhbGc...",
  "serverUrl": "wss://...",
  "roomName": "session_1762018728198_xyz",
  "message": "Session created. Voice agent is being spawned."
}
```

**POST `/orchestrator/session/end`**
End a session and cleanup agent. Returns conversation duration for billing.
```json
Request:
{
  "sessionId": "session_123"
}

Response:
{
  "success": true,
  "message": "Session session_123 ended and cleaned up",
  "details": {
    "session_id": "session_123",
    "celery_task_revoked": true,
    "process_killed": true,
    "redis_cleaned": true,
    "durationSeconds": 125,        # NEW: Total conversation time in seconds
    "durationMinutes": 3,           # NEW: Rounded up for billing (math.ceil)
    "errors": []
  }
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

## Agent Configuration (v2.1.0)

### Centralized Configuration Section

All agent parameters are now centralized in `voice_assistant.py` (lines 44-115) for easy tuning without code changes:

**Location:** `backend/agent/voice_assistant.py` lines 44-115

**Configuration Categories:**

1. **Context Aggregator Settings**
   - `AGGREGATION_TIMEOUT = 0.2` - Response completion wait time
   - `BOT_INTERRUPTION_TIMEOUT = 0.2` - Interruption response time

2. **TTS Configuration (Inworld)**
   - `TTS_STREAMING = True` - Enable streaming
   - `TTS_TEMPERATURE = 1.1` - Voice expressiveness (0.0-2.0)
   - `TTS_DEFAULT_SPEED = 1.0` - Default speech rate
   - `VOICE_SPEED_OVERRIDES` - Voice-specific speeds:
     - Craig: 1.2x (faster)
     - Edward: 1.0x (normal)
     - Olivia: 1.0x (normal)
     - Wendy: 1.2x (faster)
     - Priya: 1.0x (normal)
     - Ashley: 1.0x (default)

3. **STT Configuration (AssemblyAI)**
   - Sample rate, encoding, model selection
   - VAD parameters (confidence, silence thresholds)
   - Transcript formatting options

4. **LLM Configuration (Groq)**
   - Model selection (llama-3.3-70b-versatile)
   - Streaming, max tokens, temperature
   - Top-p, presence/frequency penalties

5. **Critical Rules** (Static, Non-Negotiable)
   - Automatically appended to ALL system prompts
   - Ensures TTS-friendly responses:
     - No stage directions or actions
     - Only supported emotion tags
     - Short, conversational responses (1-2 sentences)
     - Natural speech without scene descriptions

**Benefits:**
- Single source of truth for all agent behavior
- Easy parameter tuning without code changes
- Consistent configuration across all sessions
- Well-documented with inline comments

### Critical Rules Enforcement

The `CRITICAL_RULES` constant (lines 90-113) is **automatically appended** to every system prompt, regardless of custom user prompts. This ensures consistent, TTS-friendly responses:

```python
# In voice_assistant.py
full_system_prompt = f"{base_prompt}\n\n{CRITICAL_RULES}"
```

**Rules enforced:**
- ✅ No stage directions (e.g., "looks anxious")
- ✅ No actions in asterisks (e.g., *sighs*, *pauses*)
- ✅ Only supported emotion tags: [happy], [sad], [angry], [surprised], [fearful], [disgusted]
- ✅ Short responses (1-2 sentences max)
- ✅ Natural, conversational speech

## New Features (v2.0.0)

### 1. Dynamic System Prompts

Allows customization of the LLM's system prompt per session for different AI personalities and behaviors.

**Implementation:**
- `main.py`: Accepts `systemPrompt` in `SessionStartRequest` model
- `main.py`: Stores in Redis (`user:{userName}:config` and `session:{sessionId}`)
- `tasks.py`: Fetches from Redis and passes to agent via command-line arg
- `voice_assistant.py`: Accepts `--system-prompt` arg and uses in LLM context initialization

**Default:** "You are a helpful AI voice assistant."

**Example:**
```bash
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "user123",
    "systemPrompt": "You are a technical support agent. Provide clear, step-by-step troubleshooting instructions."
  }'
```

### 2. Opening Line in Conversation History

Adds the opening greeting to the LLM's conversation context, ensuring the AI "remembers" what it said.

**Implementation:**
- `voice_assistant.py:174-179`: Appends opening line to initial messages array
- LLM sees: `[{role: "system", content: "..."}, {role: "assistant", content: opening_line}]`
- Pipecat's `LLMContext` maintains this in conversation history

**Benefit:** Users can ask "What did you just say?" and the LLM responds accurately.

**Technical Details:**
- Opening line passed via `--opening-line` command-line argument
- Added to context BEFORE first user utterance
- Persists throughout conversation session

### 3. Conversation Duration Tracking

Tracks conversation time from first participant join to session end for billing and analytics.

**Implementation:**
- `voice_assistant.py:212-222`: Stores `conversationStartTime` in Redis on first participant join
- `voice_assistant.py:275-296`: Calculates duration on cleanup (finally block)
- `main.py:204-218`: Extracts duration from Redis and returns in cleanup response
- Uses `math.ceil()` to round up minutes for billing

**Redis Fields:**
- `conversationStartTime` - Unix timestamp (when user joins room)
- `conversationDuration` - Total seconds
- `conversationDurationMinutes` - Rounded up minutes (for "1 credit per minute" billing)

**Billing Integration:**
```python
# Celery task can read from Redis every 60s for enforcement
start_time = redis_client.hget(f'session:{session_id}', 'conversationStartTime')
if start_time and (time.time() - int(start_time)) > user_credit_limit * 60:
    # Terminate session, user out of credits
    cleanup_session(session_id)
```

**Error Handling:**
- Duration tracking failures logged, don't crash agent
- Missing start time → duration = 0
- Redis connection failures handled gracefully

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
  "userName": "user_123",
  "userId": "user_123",
  "voiceId": "Ashley",
  "openingLine": "Hello! Welcome!",                    # NEW
  "systemPrompt": "You are a helpful assistant...",    # NEW
  "status": "active",
  "agentPid": 12345,
  "createdAt": 1234567890,
  "startTime": 1234567890,
  "conversationStartTime": 1234567900,                 # NEW: First participant join
  "conversationDuration": 125,                         # NEW: Total seconds
  "conversationDurationMinutes": 3,                    # NEW: Rounded up for billing
  "celeryTaskId": "task-id",
  "logFile": "/var/log/voice-agents/session_xyz.log"
}
```

**User Configuration:**
```
user:{userName}:config → {
  "voiceId": "Ashley",
  "openingLine": "Hello! Welcome!",
  "systemPrompt": "You are a helpful assistant...",    # NEW
  "updatedAt": 1234567890
}
```

**Agent PID Tracking:**
```
agent:{sessionId}:pid → "12345"
```

**Session Logs:**
```
agent:{sessionId}:logs → ["log1", "log2", ...]   # List (last 100 entries)
```

**Session Sets:**
```
session:ready → ["session_1", "session_2", ...]       # Ready sessions
session:starting → ["session_3", ...]                 # Starting sessions
pool:ready → ["session_4", ...]                       # Pre-warmed agent pool
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

## Docker Deployment

### Local Development (docker-compose)

From the project root:

```bash
# Start all services
docker-compose up --build

# Or use Makefile
make dev       # Development mode with logs
make up        # Detached mode
make down      # Stop services
make logs      # View logs
```

### Docker Build Details

The backend Dockerfile:

1. **Base Image**: `python:3.11-slim`
2. **System Dependencies**: ffmpeg, supervisor, curl
3. **Python Dependencies**: Installed in layers for caching:
   - Shared dependencies (`backend/requirements.txt`)
   - Orchestrator dependencies (`backend/orchestrator/requirements.txt`)
   - Agent dependencies (`backend/agent/requirements.txt`)
4. **Process Manager**: Supervisord runs 3 processes:
   - FastAPI (uvicorn)
   - Celery worker
   - Celery beat

**Build Context**: Repository root (`.`) - this allows the Dockerfile to copy from `backend/` subdirectory.

```bash
# Manual build from project root
docker build -f backend/Dockerfile -t backend:latest .

# Run container
docker run -p 8000:8000 \
  -e PORT=8000 \
  -e REDIS_URL=redis://localhost:6379/0 \
  -e LIVEKIT_URL=wss://... \
  # ... other env vars
  backend:latest
```

### Railway Deployment

**Configuration:**
- Root Directory: `/`
- Dockerfile Path: `/backend/Dockerfile`
- Builder: Dockerfile

**Environment Variables:**
Set all required variables from `.env.railway.example`:
- LiveKit credentials (LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
- AI service keys (GROQ_API_KEY, ASSEMBLY_API_KEY, INWORLD_API_KEY)
- Redis URL from Railway Redis service
- PORT is automatically injected by Railway

**Process Management:**
- Supervisord manages all 3 processes (FastAPI, Celery worker, Celery beat)
- `backend/supervisord.conf` uses `%(ENV_PORT)s` to work with Railway's injected PORT
- Logs are sent to stdout/stderr for Railway visibility

See `../RAILWAY_DEPLOYMENT.md` for complete setup guide.

## Production Deployment

Key considerations:
- Set appropriate `MAX_BOTS` based on server capacity (default: 50)
- Configure `PREWARM_POOL_SIZE` based on expected traffic (default: 3)
- Monitor Redis memory usage and set appropriate maxmemory policy
- Use process manager (supervisor) for resilience
- Implement proper logging (JSON format for production: `LOG_FORMAT=json`)
- Configure log aggregation (Railway automatically captures stdout/stderr)
- Set up health check monitoring (`/health` endpoint)
- Use managed Redis service (e.g., Railway Redis) with persistence enabled
