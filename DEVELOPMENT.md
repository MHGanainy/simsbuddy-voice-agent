# Development Guide

Local development setup and workflow for the LiveKit voice assistant.

## Prerequisites

- **Docker + Docker Compose** (recommended)
- **Python 3.11+** (for local development without Docker)
- **Node 20+** (for frontend)
- **Redis** (included in Docker setup)
- **API Keys**: LiveKit, Groq, AssemblyAI, Inworld

## Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd livekit-demo
```

### 2. Environment Variables
```bash
# Copy template
cp .env.example .env

# Edit with your API keys
nano .env
```

**Required keys:**
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
- `GROQ_API_KEY`
- `ASSEMBLY_API_KEY`
- `INWORLD_API_KEY`

See [CONFIGURATION.md](CONFIGURATION.md) for all options.

### 3. Start Services

**Using Docker (Recommended):**
```bash
make dev        # Start with logs
make dev-d      # Start in background
```

**Or Docker Compose directly:**
```bash
docker-compose up --build
```

**Access:**
- Frontend: http://localhost:3000
- API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Makefile Commands

### Core Commands
```bash
make help       # Show all commands
make dev        # Start all services (attached)
make dev-d      # Start in background
make build      # Build Docker images
make stop       # Stop services
make restart    # Restart services
make clean      # Remove containers + volumes
```

### Logging
```bash
make logs                  # All services
make logs-orchestrator     # FastAPI logs
make logs-celery          # Celery worker logs
make logs-redis           # Redis logs
make logs-frontend        # Frontend logs
make logs-all             # Recent logs (last 50 lines)
```

### Voice Agent Logs
```bash
make logs-agent-files      # List agent log files
make logs-agent-live SESSION=xxx  # Follow live logs
make logs-agent-session SESSION=xxx  # View startup logs
make logs-agent            # Show running agents
```

### Utilities
```bash
make ps                   # Container status
make health              # Quick health check
make status              # Detailed status
make urls                # Show service URLs
make shell-orchestrator  # Bash into orchestrator
make shell-redis        # Redis CLI
```

### Redis
```bash
make redis-keys          # Show all Redis keys
make redis-sessions      # Show active sessions
make redis-stats        # Redis statistics
make redis-flush        # Flush database (⚠️ deletes all data)
```

## Running Without Docker

### Backend

**Terminal 1 - Redis:**
```bash
redis-server
```

**Terminal 2 - Orchestrator:**
```bash
cd backend

# Install dependencies
pip install -r requirements.txt
pip install -r orchestrator/requirements.txt
pip install -r agent/requirements.txt

# Set PYTHONPATH
export PYTHONPATH=/path/to/livekit-demo

# Start with Supervisor
supervisord -c supervisord.conf
```

**Terminal 3 - Frontend:**
```bash
cd frontend
npm install
npm run dev
```

### Manual Process Startup

If not using Supervisor:

```bash
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

## Testing

### Health Check
```bash
curl http://localhost:8000/health

# Expected:
# {"status":"healthy","redis_connected":true,...}
```

### Create Session
```bash
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "TestUser",
    "voiceId": "Ashley",
    "openingLine": "Hello! How can I help?",
    "systemPrompt": "You are a friendly assistant."
  }'

# Save sessionId from response
```

### End Session
```bash
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d '{"sessionId": "session_123"}'

# Returns duration: {durationSeconds: 125, durationMinutes: 3}
```

### API Docs
Visit: http://localhost:8000/docs (interactive Swagger UI)

## Daily Workflow

### Starting Your Day
```bash
make dev-d              # Start services
make health             # Verify everything works
```

### During Development
```bash
make logs-orchestrator  # Watch API logs
make logs-celery       # Watch worker logs
make logs-agent-live SESSION=xxx  # Watch specific agent
```

### Ending Your Day
```bash
make stop              # Stop services
```

## Debugging

### Check Services
```bash
make status            # Full status
make ps               # Container status
make logs-all         # Recent logs from all services
```

### Debug Specific Service
```bash
make logs-orchestrator    # API logs
make shell-orchestrator   # SSH into container
ps aux | grep voice_assistant.py  # Check agent processes
```

### Redis Debugging
```bash
make redis-sessions    # Active sessions
make redis-keys       # All keys
make shell-redis      # Open redis-cli
```

### Agent Debugging
```bash
# List all agent sessions
make logs-agent-files

# Follow live logs for specific session
make logs-agent-live SESSION=session_1761992887507_xyz

# View startup logs from Redis
make logs-agent-session SESSION=session_1761992887507_xyz
```

## Troubleshooting

### Services Won't Start

**Check:**
- Docker running?
- Ports 3000, 6379, 8000 available?
- `.env` file exists with valid API keys?

**Fix:**
```bash
make clean          # Clean everything
make build         # Rebuild images
make dev-d         # Start fresh
```

### No Audio in LiveKit

**Check:**
- Microphone permissions in browser?
- LiveKit credentials correct in `.env`?
- Browser console for WebRTC errors?

**Debug:**
```bash
make logs-orchestrator  # Check token generation
# Look for: "livekit_token_generated"
```

### Agent Not Responding

**Check:**
- Celery worker running?
- Redis connected?
- Agent process spawned?

**Debug:**
```bash
make logs-celery               # Celery logs
make shell-orchestrator        # SSH into container
ps aux | grep voice_assistant.py  # Check processes
make redis-sessions            # Check session state
```

### Redis Connection Issues

**Check:**
- Redis running? (`make ps`)
- Correct `REDIS_URL` in `.env`?

**Debug:**
```bash
make shell-redis    # Open redis-cli
PING                # Should return PONG
KEYS *              # List all keys
```

### Frontend Build Errors

**Check:**
- Node 20+ installed?
- Dependencies installed?

**Debug:**
```bash
cd frontend
npm install
npm run dev     # Check error output
```

## Development Tips

1. **Use Makefile** - Easier than Docker commands
2. **Check logs first** - Most issues visible in logs (`make logs-all`)
3. **Health endpoint** - Quick verification (`make health`)
4. **Redis debugging** - Check state (`make redis-sessions`)
5. **API docs** - Interactive testing at http://localhost:8000/docs

## Next Steps

- [Configure voice settings](CONFIGURATION.md)
- [API reference](backend/API.md)
- [Deploy to Railway](DEPLOYMENT.md)
- [Helper scripts](scripts/README.md)
