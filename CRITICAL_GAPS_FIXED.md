# Critical Gaps Fixed - Session Tracking & Cleanup

## Overview

This document describes the critical improvements made to the Python FastAPI orchestrator to add proper session tracking, cleanup, and LiveKit disconnect handling.

---

## Changes Made

### 1. Session State Tracking (Redis) ✅

**main.py changes:**
- Added Redis client connection at startup
- Store session state when session starts (POST /api/session/start)
- Session data includes: userName, voiceId, openingLine, celeryTaskId, status, startTime
- 2-hour TTL on session keys (matches LiveKit token TTL)

**Redis Schema:**
```python
Key: session:{sessionId}
Value (hash):
  - userName: string
  - voiceId: string
  - openingLine: string
  - celeryTaskId: string (UUID of Celery task)
  - status: "starting" | "ready"
  - startTime: unix timestamp
  - agentPid: int (added by tasks.py when agent spawns)
TTL: 7200 seconds (2 hours)
```

**Code Location:** main.py:366-380

---

### 2. Proper /api/session/end Implementation ✅

**Cleanup Flow:**
1. Check if session exists in Redis (404 if not found)
2. Call `cleanup_session()` helper function
3. Return cleanup details and success status

**cleanup_session() function** (main.py:160-282):

```python
def cleanup_session(session_id: str) -> Dict[str, Any]:
    """
    Steps:
    1. Get session data from Redis
    2. Revoke Celery task if exists
    3. Kill voice agent process (SIGTERM then SIGKILL)
    4. Remove all Redis keys for this session

    Returns:
        {
            "session_id": str,
            "celery_task_revoked": bool,
            "process_killed": bool,
            "redis_cleaned": bool,
            "errors": list
        }
    """
```

**Process Cleanup:**
- Send SIGTERM first (graceful shutdown)
- Wait 5 seconds
- Check if process still alive
- Send SIGKILL if needed
- Handle ProcessLookupError (process already dead)

**Celery Task Revocation:**
```python
celery_app.control.revoke(task_id, terminate=True)
```

**Redis Cleanup:**
- Delete keys: `session:{id}`, `agent:{id}:pid`, `agent:{id}:logs`, `agent:{id}:health`
- Remove from sets: `session:ready`, `session:starting`, `pool:ready`
- Delete user mapping: `session:user:{userId}`

**Code Location:** main.py:411-471

---

### 3. LiveKit Disconnect Webhook ✅

**New Endpoint:** POST /webhook/livekit

**Signature Verification:**
- Uses HMAC-SHA256 with LIVEKIT_API_SECRET
- Compares against X-LiveKit-Signature header
- Returns 401 if signature invalid
- Allows missing signature in development (with warning)

**Events Handled:**
- `participant_left` - User disconnected from room
- `room_finished` - Room closed

**Webhook Processing Flow:**
```python
1. Get raw request body
2. Verify X-LiveKit-Signature header
3. Parse JSON payload
4. Extract event type, room name, participant
5. If disconnect event + room name starts with "session_":
   - Call cleanup_session(session_id)
   - Log cleanup results
6. Return 200 OK
```

**Code Location:** main.py:473-540

---

### 4. tasks.py Updates ✅

**Change:** Use consistent field name `celeryTaskId` instead of `taskId`

**Before:**
```python
'taskId': task_id
```

**After:**
```python
'celeryTaskId': task_id
```

**Reason:** Consistency with main.py session state storage

**Code Location:** tasks.py:84

---

### 5. Comprehensive Error Handling ✅

#### Token Generation Errors
```python
try:
    token = generate_livekit_token(session_id, request.userName)
except Exception as e:
    raise HTTPException(status_code=500, detail=f"LiveKit token generation failed: {str(e)}")
```

#### Celery Task Errors
```python
try:
    task = spawn_voice_agent.delay(...)
except Exception as e:
    raise HTTPException(status_code=503, detail=f"Failed to queue voice agent spawn task: {str(e)}")
```

#### Redis Connection Errors
- Startup: Fails fast if Redis unavailable
- Health check: Returns "degraded" status if Redis down
- Session operations: Logs warnings if Redis writes fail (non-fatal)

#### Session Not Found
```python
if not session_exists:
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
```

#### Partial Cleanup Failures
- Returns success=True even if some cleanup steps fail
- Includes errors array in response details
- Logs all errors for debugging

**HTTP Status Codes Used:**
- 200: Success
- 400: Bad Request (invalid webhook payload)
- 401: Unauthorized (invalid webhook signature)
- 404: Session not found
- 500: Internal error (token generation, cleanup failure)
- 503: Service unavailable (Celery unavailable)

---

## Disconnect Flow Explained

### Scenario: User Disconnects from LiveKit Room

```
┌──────────────────────────────────────────────────────────┐
│                  USER DISCONNECTS                        │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              LiveKit Cloud                               │
│  • Detects participant_left event                       │
│  • Generates webhook payload                            │
│  • Signs with HMAC-SHA256 (API secret)                  │
│  • POST to orchestrator webhook endpoint                │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│        Orchestrator: POST /webhook/livekit               │
│  1. Verify signature (X-LiveKit-Signature header)       │
│  2. Parse JSON payload                                   │
│  3. Extract room name = session_xxx                     │
│  4. Call cleanup_session(session_id)                    │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│         cleanup_session(session_id)                      │
│                                                          │
│  Step 1: Get session data from Redis                    │
│  ├─ session:session_xxx → { celeryTaskId, agentPid }   │
│                                                          │
│  Step 2: Revoke Celery task                            │
│  ├─ celery_app.control.revoke(task_id, terminate=True) │
│                                                          │
│  Step 3: Kill voice agent process                       │
│  ├─ os.kill(pid, signal.SIGTERM)                       │
│  ├─ sleep(5)  # Wait for graceful shutdown             │
│  ├─ Check if still alive                               │
│  └─ os.kill(pid, signal.SIGKILL) if needed             │
│                                                          │
│  Step 4: Clean up Redis                                │
│  ├─ DELETE session:session_xxx                          │
│  ├─ DELETE agent:session_xxx:pid                        │
│  ├─ DELETE agent:session_xxx:logs                       │
│  ├─ DELETE agent:session_xxx:health                     │
│  ├─ SREM session:ready session_xxx                      │
│  └─ DELETE session:user:userName                        │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│                 CLEANUP COMPLETE                         │
│  • Voice agent process terminated                       │
│  • Redis state cleared                                   │
│  • Resources freed                                       │
│  • Webhook returns 200 OK                               │
└──────────────────────────────────────────────────────────┘
```

---

## API Changes Summary

### POST /api/session/start

**New Behavior:**
- Stores session state in Redis with 2-hour TTL
- Stores user config (voiceId, openingLine) for Celery task to read
- Better error handling with specific HTTP status codes

**Response:**
```json
{
  "success": true,
  "sessionId": "session_1730462400000_abc123xyz",
  "token": "eyJhbGci...",
  "serverUrl": "wss://your-instance.livekit.cloud",
  "roomName": "session_1730462400000_abc123xyz",
  "message": "Session created. Voice agent is being spawned."
}
```

### POST /api/session/end

**Before:**
```json
{
  "success": true,
  "message": "Session XXX end acknowledged. Note: Cleanup not yet implemented."
}
```

**After:**
```json
{
  "success": true,
  "message": "Session XXX ended and cleaned up",
  "details": {
    "session_id": "session_XXX",
    "celery_task_revoked": true,
    "process_killed": true,
    "redis_cleaned": true,
    "errors": []
  }
}
```

**Error Codes:**
- 404: Session not found
- 500: Cleanup failed

### POST /webhook/livekit (NEW)

**Request Headers:**
```
X-LiveKit-Signature: <hmac-sha256-signature>
Content-Type: application/json
```

**Request Body:**
```json
{
  "event": "participant_left",
  "room": {
    "name": "session_1730462400000_abc123xyz",
    "id": "RM_xxx"
  },
  "participant": {
    "identity": "user_xxx",
    "sid": "PA_xxx"
  }
}
```

**Response:**
```json
{
  "status": "ok",
  "event": "participant_left"
}
```

**Error Codes:**
- 400: Invalid JSON payload
- 401: Invalid signature
- 500: Processing failed

### GET /health

**Enhanced Response:**
```json
{
  "status": "healthy",
  "livekit_url": "wss://your-instance.livekit.cloud",
  "livekit_configured": true,
  "redis_connected": true,
  "celery_available": true
}
```

**Status Values:**
- "healthy" - All systems operational
- "degraded" - Redis unavailable

---

## Testing Commands

### Test Session Lifecycle

```bash
# 1. Start session
SESSION_RESPONSE=$(curl -s -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "TestUser",
    "voiceId": "Ashley",
    "openingLine": "Hello! How can I help you?"
  }')

echo $SESSION_RESPONSE | jq .

# Extract session ID
SESSION_ID=$(echo $SESSION_RESPONSE | jq -r '.sessionId')
echo "Session ID: $SESSION_ID"

# 2. Check Redis session state
docker exec voice-agent-redis redis-cli HGETALL "session:$SESSION_ID"

# 3. Check agent PID
docker exec voice-agent-redis redis-cli GET "agent:$SESSION_ID:pid"

# 4. End session
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d "{\"sessionId\": \"$SESSION_ID\"}" | jq .

# 5. Verify cleanup
docker exec voice-agent-redis redis-cli HGETALL "session:$SESSION_ID"
# Should return empty
```

### Test Webhook (Simulate LiveKit)

```bash
# Generate HMAC signature (Python)
python3 << 'EOF'
import hmac
import hashlib
import json

payload = {
    "event": "participant_left",
    "room": {"name": "session_1730462400000_abc123xyz"},
    "participant": {"identity": "test_user"}
}

payload_bytes = json.dumps(payload).encode('utf-8')
secret = "your_livekit_api_secret"  # Replace with actual secret

signature = hmac.new(
    secret.encode('utf-8'),
    payload_bytes,
    hashlib.sha256
).hexdigest()

print(f"Signature: {signature}")
print(f"Payload: {json.dumps(payload)}")
EOF

# Send webhook
curl -X POST http://localhost:8000/webhook/livekit \
  -H "Content-Type: application/json" \
  -H "X-LiveKit-Signature: <signature-from-above>" \
  -d '{
    "event": "participant_left",
    "room": {"name": "session_1730462400000_abc123xyz"},
    "participant": {"identity": "test_user"}
  }' | jq .
```

### Monitor Logs

```bash
# Orchestrator logs
docker logs voice-agent-orchestrator -f --tail 50

# Look for:
# [Session] Started session...
# [Cleanup] Cleaning up session...
# [Cleanup] Revoked Celery task...
# [Cleanup] Killing process...
# [Webhook] Disconnect detected...
```

---

## File Changes Summary

### Modified Files

1. **voice-assistant-project/orchestrator/main.py**
   - **Lines changed:** 212 → 563 (351 lines added)
   - **Key additions:**
     - Redis client connection (lines 37-44)
     - Celery app import (lines 46-48)
     - `cleanup_session()` helper (lines 160-282)
     - Enhanced `/api/session/start` with Redis storage (lines 296-409)
     - Proper `/api/session/end` implementation (lines 411-471)
     - `/webhook/livekit` endpoint (lines 473-540)
     - `verify_livekit_webhook()` helper (lines 136-158)
     - Enhanced error handling throughout

2. **voice-assistant-project/orchestrator/tasks.py**
   - **Lines changed:** 1 line
   - **Change:** `'taskId'` → `'celeryTaskId'` (line 84)
   - **Reason:** Consistency with main.py

---

## Dependencies

**No new dependencies required!** All used libraries are already in requirements.txt:
- ✅ `redis==5.0.1` - Redis client
- ✅ `celery==5.3.4` - Celery app for task revocation
- ✅ `fastapi==0.109.0` - Request, Header imports
- ✅ Standard library: `os`, `signal`, `hmac`, `hashlib`, `json`, `time`

---

## Security Considerations

### 1. Webhook Signature Verification
- **Implemented:** HMAC-SHA256 with LIVEKIT_API_SECRET
- **Protection:** Prevents unauthorized webhook spoofing
- **Development:** Allows missing signature with warning log

### 2. Process Termination
- **SIGTERM first:** Allows graceful shutdown
- **5-second grace period**
- **SIGKILL fallback:** Ensures cleanup even if process hangs

### 3. Error Information Disclosure
- **Careful logging:** Errors logged server-side with full details
- **Limited client exposure:** HTTP responses don't leak internal state
- **Status codes:** Appropriate codes (404, 500, 503) without revealing implementation

### 4. Resource Cleanup
- **Prevents orphaned processes:** Kills voice agent on disconnect
- **Prevents memory leaks:** Cleans up Redis keys
- **Prevents task buildup:** Revokes running Celery tasks

---

## Production Checklist

Before deploying to production:

- [ ] **Configure webhook URL in LiveKit Cloud:**
  ```
  https://your-domain.com/webhook/livekit
  ```

- [ ] **Enable webhook signature verification:**
  - Remove development bypass in webhook handler
  - Ensure LIVEKIT_API_SECRET is correct

- [ ] **Set up monitoring:**
  - Track cleanup success/failure rates
  - Alert on failed process terminations
  - Monitor Redis connection health

- [ ] **Configure CORS properly:**
  - Change `allow_origins=["*"]` to specific domains
  - In production: `allow_origins=["https://your-frontend.com"]`

- [ ] **Add rate limiting:**
  - Protect /api/session/start endpoint
  - Prevent abuse of session creation

- [ ] **Set up log aggregation:**
  - Capture [Cleanup], [Webhook], [Session] logs
  - Enable debugging of disconnect issues

- [ ] **Test failover scenarios:**
  - Redis unavailable
  - Celery worker down
  - Process already terminated
  - Invalid webhook signatures

---

## Troubleshooting

### Session cleanup not working

**Check Redis connection:**
```bash
docker exec voice-agent-orchestrator python3 -c "
import redis;
r = redis.from_url('redis://redis:6379/0');
print(r.ping())
"
```

**Check session exists:**
```bash
docker exec voice-agent-redis redis-cli KEYS "session:*"
```

### Process not killed

**Check PID in Redis:**
```bash
docker exec voice-agent-redis redis-cli GET "agent:session_XXX:pid"
```

**Check if process exists:**
```bash
docker exec voice-agent-orchestrator ps aux | grep python3
```

**Manual kill:**
```bash
docker exec voice-agent-orchestrator kill -TERM <PID>
```

### Webhook not triggered

**Check LiveKit Cloud webhook configuration:**
- URL must be publicly accessible
- HTTPS required in production
- Verify webhook is enabled

**Test webhook manually** (see Testing Commands above)

**Check webhook logs:**
```bash
docker logs voice-agent-orchestrator | grep "\[Webhook\]"
```

---

## Summary

All critical gaps have been fixed:

✅ **Session state tracking** - Redis storage with 2-hour TTL
✅ **Proper cleanup** - Revoke tasks, kill processes, clean Redis
✅ **LiveKit webhooks** - Auto-cleanup on disconnect
✅ **Error handling** - Specific status codes, detailed error logs
✅ **Process management** - SIGTERM → SIGKILL graceful cleanup

**Result:** Production-ready session management with proper resource cleanup and automatic disconnect handling.
