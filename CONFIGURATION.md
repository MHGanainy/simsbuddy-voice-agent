# Configuration Reference

All configurable options in one place.

## Environment Variables

### Required Variables

```bash
# LiveKit Configuration
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxx
LIVEKIT_API_SECRET=secretxxxxxxxxxxxxxxxxxxxxxxx

# AI Services
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ASSEMBLY_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
INWORLD_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Redis
REDIS_URL=redis://localhost:6379/0
# Railway: redis://default:password@host:port
```

**Get API keys:**
- LiveKit: https://cloud.livekit.io
- Groq: https://console.groq.com/keys
- AssemblyAI: https://www.assemblyai.com/app/account
- Inworld: https://studio.inworld.ai/

### Optional Variables (with defaults)

```bash
# Logging
LOG_LEVEL=INFO                    # DEBUG|INFO|WARN|ERROR|CRITICAL
LOG_FORMAT=console                # console|json (use json for production)
SERVICE_NAME=orchestrator         # Service identifier in logs

# Python Configuration
PYTHONPATH=/app                   # Python module search path
PYTHON_SCRIPT_PATH=/app/backend/agent/voice_assistant.py

# Performance
MAX_BOTS=50                       # Max concurrent voice agents
SESSION_TIMEOUT=1800000           # Session timeout in ms (30 min)
BOT_STARTUP_TIMEOUT=30            # Agent startup timeout (seconds)

# Port (Railway auto-injects this)
PORT=8000                         # FastAPI server port
```

## Agent Configuration

File: `backend/agent/voice_assistant.py` (lines 44-115)

All agent parameters are in a centralized configuration section.

### Context Aggregator

```python
AGGREGATION_TIMEOUT = 0.2          # Response aggregation delay (seconds)
BOT_INTERRUPTION_TIMEOUT = 0.2     # How quickly bot can be interrupted
```

**Tuning:**
- Lower values = faster responses, more interruptions
- Higher values = smoother responses, less interruptions

### TTS (Text-to-Speech) - Inworld

```python
TTS_STREAMING = True               # Enable streaming (recommended)
TTS_TEMPERATURE = 1.1              # Voice expressiveness (0.0-2.0)
TTS_DEFAULT_SPEED = 1.0            # Default speech rate
```

**Voice-specific speeds:**
```python
VOICE_SPEED_OVERRIDES = {
    "Craig": 1.2,    # Male, faster (20% faster)
    "Edward": 1.0,   # Male, normal speed
    "Olivia": 1.0,   # Female, normal speed
    "Wendy": 1.2,    # Female, faster
    "Priya": 1.0,    # Asian accent, normal speed
    "Ashley": 1.0,   # Default voice, normal speed
}
```

### STT (Speech-to-Text) - AssemblyAI

```python
STT_SAMPLE_RATE = 16000                      # Audio sample rate (Hz)
STT_ENCODING = "pcm_s16le"                   # Audio encoding
STT_MODEL = "universal-streaming"             # AssemblyAI model
STT_FORMAT_TURNS = False                      # Format as conversation turns
STT_END_OF_TURN_CONFIDENCE = 0.70            # Confidence to end turn (0.0-1.0)
STT_MIN_SILENCE_CONFIDENT = 50               # Min silence when confident (ms)
STT_MAX_TURN_SILENCE = 200                   # Max silence before turn ends (ms)
STT_ENABLE_PARTIALS = True                   # Enable partial transcripts
STT_IMMUTABLE_FINALS = True                  # Final transcripts immutable
STT_PUNCTUATE = False                        # Add punctuation
STT_FORMAT_TEXT = False                      # Format text (capitalization)
STT_VAD_FORCE_ENDPOINT = True                # Force turn endpoint on VAD
STT_LANGUAGE = "en"                          # Language code
```

**Key tuning parameters:**
- `STT_END_OF_TURN_CONFIDENCE` - Higher = waits longer for user to finish
- `STT_MAX_TURN_SILENCE` - Lower = faster turn detection, more interruptions

### LLM (Large Language Model) - Groq

```python
LLM_MODEL = "llama-3.3-70b-versatile"        # Groq model
LLM_STREAM = True                            # Enable streaming (low latency)
LLM_MAX_TOKENS = 100                         # Max response length
LLM_TEMPERATURE = 0.6                        # Creativity (0.0-2.0)
LLM_TOP_P = 0.8                              # Nucleus sampling
LLM_PRESENCE_PENALTY = 0.15                  # Penalty for repetition
LLM_FREQUENCY_PENALTY = 0.30                 # Penalty for common words
```

**Key tuning parameters:**
- `LLM_MAX_TOKENS` - Lower = shorter responses (faster, cheaper)
- `LLM_TEMPERATURE` - Higher = creative, lower = focused

### Critical Rules

These rules are **automatically appended** to all system prompts:

```python
CRITICAL_RULES = """
CRITICAL RULES:
You are roleplaying. Everything you write will be spoken aloud...
- Keep responses short (1-2 sentences max)
- Only output spoken words + emotion tags
- Supported tags: [happy], [sad], [angry], [surprised], [fearful], [disgusted]
- Never use stage directions or actions
"""
```

**Note:** Cannot be overridden - always appended for TTS compatibility.

## Frontend Configuration

File: `frontend/src/VoiceSettings.tsx`

Available voices (must match backend):

```typescript
const voices = [
  { id: "Ashley", name: "Ashley (Default)", gender: "Female" },
  { id: "Craig", name: "Craig (Fast)", gender: "Male" },
  { id: "Edward", name: "Edward", gender: "Male" },
  { id: "Olivia", name: "Olivia", gender: "Female" },
  { id: "Wendy", name: "Wendy (Fast)", gender: "Female" },
  { id: "Priya", name: "Priya (Asian)", gender: "Female" },
];
```

**To add a new voice:**
1. Add to `VOICE_SPEED_OVERRIDES` in `voice_assistant.py`
2. Add to `voices` array in `VoiceSettings.tsx`
3. Ensure voice ID exists in Inworld

## Redis Schema

### Session Data

```
Key: session:{sessionId}

Fields:
- userName: string
- voiceId: string
- openingLine: string
- systemPrompt: string
- celeryTaskId: string (UUID)
- agentPid: integer (process ID)
- status: string (starting|ready|ending)
- startTime: integer (Unix timestamp)
- conversationStartTime: integer (first utterance)
- conversationDuration: integer (seconds)
- conversationDurationMinutes: integer (rounded up)
- minutesBilled: integer (for billing enforcement)

TTL: 2 hours (7200 seconds)
```

### User Configuration

```
Key: user:{userName}:config

Fields:
- voiceId: string
- openingLine: string
- systemPrompt: string
- updatedAt: integer (Unix timestamp)
```

## Tuning Guide

### For Faster Responses

```python
# Reduce timeouts
AGGREGATION_TIMEOUT = 0.1
BOT_INTERRUPTION_TIMEOUT = 0.1

# Reduce max tokens
LLM_MAX_TOKENS = 50

# Lower STT confidence
STT_END_OF_TURN_CONFIDENCE = 0.60

# Use fast voices
voice_id = "Craig"  # or "Wendy"
```

### For Better Accuracy

```python
# Increase timeouts
AGGREGATION_TIMEOUT = 0.3
BOT_INTERRUPTION_TIMEOUT = 0.3

# Increase max tokens
LLM_MAX_TOKENS = 150

# Higher STT confidence
STT_END_OF_TURN_CONFIDENCE = 0.80

# Normal speed voices
voice_id = "Edward"  # or "Olivia"
```

### For Production

```bash
# Environment variables
LOG_FORMAT=json                    # Structured logs
LOG_LEVEL=WARN                     # Less verbose
MAX_BOTS=100                       # Higher capacity
```

## Configuration by Environment

### Local Development

```bash
LOG_LEVEL=DEBUG
LOG_FORMAT=console
MAX_BOTS=10
REDIS_URL=redis://localhost:6379/0
```

### Staging

```bash
LOG_LEVEL=INFO
LOG_FORMAT=json
MAX_BOTS=50
REDIS_URL=redis://default:password@railway:6379
```

### Production

```bash
LOG_LEVEL=WARN
LOG_FORMAT=json
MAX_BOTS=100
REDIS_URL=redis://default:password@railway:6379
```

## Related Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) - Local setup
- [DEPLOYMENT.md](DEPLOYMENT.md) - Railway deployment
- [backend/API.md](backend/API.md) - API reference
