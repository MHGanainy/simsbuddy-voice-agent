# LiveKit Voice Assistant - Monorepo

Production-ready voice assistant system using LiveKit, Pipecat, and modern AI services.

## Overview

This is a full-stack voice assistant application featuring:
- **Real-time voice conversations** using LiveKit WebRTC
- **AI-powered agent** with Pipecat framework (STT, LLM, TTS)
- **Dynamic system prompts** for customizable AI personalities per session
- **Conversation history tracking** with opening line memory
- **Duration tracking** for billing and analytics (seconds + minutes)
- **Session orchestration** with FastAPI + Celery
- **React frontend** for voice configuration and testing
- **Agent pool management** for instant connections

## Architecture

```
livekit-demo/
├── backend/                    # Python services
│   ├── orchestrator/          # FastAPI + Celery orchestration
│   │   ├── main.py           # REST API server
│   │   ├── tasks.py          # Celery workers
│   │   └── celeryconfig.py   # Celery config
│   ├── agent/                # Voice assistant bot
│   │   └── voice_assistant.py # Pipecat bot
│   ├── common/               # Shared utilities
│   │   └── logging_config.py # Structured logging
│   ├── Dockerfile            # Backend container image
│   └── supervisord.conf      # Railway process manager config
├── frontend/                  # React application
│   ├── src/                  # React components
│   └── Dockerfile            # Frontend container image
├── supervisord.conf          # Local dev process manager config
├── docker-compose.yml        # Local development orchestration
├── Makefile                  # Development commands
└── RAILWAY_DEPLOYMENT.md     # Railway deployment guide
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- LiveKit Cloud account or self-hosted LiveKit server
- API keys for:
  - Groq (LLM)
  - AssemblyAI (STT)
  - Inworld AI (TTS)

### 1. Clone and Configure

```bash
git clone <repository-url>
cd livekit-demo
```

### 2. Set Environment Variables

Create `.env` file in the root directory:

```bash
# LiveKit Configuration
LIVEKIT_URL=wss://your-livekit-server.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret

# AI Service API Keys
GROQ_API_KEY=your-groq-api-key
ASSEMBLY_API_KEY=your-assemblyai-api-key
INWORLD_API_KEY=your-inworld-api-key

# Redis (auto-configured in docker-compose)
REDIS_URL=redis://redis:6379/0
```

See `.env.example` for all available options.

### 3. Start Services

Using Makefile (recommended):
```bash
# Start all services in development mode
make dev

# Or start in production mode (detached)
make up

# Stop all services
make down

# View logs
make logs
```

Or using Docker Compose directly:
```bash
# Start all services (Redis, Orchestrator, Frontend)
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

### 4. Access the Application

- **Frontend**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Services

### Backend (Port 8000)

**Orchestrator** - FastAPI server with Celery workers
- Generates LiveKit access tokens
- Spawns voice agent processes
- Manages session lifecycle
- Handles LiveKit webhooks
- Pre-warms agent pool for instant connections

**Agent** - Pipecat-based voice bot
- AssemblyAI for speech-to-text (with configurable STT parameters)
- Groq (Llama) for language model (with configurable LLM parameters)
- Inworld AI for text-to-speech (with voice-specific speed optimization)
- Smart turn detection for natural conversations
- **Centralized configuration section** for all agent parameters
- **Critical rules** automatically appended to all system prompts

### Frontend (Port 3000)

React application for:
- Voice assistant configuration
- Real-time voice chat interface
- Session management
- Voice selection and settings

### Redis (Port 6379)

- Message broker for Celery
- Session state storage
- Agent pool tracking

## API Endpoints

### Session Management

```bash
# Generate LiveKit token
POST /api/token
{
  "sessionId": "session_123",
  "userId": "user_456"
}

# Start voice session (NEW: systemPrompt, openingLine, duration tracking)
POST /orchestrator/session/start
{
  "userName": "user_456",
  "voiceId": "Ashley",
  "openingLine": "Hello! I'm your AI assistant.",
  "systemPrompt": "You are a helpful customer service agent."
}

# End session (returns duration for billing)
POST /orchestrator/session/end
{
  "sessionId": "session_123"
}
# Response includes:
{
  "success": true,
  "message": "Session ended and cleaned up",
  "details": {
    "durationSeconds": 125,
    "durationMinutes": 3
  }
}

# Health check
GET /health

# System stats
GET /stats
```

## New Features (v2.0.0)

### 1. Dynamic System Prompts

Customize the LLM's behavior and personality per session by providing a custom system prompt.

**Usage:**
```bash
POST /orchestrator/session/start
{
  "userName": "user123",
  "systemPrompt": "You are a friendly customer service agent for ACME Corp."
}
```

**Default:** If not provided, uses: "You are a helpful AI voice assistant."

**Use Cases:**
- Customer service agents with company-specific instructions
- Technical support specialists with troubleshooting guidelines
- Educational tutors with subject-specific teaching styles
- Sales assistants with product knowledge

### 2. Opening Line in Conversation History

The opening greeting is now added to the LLM's conversation context, ensuring the AI "remembers" what it said when greeting the user.

**Usage:**
```bash
POST /orchestrator/session/start
{
  "userName": "user123",
  "openingLine": "Welcome to ACME support! How can I help you today?",
  "systemPrompt": "You are a support agent. Remember you already greeted the user."
}
```

**Benefit:** Users can ask "What did you just say?" and get an accurate response.

### 3. Conversation Duration Tracking

Tracks conversation time from first participant join to session end for billing and analytics.

**Features:**
- Stores `conversationStartTime` when user joins
- Calculates duration on session end
- Returns both seconds and minutes (rounded up for billing)
- Integrates with Celery for real-time billing enforcement

**Response from `/session/end`:**
```json
{
  "details": {
    "durationSeconds": 125,
    "durationMinutes": 3
  }
}
```

**Billing Integration:**
- Celery can read `conversationStartTime` from Redis every 60s
- Minutes rounded UP (math.ceil) for "1 credit per minute" model
- Duration stored in Redis for audit/logging

## Development

### Local Development (Without Docker)

**Backend:**

```bash
# Install dependencies
cd backend
pip install -r requirements.txt
pip install -r orchestrator/requirements.txt
pip install -r agent/requirements.txt

# Set PYTHONPATH
export PYTHONPATH=/path/to/livekit-demo

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Terminal 1: FastAPI
cd backend/orchestrator
uvicorn main:app --reload --port 8000

# Terminal 2: Celery Worker
cd backend/orchestrator
celery -A tasks worker --loglevel=info

# Terminal 3: Celery Beat
cd backend/orchestrator
celery -A tasks beat --loglevel=info
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

### Project Structure

```
backend/
├── __init__.py                # Package marker
├── requirements.txt           # Shared dependencies
├── Dockerfile                 # Backend container image
├── supervisord.conf           # Railway process manager (uses $PORT)
├── common/
│   ├── __init__.py
│   └── logging_config.py     # Structured logging
├── orchestrator/
│   ├── __init__.py
│   ├── main.py               # FastAPI app
│   ├── tasks.py              # Celery tasks
│   ├── celeryconfig.py       # Celery config
│   └── requirements.txt      # Orchestrator deps
└── agent/
    ├── __init__.py
    ├── voice_assistant.py    # Voice bot
    └── requirements.txt      # Agent deps

frontend/
├── src/
│   ├── App.tsx              # Main component
│   ├── DevTools.tsx         # Development tools
│   ├── VoiceSettings.tsx    # Voice configuration UI
│   ├── types.ts             # TypeScript types
│   ├── logger.ts            # Frontend logging
│   └── styles.css           # Global styles
├── Dockerfile               # Frontend container image
├── package.json
├── vite.config.ts
└── README.md                # Frontend-specific docs
```

## Configuration

### Environment Variables

**Required:**
- `LIVEKIT_URL` - LiveKit server WebSocket URL
- `LIVEKIT_API_KEY` - LiveKit API key
- `LIVEKIT_API_SECRET` - LiveKit API secret
- `GROQ_API_KEY` - Groq API key
- `ASSEMBLY_API_KEY` - AssemblyAI API key
- `INWORLD_API_KEY` - Inworld AI API key

**Optional:**
- `REDIS_URL` - Redis connection URL (default: redis://localhost:6379/0)
- `MAX_BOTS` - Max concurrent bots (default: 50)
- `SESSION_TIMEOUT` - Session timeout in ms (default: 1800000)
- `BOT_STARTUP_TIMEOUT` - Agent startup timeout in seconds (default: 30)
- `PREWARM_POOL_SIZE` - Pre-warmed agent pool size (default: 3)

### Voice Configuration

Available voices (Inworld AI) with speed optimization:
- `Ashley` - Default voice (Female, 1.0x speed)
- `Craig` - Professional male (1.2x speed)
- `Edward` - Smooth, natural male (1.0x speed)
- `Olivia` - Clear, professional female (1.0x speed)
- `Wendy` - Energetic female (1.2x speed)
- `Priya` - Asian accent female (1.0x speed)

**Agent Configuration:**
All voice parameters are centralized in `backend/agent/voice_assistant.py` (lines 44-115) for easy tuning:
- Voice-specific speed overrides
- TTS temperature and streaming settings
- STT parameters (AssemblyAI)
- LLM parameters (Groq)
- Context aggregator timeouts
- Critical rules (automatically appended to all system prompts)

## Deployment

### Docker Compose (Recommended)

```bash
# Production build
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Clean up volumes
docker-compose down -v
```

### Railway / Cloud Platforms

The project is configured for easy deployment to Railway, Render, or similar platforms.

**Services to deploy:**
1. **Redis** - Use managed Redis service (or existing Railway Redis)
2. **Backend Orchestrator** - Configure with:
   - Root Directory: `/` (repo root)
   - Dockerfile Path: `/backend/Dockerfile`
   - Builder: Dockerfile
3. **Frontend** - Configure with:
   - Root Directory: `/` (repo root)
   - Dockerfile Path: `/frontend/Dockerfile`
   - Builder: Dockerfile

**Environment Variables:**
- **Backend**: Set all variables from `.env.railway.example`
- **Frontend**: Set `VITE_API_URL` to your backend service URL

See `RAILWAY_DEPLOYMENT.md` for detailed Railway setup instructions and troubleshooting.

## Monitoring & Logs

### Docker Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f orchestrator
docker-compose logs -f frontend
docker-compose logs -f redis
```

### Application Logs

Inside orchestrator container:
- `/var/log/supervisor/fastapi.log` - FastAPI server
- `/var/log/supervisor/celery-worker.log` - Celery worker
- `/var/log/supervisor/celery-beat.log` - Celery beat

### Metrics

Check system stats:
```bash
curl http://localhost:8000/stats
```

Response includes:
- Active sessions
- Pre-warmed agent count
- Redis status
- Agent pool health

## Troubleshooting

### Common Issues

**1. Agent fails to spawn**
- Verify all AI API keys are set
- Check `PYTHON_SCRIPT_PATH` points to `/app/backend/agent/voice_assistant.py`
- Review Celery worker logs

**2. Import errors**
- Ensure `PYTHONPATH=/app` is set in environment
- Verify `__init__.py` files exist in all Python packages

**3. Frontend can't connect to backend**
- Check `VITE_API_URL` environment variable (should point to backend URL)
- Verify orchestrator is running on port 8000
- Check CORS settings in `backend/orchestrator/main.py`
- For Railway: Ensure frontend has `VITE_API_URL` set to backend service URL

**4. LiveKit connection errors**
- Verify `LIVEKIT_URL` is accessible
- Check API key/secret are correct
- Ensure firewall allows WebSocket connections

**5. Redis connection errors**
- Verify Redis is running: `docker-compose ps redis`
- Check Redis health: `docker exec voice-agent-redis redis-cli ping`
- Verify `REDIS_URL` is correct

### Debug Mode

Enable debug logging:

```bash
# In docker-compose.yml, add to orchestrator environment:
LOG_LEVEL: debug

# Or run locally with:
uvicorn main:app --reload --log-level debug
celery -A tasks worker --loglevel=debug
```

## Performance Tuning

### Agent Pool Size

Adjust `PREWARM_POOL_SIZE` based on:
- Expected concurrent users
- Server resources
- Connection patterns

Recommendation: Start with 3, increase if connections are slow.

### Celery Concurrency

Adjust worker concurrency in `supervisord.conf`:
```
command=celery -A tasks worker --loglevel=info --concurrency=4
```

Increase concurrency for more parallel agent spawns.

### Session Timeout

Adjust `SESSION_TIMEOUT` to clean up idle sessions:
```
SESSION_TIMEOUT: 1800000  # 30 minutes in milliseconds
```

## Testing

### Test Backend API

```bash
# Health check
curl http://localhost:8000/health

# Get token
curl -X POST http://localhost:8000/api/token \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"test-123","userId":"user-1"}'

# Start session
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId":"test-123",
    "userId":"user-1",
    "config":{"voice":"inworld-male-1"}
  }'

# Check stats
curl http://localhost:8000/stats
```

### Test Voice Agent

```bash
# Direct agent test (requires LiveKit token)
docker exec voice-agent-orchestrator python /app/backend/agent/voice_assistant.py \
  --url $LIVEKIT_URL \
  --token "your-test-token" \
  --session-id "test-session"
```

## Contributing

See `backend/README.md` for backend architecture details.

## License

MIT

## Support

For issues, questions, or contributions, please open an issue on GitHub.
