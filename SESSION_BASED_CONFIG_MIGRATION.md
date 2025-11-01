# Session-Based Configuration Migration

## Problem

The previous implementation stored voice and session configuration using user-based Redis keys (`user:{userName}:config`). This caused critical conflicts when the same user had multiple concurrent sessions:

- User starts session 1 with voice "Craig"
- User starts session 2 with voice "Olivia"
- Session 1's config gets overwritten by session 2's config
- Both sessions would use "Olivia" voice instead of their intended voices

## Solution

Migrated to session-based configuration storage (`session:{session_id}:config`) to ensure each session maintains its own independent configuration.

## Changes Made

### 1. Orchestrator - Write Session Config (`backend/orchestrator/main.py`)

**Lines 404-431**: Changed Redis storage from user-based to session-based

```python
# OLD (user-based - caused conflicts)
config_key = f"user:{request.userName}:config"

# NEW (session-based - isolated per session)
config_key = f"session:{session_id}:config"
```

**Additional changes:**
- Added 4-hour TTL to match session lifetime
- Changed log event from "user_config_stored" to "session_config_stored"
- Added userName to config_data for reference tracking

### 2. Celery Task - Read Session Config (`backend/orchestrator/tasks.py`)

**Lines 120-134**: Updated config retrieval to use session ID

```python
# OLD (read from user config)
if user_id:
    config_key = f'user:{user_id}:config'

# NEW (read from session config)
config_key = f'session:{session_id}:config'
```

**Additional changes:**
- Removed `if user_id:` check (session_id always available)
- Updated log event from "user_config_loaded" to "session_config_loaded"
- Added comment explaining the change

### 3. Session Cleanup (`backend/orchestrator/main.py`)

**Line 300**: Added session config to cleanup keys

```python
keys_to_delete = [
    f"session:{session_id}",
    f"session:{session_id}:config",  # NEW - Clean up session config
    f"agent:{session_id}:pid",
    # ... other keys
]
```

### 4. Stale Agent Cleanup (`backend/orchestrator/tasks.py`)

**Line 452**: Added session config to stale session cleanup

```python
redis_client.delete(f'session:{session_id}:config')  # NEW
```

## Testing

Test multiple concurrent sessions from the same user with different voices:

```bash
#!/bin/bash
# Test concurrent sessions with different voices

USER="test_concurrent_user"

# Start session 1 with Craig
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d "{\"userName\":\"$USER\",\"voiceId\":\"Craig\",\"correlationToken\":\"test_craig_$(date +%s)\"}"

# Start session 2 with Olivia
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d "{\"userName\":\"$USER\",\"voiceId\":\"Olivia\",\"correlationToken\":\"test_olivia_$(date +%s)\"}"

# Verify both sessions have correct voices in Redis
docker exec voice-agent-redis redis-cli KEYS "session:*:config"
```

## Migration Notes

- **No data migration needed**: System auto-generates config if not found
- **Backward compatible**: Old user-based configs will expire naturally (TTL)
- **User ID still tracked**: userName stored in session config for reference

## Benefits

1. **Concurrent session support**: Multiple sessions per user work correctly
2. **Session isolation**: Each session's configuration is independent
3. **Automatic cleanup**: Config expires with session (4-hour TTL)
4. **Better tracking**: Session ID provides direct correlation to LiveKit room

## Files Modified

1. `/Users/elganayni/mg/livekit-demo/backend/orchestrator/main.py`
   - Session config storage (lines 404-431)
   - Session cleanup (line 300)

2. `/Users/elganayni/mg/livekit-demo/backend/orchestrator/tasks.py`
   - Config retrieval (lines 120-134)
   - Stale session cleanup (line 452)
