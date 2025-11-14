# Voice Agent Testing Guide

## Quick Start - Standalone Agent (Fastest)

The fastest way to test the voice agent is using the standalone server:

```bash
# 1. Start standalone agent server
docker-compose up voice-agent-server

# 2. Start frontend
cd frontend && npm run dev

# 3. Open browser to http://localhost:3000
# 4. Select "Direct Agent" mode
# 5. Click "Start Session" (<1s connection)
# 6. Speak into microphone
```

**Advantages**:
- ✅ Instant connection (<1s)
- ✅ No orchestrator needed
- ✅ No database needed
- ✅ No Celery needed
- ✅ Single service
- ✅ Perfect for rapid voice testing

**Limitations**:
- ⚠️ Single agent only (not multi-session)
- ⚠️ No credit billing
- ⚠️ For testing only (not production)
- ⚠️ Static configuration (voice/prompt from env vars)

---

## Testing Mode Comparison

### Direct Agent Mode (Fastest)
**Architecture**: Frontend → Voice Agent Server → LiveKit

**Setup**:
```bash
docker-compose up voice-agent-server frontend
```

**Use when**:
- Testing voice interaction rapidly
- No need for orchestrator features
- Working on voice agent code
- Need instant feedback loop

**Connection time**: <1s

---

### Direct Mode (Orchestrator, No Celery)
**Architecture**: Frontend → Orchestrator → Voice Agent (direct spawn)

**Setup**:
```bash
docker-compose up redis voice-agent frontend
```

**Use when**:
- Testing orchestrator logic
- Need session management
- Testing without Celery queue
- Faster than full orchestrator mode

**Connection time**: ~5s

---

### Orchestrator Mode (Full Flow)
**Architecture**: Frontend → Orchestrator → Celery → Voice Agent → LiveKit

**Setup**:
```bash
docker-compose up
```

**Use when**:
- Testing production flow
- Need credit billing
- Testing task queue
- Testing session management

**Connection time**: ~10s

---

## Standalone Server Configuration

### Environment Variables

```bash
# Voice Configuration
VOICE_AGENT_VOICE_ID=Ashley
VOICE_AGENT_OPENING_LINE=Hello! Ready for testing.
VOICE_AGENT_SYSTEM_PROMPT=You are a helpful assistant.

# Room Configuration
AGENT_ROOM_NAME=test-agent-room
AGENT_USER_ID=voice-agent
```

### Testing Different Voices

```bash
# Update .env
VOICE_AGENT_VOICE_ID=Wendy

# Restart server
docker-compose restart voice-agent-server

# Connect from frontend - will use Wendy voice
```

### Viewing Agent Logs

```bash
# Follow agent logs in real-time
docker logs -f voice-agent-server

# Look for:
# - "Voice agent spawned: PID=..."
# - "[AGENT] Connected to..."
# - "[AGENT] Participant joined"
```

---

## Troubleshooting

### Issue: "Voice agent is not running"

**Check**:
```bash
# Check health
curl http://localhost:8001/health

# If agent_running=false, check logs
docker logs voice-agent-server | grep ERROR
```

**Common causes**:
- Missing API keys (GROQ_API_KEY, ASSEMBLY_API_KEY, INWORLD_API_KEY)
- Invalid LiveKit credentials
- Agent process crashed

**Fix**:
```bash
# Restart server
docker-compose restart voice-agent-server

# Wait 30s for agent to spawn
sleep 30

# Check again
curl http://localhost:8001/health
```

---

### Issue: Connection succeeds but no audio

**Check**:
1. Microphone permission granted in browser
2. LiveKit room joined (check browser console)
3. Agent is in same room

```bash
# Check agent logs
docker logs voice-agent-server | grep "Participant joined"
```

---

### Issue: Different voice not working

**Check**:
```bash
# Verify environment variable
docker exec voice-agent-server env | grep VOICE_AGENT_VOICE_ID

# Should match your .env setting
# If not, restart:
docker-compose down
docker-compose up voice-agent-server
```

---

## Legacy Testing Methods

### Direct Voice Agent Testing (CLI)

```bash
# Enable test mode
export TEST_MODE=true

# Spawn voice agent directly (bypasses orchestrator/celery)
python scripts/test_voice_agent_direct.py --session-id test_001

# With custom voice and prompts
python scripts/test_voice_agent_direct.py \
  --session-id test_002 \
  --voice-id Ashley \
  --opening-line "Hello! Ready for testing." \
  --system-prompt "You are a test assistant."
```

### Full Flow Testing (via Orchestrator)

```bash
# Add to .env
TEST_MODE=true

# Start services
docker-compose up

# Test session via API
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "test_user",
    "voiceId": "Ashley",
    "correlationToken": "test_session_001"
  }'
```

## Environment Variables

### Required (All Modes)
```bash
LIVEKIT_URL=wss://your-livekit-server.com
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
GROQ_API_KEY=gsk_...
ASSEMBLY_API_KEY=...
INWORLD_API_KEY=...
```

### Test Mode Configuration
```bash
# Enable test mode (default: false)
TEST_MODE=true

# Mock student ID for credit billing (default: test_student_123)
MOCK_STUDENT_ID=my_test_student

# Mock credit balance (default: 999)
MOCK_CREDIT_BALANCE=5000
```

## Verification

### What to Look For in Logs

When TEST_MODE is enabled, you should see:

```
============================================================
TEST MODE ENABLED - Database and orchestrator calls will be mocked
MOCK_REDIS=false
============================================================

TEST MODE: Skipping student_id lookup for test_session_001, returning test_student_123
TEST MODE: Skipping credit check for test_student_123, required=1, mock_balance=999 (always sufficient)
TEST MODE: Skipping credit deduction for session=test_session_001, minute=0
TEST MODE: Would execute transaction: SELECT/UPDATE students, INSERT credit_transactions, UPDATE simulation_attempts

[After 60 seconds]
heartbeat_sending session_id=test_session_001
TEST MODE: Skipping heartbeat HTTP call to orchestrator for test_session_001
TEST MODE: Would POST to orchestrator/api/session/heartbeat
TEST MODE: Mock heartbeat response - status=ok, credits_remaining=999

[On session end]
TEST MODE: Reconciling session test_session_001, total_minutes=2
TEST MODE: Will call deduct_minute() for minutes 0-1 (each returns mock data)
TEST MODE: Mock reconciliation complete

TEST MODE: Skipping transcript save for test_session_001
TEST MODE: Transcript contains 5 messages
```

### Success Criteria

- ✅ No database connection errors
- ✅ No SQL queries executed
- ✅ All "TEST MODE:" log messages appear
- ✅ Heartbeat fires every 60 seconds
- ✅ credits_remaining always shows 999
- ✅ Session completes without errors
- ✅ Voice agent connects to LiveKit successfully

### Failure Indicators

- ❌ Database connection errors (means TEST_MODE not detected)
- ❌ Missing "TEST MODE ENABLED" banner on startup
- ❌ No heartbeat logs after 60+ seconds
- ❌ HTTP connection errors to orchestrator (in test mode)
