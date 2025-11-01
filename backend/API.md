# API Reference

REST API documentation for the Voice Assistant Orchestrator.

**Base URL:**
- Development: `http://localhost:8000`
- Production: `https://your-app.railway.app`

**Interactive Docs:**
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Authentication

Currently no authentication required.

## Endpoints

### Health Check

**GET** `/health`

Check if all services are healthy.

**Response 200:**
```json
{
  "status": "healthy",
  "livekit_url": "wss://...",
  "livekit_configured": true,
  "redis_connected": true,
  "celery_available": true
}
```

**Status values:**
- `healthy` - All systems operational
- `degraded` - Some services down

**Example:**
```bash
curl http://localhost:8000/health
```

---

### Start Session

**POST** `/api/session/start`

Create a new voice assistant session.

**Request Body:**
```json
{
  "userName": "user123",
  "voiceId": "Ashley",
  "openingLine": "Hello! How can I help you today?",
  "systemPrompt": "You are a helpful customer service agent."
}
```

**Parameters:**
- `userName` (required) - User identifier
- `voiceId` (optional) - Voice to use (default: "Ashley")
  - Options: Ashley, Craig, Edward, Olivia, Wendy, Priya
- `openingLine` (optional) - Custom greeting
- `systemPrompt` (optional) - Custom LLM instructions

**Response 200:**
```json
{
  "success": true,
  "sessionId": "session_1234567890_abc123",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "serverUrl": "wss://your-project.livekit.cloud",
  "roomName": "session_1234567890_abc123",
  "message": "Session created. Voice agent is being spawned."
}
```

**Response Fields:**
- `sessionId` - Unique session identifier
- `token` - LiveKit JWT token (2-hour expiry)
- `serverUrl` - LiveKit WebRTC server URL
- `roomName` - LiveKit room name (same as sessionId)

**Error Responses:**

`500 Internal Server Error` - Token generation failed
```json
{
  "detail": "LiveKit token generation failed: ..."
}
```

`503 Service Unavailable` - Celery unavailable
```json
{
  "detail": "Failed to queue voice agent spawn task: ..."
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "john_doe",
    "voiceId": "Craig",
    "openingLine": "Hi there! Ready to help.",
    "systemPrompt": "You are a friendly tech support agent."
  }'
```

---

### End Session

**POST** `/api/session/end`

End a session and cleanup resources.

**Request Body:**
```json
{
  "sessionId": "session_1234567890_abc123"
}
```

**Response 200:**
```json
{
  "success": true,
  "message": "Session session_123 ended and cleaned up",
  "details": {
    "session_id": "session_123",
    "celery_task_revoked": true,
    "process_killed": true,
    "redis_cleaned": true,
    "errors": [],
    "durationSeconds": 125,
    "durationMinutes": 3
  }
}
```

**Response Fields:**
- `details.durationSeconds` - Total conversation time in seconds
- `details.durationMinutes` - Rounded up to minutes (for billing)
- `details.celery_task_revoked` - Celery task stopped
- `details.process_killed` - Voice agent process terminated
- `details.redis_cleaned` - Redis keys deleted

**Error Responses:**

`404 Not Found` - Session doesn't exist
```json
{
  "detail": "Session session_123 not found"
}
```

`500 Internal Server Error` - Cleanup failed
```json
{
  "detail": "Failed to end session: ..."
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d '{"sessionId": "session_1234567890_abc123"}'
```

---

### LiveKit Webhook

**POST** `/webhook/livekit`

Internal endpoint for LiveKit disconnect events.

**Headers:**
- `X-LiveKit-Signature` - HMAC-SHA256 signature (verified)

**Request Body:**
```json
{
  "event": "participant_left",
  "room": {
    "name": "session_123",
    "id": "..."
  },
  "participant": {
    "identity": "user_123",
    "id": "..."
  }
}
```

**Handled Events:**
- `participant_left` - User disconnected
- `room_finished` - Room closed

**Response 200:**
```json
{
  "status": "ok",
  "event": "participant_left"
}
```

**Error Responses:**

`401 Unauthorized` - Invalid signature
```json
{
  "detail": "Invalid webhook signature"
}
```

`400 Bad Request` - Invalid JSON
```json
{
  "detail": "Invalid JSON payload"
}
```

**Note:** This endpoint is called automatically by LiveKit.

---

### Root Endpoint

**GET** `/`

API information.

**Response 200:**
```json
{
  "service": "Voice Assistant Orchestrator",
  "status": "running",
  "version": "2.0.0",
  "type": "Python FastAPI",
  "features": ["session_tracking", "cleanup", "livekit_webhooks"]
}
```

## WebSocket Endpoints

LiveKit handles WebRTC connections directly. The API doesn't expose WebSocket endpoints.

**Frontend connection flow:**
1. Call `/api/session/start` to get token
2. Use token to connect to LiveKit via LiveKit SDK
3. Audio/video handled by LiveKit WebRTC

## Rate Limits

Currently no rate limits implemented.

## Errors

All errors follow this format:
```json
{
  "detail": "Error message here"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad request (invalid input)
- `401` - Unauthorized (webhook signature)
- `404` - Not found (session doesn't exist)
- `500` - Internal server error
- `503` - Service unavailable (Celery/Redis down)

## Examples

### Complete Flow

```bash
# 1. Start session
SESSION=$(curl -s -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"test"}' | jq -r '.sessionId')

echo "Session: $SESSION"

# 2. Wait for conversation (user talks to agent)
sleep 120  # 2 minutes

# 3. End session
curl -X POST http://localhost:8000/api/session/end \
  -H "Content-Type: application/json" \
  -d "{\"sessionId\":\"$SESSION\"}" | jq .

# Output includes duration:
# {
#   "durationSeconds": 120,
#   "durationMinutes": 2
# }
```

### Test with Different Voices

```bash
# Craig (fast male)
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"test","voiceId":"Craig"}'

# Olivia (professional female)
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"test","voiceId":"Olivia"}'
```

### Custom System Prompts

```bash
# Customer service agent
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName":"customer1",
    "systemPrompt":"You are a helpful customer service representative for ACME Corp. Be friendly and professional."
  }'

# Technical support
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName":"user1",
    "systemPrompt":"You are a technical support specialist. Provide clear troubleshooting steps."
  }'
```

## Related Documentation

- [CONFIGURATION.md](../CONFIGURATION.md) - Configuration options
- [DEVELOPMENT.md](../DEVELOPMENT.md) - Local development
- [DEPLOYMENT.md](../DEPLOYMENT.md) - Railway deployment
