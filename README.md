# LiveKit Voice Assistant

Production-ready voice assistant system using LiveKit, Pipecat, and modern AI services.

## Overview

Real-time voice conversations powered by:
- **LiveKit WebRTC** - Real-time voice infrastructure
- **Pipecat Framework** - Voice agent orchestration
- **Dynamic System Prompts** - Customizable AI personalities
- **Duration Tracking** - Conversation billing/analytics
- **Agent Pool Management** - Instant connections

## Architecture

```
Frontend (React) → Orchestrator (FastAPI + Celery) → Voice Agent (Pipecat)
                            ↓
                         Redis
```

### Components

**Frontend** (`frontend/`)
- React + Vite + TypeScript
- LiveKit client for WebRTC
- Real-time log viewer
- Voice selection interface

**Orchestrator** (`backend/orchestrator/`)
- FastAPI REST API (port 8000)
- Celery workers for session management
- LiveKit token generation
- Session lifecycle management

**Voice Agent** (`backend/agent/`)
- Pipecat pipeline: STT → LLM → TTS
- AssemblyAI for speech-to-text
- Groq LLM (llama-3.3-70b-versatile)
- Inworld for text-to-speech
- 6 voice options with speed control

**Redis**
- Session state storage
- Celery message broker
- Duration tracking

## Quick Start

### Prerequisites

- Docker and Docker Compose
- API keys: LiveKit, Groq, AssemblyAI, Inworld

### 1. Clone and Configure

```bash
git clone <repository-url>
cd livekit-demo
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start Services

```bash
# Using Makefile (recommended)
make dev

# Or Docker Compose
docker-compose up --build
```

### 3. Access

- **Frontend**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Features

- ✅ Real-time voice conversations via LiveKit
- ✅ Dynamic system prompts (customize AI behavior per session)
- ✅ Multiple voices with speed control (Craig, Edward, Olivia, Wendy, Priya, Ashley)
- ✅ Opening line in conversation context (LLM remembers greeting)
- ✅ Duration tracking (for billing: seconds + minutes)
- ✅ Structured logging with session correlation
- ✅ Async cleanup (non-blocking)
- ✅ Graceful disconnect handling

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend  | React + Vite + TypeScript + LiveKit |
| API       | FastAPI + Pydantic |
| Workers   | Celery + Celery Beat |
| Voice AI  | Pipecat framework |
| STT       | AssemblyAI (universal-streaming) |
| LLM       | Groq (llama-3.3-70b-versatile) |
| TTS       | Inworld (6 voices) |
| Storage   | Redis |
| Container | Docker + Docker Compose |
| Deploy    | Railway |

## API Endpoints

### Start Session

```bash
POST /api/session/start
{
  "userName": "user123",
  "voiceId": "Ashley",
  "openingLine": "Hello! How can I help?",
  "systemPrompt": "You are a helpful assistant."
}
```

**Response:**
```json
{
  "sessionId": "session_123...",
  "token": "eyJ...",
  "serverUrl": "wss://...",
  "roomName": "session_123..."
}
```

### End Session

```bash
POST /api/session/end
{"sessionId": "session_123"}
```

**Response:**
```json
{
  "success": true,
  "details": {
    "durationSeconds": 125,
    "durationMinutes": 3
  }
}
```

### Health Check

```bash
GET /health
```

See [backend/API.md](backend/API.md) for complete API reference.

## Project Structure

```
backend/
├── orchestrator/    # FastAPI API + Celery workers
├── agent/          # Pipecat voice assistant
└── common/         # Shared logging & utilities

frontend/           # React dev UI
scripts/           # Helper scripts (Railway SSH, logs)

docker-compose.yml # Local development
Makefile          # Development commands
```

## Development

### Quick Commands

```bash
make dev              # Start all services
make logs             # View all logs
make logs-orchestrator # FastAPI logs only
make logs-celery      # Celery worker logs
make stop             # Stop services
make clean            # Remove containers & volumes
```

### Local Setup

**With Docker:**
```bash
make dev-d          # Start in background
make health         # Verify services
```

**Without Docker:**
```bash
# Redis
redis-server

# Backend
cd backend
pip install -r requirements.txt
pip install -r orchestrator/requirements.txt
pip install -r agent/requirements.txt
supervisord -c supervisord.conf

# Frontend
cd frontend
npm install
npm run dev
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed setup.

## Configuration

### Environment Variables

**Required:**
```bash
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxx
LIVEKIT_API_SECRET=secretxxxxx
GROQ_API_KEY=gsk_xxxxx
ASSEMBLY_API_KEY=xxxxx
INWORLD_API_KEY=xxxxx
REDIS_URL=redis://localhost:6379/0
```

**Optional:**
```bash
MAX_BOTS=50                  # Max concurrent agents
SESSION_TIMEOUT=1800000      # 30 minutes
PREWARM_POOL_SIZE=3          # Pre-warmed agents
LOG_LEVEL=INFO               # Logging level
```

See [CONFIGURATION.md](CONFIGURATION.md) for all options.

### Voice Configuration

Available voices (Inworld):
- **Ashley** - Default (Female, 1.0x speed)
- **Craig** - Professional male (1.2x speed)
- **Edward** - Smooth male (1.0x speed)
- **Olivia** - Professional female (1.0x speed)
- **Wendy** - Energetic female (1.2x speed)
- **Priya** - Asian accent female (1.0x speed)

Agent configuration: `backend/agent/voice_assistant.py` (lines 44-115)

See [CONFIGURATION.md](CONFIGURATION.md) for tuning parameters.

## Deployment

### Docker Compose (Local)

```bash
docker-compose up -d --build
docker-compose logs -f
```

### Railway (Production)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete Railway setup.

## Testing

### Health Check
```bash
curl http://localhost:8000/health
```

### Create Session
```bash
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"TestUser","voiceId":"Ashley"}'
```

### End Session
```bash
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"session_123"}'
```

## Troubleshooting

### Services Won't Start
```bash
make ps           # Check container status
make logs-all     # View all logs
make clean        # Clean and rebuild
make build
make dev-d
```

### No Audio
- Check microphone permissions in browser
- Verify LiveKit credentials in `.env`
- Check browser console for WebRTC errors

### Agent Not Responding
```bash
make logs-celery              # Check Celery worker
make redis-sessions           # Check session state
make logs-agent-live SESSION=xxx  # Watch agent logs
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed troubleshooting.

## Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Local setup, Makefile commands, troubleshooting
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Railway deployment guide
- **[CONFIGURATION.md](CONFIGURATION.md)** - All environment variables & agent config
- **[backend/API.md](backend/API.md)** - REST API endpoints reference
- **[frontend/README.md](frontend/README.md)** - Frontend development guide
- **[scripts/README.md](scripts/README.md)** - Helper scripts usage

## License

MIT

## Support

For issues or questions, open an issue on GitHub.
