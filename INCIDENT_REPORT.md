# Incident Report: Recent Commits Analysis & Production Issues

**Date:** 2026-01-24
**Reporter:** Ahmed Alazab
**Commits Under Review:**
- `57ba402` - feat: add Prometheus-compatible agent metrics endpoints
- `69a690b` - fix: improve agent spawn reliability with faster failure detection

---

## Executive Summary

Two commits (589+ lines of code) were added to fix perceived agent spawn reliability issues. However:

1. **No investigation was done** before implementing the fix
2. **No metrics were collected** to validate the problem
3. **New issues emerged** after deployment:
   - Opening message sometimes repeats
   - Echo sound in first 30 seconds
   - Original "stuck on connecting" issue **may be fixed** (not enough safe testing yet)

**Critical Finding:** The commits may have fixed the original issue but at the cost of introducing new problems. We can't safely test in production to confirm. The solution was a shotgun approach rather than targeted debugging.

**Paradox:** We can't determine if the original issue is fixed because the new issues make production testing unsafe.

---

## Production Issues Timeline

### **Issue #1: "Stuck on Connecting" (Pre-existing - ~10% failure rate)**

**User Experience:**
- Frontend shows "Connecting to voice agent..." indefinitely
- User must refresh browser (after ~1 minute)
- No error message shown

**Backend Logs Show:**
- ✅ Room created successfully
- ✅ LiveKit room exists
- ✅ Pipecat agent connected to room
- ❌ **User never joins the room**

**LiveKit Dashboard Shows:**
- Only 1 participant: Pipecat agent
- User participant: **Missing**

**Frontend Console Shows:**
- ✅ "Connected"
- ✅ "Ready"
- ✅ **NO ERRORS AT ALL**
- Frontend **thinks** it's connected but LiveKit shows it's not

**Timeline:**
```
T+0s:  Frontend requests session start
T+2s:  Backend returns token + room name
T+5s:  Pipecat agent joins room
T+7s:  Frontend console: "Connected", "Ready" (lying?)
T+10s: Frontend UI still shows "Connecting..." (correct - not actually connected)
T+60s: User refreshes page → works on second try
```

**Critical Observation:**
- Connection usually takes max 10 seconds when it works
- Failure happens in the **first 30 seconds**
- **Frontend console lies** - says "connected" when it's not
- This is a **silent connection failure** where frontend JavaScript thinks it succeeded but LiveKit WebSocket never established

**Status After Commits:**
- ⚠️ **Unknown if fixed** - can't safely test in production due to new regressions
- May have been resolved by the 90s timeout / status reporter changes
- Or may still occur but masked by new issues

---

### **Issue #2: Opening Message Repeats (New - appeared after commits)**

**User Experience:**
- Agent says opening line: "Hello, I'm Ashley..."
- After 2-5 seconds, **same message repeats**
- Sometimes accompanied by echo/audio artifacts

**Timeline:**
```
T+0s:  Agent joins room
T+1s:  Opening message queued
T+3s:  Opening message plays
T+5s:  Opening message plays AGAIN (duplicate)
```

**Possible Causes (to investigate):**
1. `on_first_participant_joined` firing twice
2. Status reporter interfering with audio pipeline
3. Race condition in participant detection
4. Agent reconnection during startup

---

### **Issue #3: Echo Sound (New - first 30 seconds only)**

**User Experience:**
- Audio feedback/echo during first 30 seconds
- Clears up after initial period
- Only affects beginning of conversation

**Correlation:** Timing matches the new `AGENT_ALIVE_TIMEOUT` (30s) and Redis log cutoff (60s)

---

## Analysis of Recent Commits

### **Commit #1: `69a690b` - Agent Spawn Reliability**

#### What Was Added (264 lines in tasks.py):

| Feature | Lines | Useful? | Notes |
|---------|-------|---------|-------|
| 90s timeout (was 30s) | 5 | ❌ | Over-engineered, no evidence cold starts take >30s |
| AGENT_ALIVE signal | 50 | ❌ | Solves imaginary problem (import crashes don't happen in prod) |
| Disabled exponential backoff | 3 | ❌ | Creates thundering herd during outages |
| AgentMetrics class | 140 | ⚠️ | Useful for observability, but poorly implemented |
| Cold start detection | 30 | ❌ | Per-worker, not global - metrics are wrong |
| Redis log cutoff (60s) | 36 | ❌ | Breaks debugging for long sessions |

**Total Useful Lines:** ~40 / 264 = **15% useful**

#### Frontend Status Updates (133 lines in voice_assistant.py):

| Feature | Lines | Useful? | Notes |
|---------|-------|---------|-------|
| AgentStatusReporter class | 83 | ✅ | **Good idea**, poor implementation (fire-and-forget) |
| Integration with events | 50 | ✅ | Necessary for status updates |

**Total Useful Lines:** ~133 / 133 = **100% useful concept, 50% implementation quality**

---

### **Commit #2: `57ba402` - Prometheus Metrics**

#### What Was Added (209 lines in main.py):

| Feature | Lines | Useful? | Notes |
|---------|-------|---------|-------|
| `/api/metrics/agent` JSON endpoint | 70 | ⚠️ | Duplicates existing metrics |
| `/api/metrics/agent/prometheus` | 100 | ❌ | **Prometheus not deployed** - unused code |
| `DELETE /api/metrics/agent/reset` | 39 | ⚠️ | Debug endpoint, low value |

**Total Useful Lines:** ~30 / 209 = **14% useful** (and only if you deploy Prometheus)

---

## Root Cause Analysis: "Stuck on Connecting" Issue

### **What We Know:**

1. ✅ Backend creates room successfully
2. ✅ Backend returns token to frontend
3. ✅ Pipecat agent connects to LiveKit room
4. ❌ **Frontend never connects to LiveKit room**
5. ❌ No error logged in backend
6. ✅ Works on second attempt (after page refresh)

### **This is NOT a Backend Problem**

The commits tried to fix backend spawn reliability, but:
- Backend spawn **works** (Pipecat connects)
- Frontend connection **fails** (user doesn't join)

**The fix was applied to the wrong layer.**

---

### **Possible Root Causes (Require Investigation):**

#### **Theory #1: Token Expiry Race Condition**

**Hypothesis:** Frontend receives token, but tries to connect after it expires

**Evidence Needed:**
- Token TTL in `generate_livekit_token()`: 2 hours (✅ unlikely)
- Time between token generation and frontend connection attempt
- LiveKit error logs on frontend

**Likelihood:** Low (2-hour TTL is generous)

---

#### **Theory #2: Frontend LiveKit Connection Error (Silent Failure) - MOST LIKELY**

**Hypothesis:** Frontend LiveKit client fails to connect, but JavaScript thinks it succeeded

**Evidence:**
- ✅ Frontend console shows "Connected", "Ready"
- ✅ Frontend UI shows "Connecting..." (contradicts console)
- ✅ LiveKit dashboard shows only agent, not user
- ✅ No errors in console
- ✅ Works on retry (state reset fixes it)

**This is a RACE CONDITION or STATE MACHINE BUG in the frontend.**

**Possible Scenarios:**

**Scenario A: Frontend tracks wrong state**
```javascript
// Frontend code might do:
setConnectionState('connected');  // Sets state too early
// But actual WebSocket is still connecting...
// UI reads stale state → shows "Connecting"
// Console reads new state → logs "Connected"
```

**Scenario B: Promise resolves before actual connection**
```javascript
await room.connect();  // Returns immediately
console.log('Connected');  // Logs this
// But WebSocket handshake still in progress...
// Handshake fails silently later
```

**Scenario C: Event listener timing**
```javascript
// If we attach listeners AFTER connection attempt:
room.connect();  // Starts connecting
room.on('connected', () => {...});  // Too late! Missed the event
// Frontend thinks it's still connecting
```

**Investigation Required:**
```javascript
// Add detailed state tracking
room.on('connectionStateChanged', (state) => {
  console.error('[LIVEKIT_STATE]', state, Date.now());
  reportConnectionEvent('livekit_state_changed', { state });
});

room.on('connected', () => {
  console.error('[LIVEKIT_CONNECTED]', Date.now());
  reportConnectionEvent('livekit_connected');
});

room.on('disconnected', () => {
  console.error('[LIVEKIT_DISCONNECTED]', Date.now());
  reportConnectionEvent('livekit_disconnected');
});

room.on('reconnecting', () => {
  console.error('[LIVEKIT_RECONNECTING]', Date.now());
  reportConnectionEvent('livekit_reconnecting');
});

// Track WebSocket state directly
const ws = room._engine?.client?.ws;
if (ws) {
  console.error('[WEBSOCKET_STATE]', ws.readyState);
  // 0 = CONNECTING, 1 = OPEN, 2 = CLOSING, 3 = CLOSED
}
```

**Likelihood:** **VERY HIGH** - console says "connected" but LiveKit shows user not in room = frontend bug

**Why it works on retry:**
- First attempt: Frontend gets into bad state
- Refresh: Clean slate, state machine resets
- Second attempt: Works because no stale state

---

#### **Theory #3: Agent Status Reporter Blocking Frontend Connection**

**Hypothesis:** New `AgentStatusReporter` interferes with LiveKit transport initialization

**Evidence in Code (voice_assistant.py:584):**
```python
# Status reporter initialized BEFORE user can join
status_reporter = AgentStatusReporter(transport)

# Then agent connects...
# Then waits for user...
# But status updates might block user connection?
```

**Investigation Required:**
- Disable `AgentStatusReporter` temporarily and test
- Check if `transport.send_message()` blocks during initialization

**Likelihood:** Medium - timing correlates with issue appearance

---

#### **Theory #4: Race Condition in `on_first_participant_joined` - LIKELY CAUSE OF NEW ISSUES**

**Hypothesis:** Agent sends status too early, and opening message queues before user actually joins

**Evidence in Code (voice_assistant.py:767):**
```python
@transport.event_handler("on_first_participant_joined")
async def on_first_participant_joined(transport, participant_id):
    logger.info(f"participant_joined participant_id={participant_id}")

    # Send "ready" status immediately
    await status_reporter.report_ready()

    # Wait only 0.2 seconds
    await asyncio.sleep(PARTICIPANT_GREETING_DELAY)  # 0.2s

    # Send opening line
    await task.queue_frame(TTSSpeakFrame(greeting))
```

**Critical Questions:**
1. Does `on_first_participant_joined` fire when **agent** joins? (Wrong)
2. Or when **first user** joins? (Correct)
3. Can it fire **twice** if agent joins, then user joins?

**Timeline of What's Probably Happening:**

```
T+0s:   Agent process starts
T+5s:   Agent connects to LiveKit room
T+5.1s: on_first_participant_joined FIRES (agent = first participant)
T+5.2s: Status "ready" sent to... nobody (no user in room yet)
T+5.4s: Opening message queued (no user to hear it yet)
T+10s:  User attempts to join (but fails silently)
T+15s:  User still trying to connect
T+20s:  Connection succeeds (after retry)
T+20.1s: on_first_participant_joined FIRES AGAIN (user = "first" participant?)
T+20.2s: Status "ready" sent to user
T+20.4s: Opening message queued AGAIN
T+20.5s: User hears first opening message (from T+5.4s)
T+22s:  User hears SECOND opening message (from T+20.4s) ← ECHO/REPEAT
```

**This explains:**
- ✅ Why opening message repeats (queued twice)
- ✅ Why echo happens in first 30 seconds (two messages close together)
- ✅ Why console says "Connected" but UI shows "Connecting" (status sent before user joined)

**The Bug:**
`on_first_participant_joined` is probably firing when the **AGENT** joins, not when the **USER** joins.

**How to Test:**
```python
@transport.event_handler("on_first_participant_joined")
async def on_first_participant_joined(transport, participant_id):
    # Log who joined
    logger.error(f"FIRST_PARTICIPANT_JOINED participant_id={participant_id}")

    # Get all participants
    all_participants = getattr(transport, 'participants', [])
    logger.error(f"ALL_PARTICIPANTS count={len(all_participants)} ids={[p for p in all_participants]}")

    # Check if this is the agent or user
    # Agent identity is usually "agent" or the session_id
    # User identity is the userName

    if participant_id == "agent" or "agent" in participant_id.lower():
        logger.error(f"IGNORING_AGENT_JOIN - waiting for user")
        return  # Don't send opening message for agent!

    # Only proceed if this is actually a user
    logger.error(f"USER_JOINED participant_id={participant_id}")
    # Now send status and opening message...
```

**Likelihood:** **VERY HIGH** - this is probably the root cause of new regressions

**Fix:**
1. Check participant identity before sending opening message
2. Only fire on **user** join, not agent join
3. Add safeguard to prevent duplicate opening messages

---

#### **Theory #5: Redis Log Cutoff Breaking Critical Logs**

**Evidence (tasks.py:266):**
```python
if current_time < redis_cutoff_time:
    # Log to Redis for connection detection
    redis_client.rpush(f'agent:{session_id}:logs', line)
else:
    # STOP writing to Redis after 60s
    # Orchestrator can't see errors after this point
```

**Problem:** If connection fails at T+65s, orchestrator has no logs to detect it

**Likelihood:** Low for "stuck connecting" (happens early), but **breaks monitoring**

---

## Critical Missing: No Monitoring or Diagnostics

### **What Logs Do We Have?**

| Event | Backend Logs? | Frontend Logs? | LiveKit Logs? | Metrics? |
|-------|---------------|----------------|---------------|----------|
| Session start requested | ✅ Yes | ❌ Console only | ❌ No | ❌ No |
| Token generated | ✅ Yes | ❌ No | ❌ No | ❌ No |
| Agent joins room | ✅ Yes | ❌ No | ✅ Dashboard only | ❌ No |
| **User tries to join room** | ❌ **NO** | ❌ **Console only** | ❌ **No API** | ❌ **NO** |
| User connection fails | ❌ **NO** | ❌ **Console only** | ❌ **No API** | ❌ **NO** |
| Opening message sent | ✅ Yes | ❌ No | ❌ No | ❌ No |
| Audio echo occurs | ❌ **NO** | ❌ **No** | ❌ **No** | ❌ **NO** |

**Critical Gap:** We have **ZERO visibility** into frontend connection failures.

**Why Console Logs Are Not Enough:**
- Users won't open developer console
- Console shows "Connected" even when connection failed
- Production users won't report console logs
- We need **automatic backend reporting** of frontend state

---

### **What We Need to Add:**

#### **1. Frontend Connection Monitoring (Dual-Storage Strategy: Redis + Database)**

### **The Two-Tier Storage Strategy:**

**Tier 1: Redis (Real-Time Debugging - 24 Hours)**
- Purpose: Active session monitoring and real-time debugging
- Retention: 24 hours, then auto-expires
- Speed: < 5ms write latency
- Use case: Debug issues while session is active or recent

**Tier 2: Database (Long-Term Analysis - Permanent)**
- Purpose: Historical analysis and trend detection
- Retention: Permanent (or 90 days with cleanup)
- Speed: 50-200ms write latency
- Use case: Analyze patterns across weeks/months

### **Why Use BOTH Redis AND Database:**

**Why Redis for Real-Time:**
- ✅ **Lightning fast** - 5ms writes vs 100-200ms for database
- ✅ **Non-blocking** - Frontend doesn't wait for response
- ✅ **Auto-cleanup** - TTL expires old data automatically
- ✅ **Query during session** - Can debug while user is still connected
- ✅ **High throughput** - Can handle 1000+ events/second
- ✅ **Ordered lists** - Events stay in chronological order

**Why Database for Long-Term:**
- ✅ **Permanent storage** - Analyze patterns over months
- ✅ **Complex queries** - SQL joins, aggregations, filtering
- ✅ **Compliance** - Audit trails for production incidents
- ✅ **Alerting** - Detect patterns like "10% failure rate"
- ✅ **Reporting** - Generate reports for stakeholders

**Problems with Database-Only:**
- ❌ **Too slow** - 100-200ms writes block frontend
- ❌ **No auto-cleanup** - Millions of rows accumulate
- ❌ **Can't query fast** - Takes seconds to query recent events
- ❌ **Connection pool exhaustion** - 1000 events = 1000 DB connections

**Problems with Redis-Only:**
- ❌ **Data loss** - After 24 hours, debugging evidence gone
- ❌ **No historical analysis** - Can't see trends over time
- ❌ **No complex queries** - Can't do "show all Chrome failures"

---

### **Implementation with Dual Storage:**
```javascript
// Frontend reports every state change to backend
async function reportConnectionEvent(event, data = {}) {
  try {
    // Non-blocking fetch - don't wait for response
    fetch('/api/session/connection-event', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionId,
        event,
        timestamp: Date.now(),
        userAgent: navigator.userAgent,
        ...data
      }),
      keepalive: true  // Send even if page closes
    }).catch(() => {}); // Swallow errors silently
  } catch (e) {
    // Never let monitoring break the app
  }
}

// Call at every step
reportConnectionEvent('session_start_requested');
reportConnectionEvent('token_received', { tokenLength: token.length });
reportConnectionEvent('livekit_connecting', { serverUrl });
reportConnectionEvent('livekit_connected');  // This won't fire when it fails!
reportConnectionEvent('first_audio_received');
```

**Backend Endpoint (Dual Storage):**
```python
@app.post("/api/session/connection-event")
async def record_connection_event(request: Request):
    """
    Fast, non-blocking endpoint to track frontend connection lifecycle.

    TWO-TIER STORAGE:
    1. Redis: Immediate storage (5ms) for real-time debugging (24h TTL)
    2. Database: Background async write for long-term analysis (permanent)

    Frontend gets instant response, database write happens in background.
    """
    try:
        data = await request.json()
        session_id = data.get('sessionId')
        event = data.get('event')
        timestamp = data.get('timestamp')

        # Build event data
        event_data = {
            'event': event,
            'timestamp': timestamp,
            'userAgent': data.get('userAgent', 'unknown'),
            'sessionId': session_id,
            **data
        }

        # ============================================================
        # TIER 1: Write to Redis (FAST - 5ms)
        # ============================================================
        # Store in Redis list (ordered by time)
        redis_client.rpush(
            f"session:{session_id}:frontend_events",
            json.dumps(event_data)
        )

        # Auto-expire after 24 hours (86400 seconds)
        redis_client.expire(f"session:{session_id}:frontend_events", 86400)

        # Keep only last 200 events per session (prevent memory bloat)
        redis_client.ltrim(f"session:{session_id}:frontend_events", -200, -1)

        # ============================================================
        # TIER 2: Write to Database (SLOW - async background task)
        # ============================================================
        # Use asyncio.create_task for non-blocking database write
        # This returns immediately, database write happens in background
        asyncio.create_task(
            store_event_to_database(event_data)
        )

        # Fast response - don't wait for database
        return {"status": "ok"}

    except Exception as e:
        # Never fail - monitoring must not break app
        logger.warning(f"connection_event_recording_failed error={str(e)}")
        return {"status": "ok"}  # Return OK even on error


async def store_event_to_database(event_data: dict):
    """
    Background task to store event in database for long-term analysis.

    This runs asynchronously - doesn't block the API response.
    If it fails, we still have Redis data for debugging.
    """
    try:
        from backend.shared.services import Database

        # Store in database table: connection_events
        await Database.execute(
            """
            INSERT INTO connection_events (
                session_id,
                event_type,
                timestamp_ms,
                user_agent,
                event_data,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            event_data.get('sessionId'),
            event_data.get('event'),
            event_data.get('timestamp'),
            event_data.get('userAgent'),
            json.dumps(event_data)  # Store full JSON for flexibility
        )

        logger.debug(f"connection_event_stored_to_db session_id={event_data.get('sessionId')} event={event_data.get('event')}")

    except Exception as e:
        # Log but don't fail - Redis still has the data
        logger.warning(f"database_event_storage_failed session_id={event_data.get('sessionId')} error={str(e)}")
```

**Database Schema:**
```sql
-- Table for long-term connection event storage
CREATE TABLE connection_events (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    user_agent TEXT,
    event_data JSONB,  -- Full JSON for flexibility
    created_at TIMESTAMP DEFAULT NOW(),

    -- Indexes for fast queries
    INDEX idx_session_id (session_id),
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at),
    INDEX idx_event_data_gin (event_data) USING GIN  -- For JSON queries
);

-- Auto-cleanup old events (optional - keep 90 days)
-- Run this as a daily cron job
DELETE FROM connection_events
WHERE created_at < NOW() - INTERVAL '90 days';
```

**Query Events for Debugging:**
```python
@app.get("/api/session/{session_id}/connection-timeline")
async def get_connection_timeline(
    session_id: str,
    source: str = 'redis'  # 'redis' or 'database'
):
    """
    Get complete frontend connection timeline for debugging.

    Args:
        session_id: Session to debug
        source: 'redis' (last 24h, fast) or 'database' (all history, slower)

    Returns:
        Timeline of events showing exactly what the user experienced
    """

    if source == 'redis':
        # =====================================================
        # Query Redis (Fast - for recent sessions)
        # =====================================================
        events = redis_client.lrange(f"session:{session_id}:frontend_events", 0, -1)

        if not events:
            # Not in Redis - try database
            logger.info(f"timeline_not_in_redis session_id={session_id} falling_back=database")
            source = 'database'  # Fall through to database query
        else:
            timeline = []
            first_timestamp = None

            for event_json in events:
                event = json.loads(event_json)
                timestamp = event['timestamp']

                if first_timestamp is None:
                    first_timestamp = timestamp

                # Show relative time
                event['elapsed_ms'] = timestamp - first_timestamp
                timeline.append(event)

            return {
                "session_id": session_id,
                "source": "redis",
                "ttl_remaining": redis_client.ttl(f"session:{session_id}:frontend_events"),
                "events": timeline,
                "total_events": len(timeline)
            }

    if source == 'database':
        # =====================================================
        # Query Database (Slower - for historical sessions)
        # =====================================================
        from backend.shared.services import Database

        rows = await Database.fetch(
            """
            SELECT
                event_type,
                timestamp_ms,
                user_agent,
                event_data,
                created_at
            FROM connection_events
            WHERE session_id = $1
            ORDER BY timestamp_ms ASC
            """,
            session_id
        )

        if not rows:
            return {
                "session_id": session_id,
                "source": "database",
                "events": [],
                "total_events": 0,
                "message": "No events found for this session"
            }

        timeline = []
        first_timestamp = None

        for row in rows:
            event_data = json.loads(row['event_data']) if isinstance(row['event_data'], str) else row['event_data']
            timestamp = event_data.get('timestamp', row['timestamp_ms'])

            if first_timestamp is None:
                first_timestamp = timestamp

            event_data['elapsed_ms'] = timestamp - first_timestamp
            timeline.append(event_data)

        return {
            "session_id": session_id,
            "source": "database",
            "events": timeline,
            "total_events": len(timeline),
            "oldest_event": rows[0]['created_at'].isoformat() if rows else None
        }
```

**Usage Examples:**

```bash
# Debug recent session (last 24 hours) - FAST
curl http://localhost:8000/api/session/{session_id}/connection-timeline?source=redis

# Debug old session (any time) - SLOWER
curl http://localhost:8000/api/session/{session_id}/connection-timeline?source=database

# Auto-fallback: Try Redis first, fall back to database if not found
curl http://localhost:8000/api/session/{session_id}/connection-timeline
```

**Example Timeline Output:**
```json
{
  "events": [
    {"event": "session_start_requested", "elapsed_ms": 0},
    {"event": "token_received", "elapsed_ms": 450},
    {"event": "livekit_connecting", "elapsed_ms": 500},
    // "livekit_connected" MISSING - this is the failure!
    {"event": "timeout_waiting", "elapsed_ms": 30000}
  ]
}
```

**This lets us see EXACTLY where the user got stuck.**

---

## **Deep Dive: Redis vs Database Storage**

### **How Long Data Lasts:**

| Storage | Retention | Why This Duration? |
|---------|-----------|-------------------|
| **Redis** | 24 hours | Recent debugging needs (95% of issues debugged within 24h) |
| **Database** | 90 days | Historical analysis, compliance, trend detection |

### **When to Use Redis vs Database:**

**Use Redis Query When:**
- ✅ Session happened today
- ✅ Debugging active issue
- ✅ Need answer in <50ms
- ✅ User is waiting for response

**Use Database Query When:**
- ✅ Session happened last week/month
- ✅ Analyzing patterns across many sessions
- ✅ Generating reports
- ✅ Compliance audit

### **How to Debug Later:**

**Scenario 1: User reports issue TODAY (within 24 hours)**
```bash
# Query Redis (fast)
GET /api/session/{session_id}/connection-timeline?source=redis

# Returns in 20-50ms
{
  "source": "redis",
  "ttl_remaining": 72341,  // 20 hours left before expiry
  "events": [
    {"event": "session_start_requested", "elapsed_ms": 0},
    {"event": "token_received", "elapsed_ms": 450},
    {"event": "livekit_connecting", "elapsed_ms": 500},
    // "livekit_connected" MISSING - found the bug!
  ]
}
```

**Scenario 2: Analyzing issue from LAST WEEK**
```bash
# Query Database (slower but has history)
GET /api/session/{session_id}/connection-timeline?source=database

# Returns in 200-500ms
{
  "source": "database",
  "oldest_event": "2026-01-17T10:30:00Z",
  "events": [
    // Same data, but queried from database
  ]
}
```

**Scenario 3: Pattern Analysis Across 1000 Sessions**
```sql
-- This is why we need database (can't do this in Redis)
SELECT
    event_type,
    COUNT(*) as count,
    AVG(elapsed_ms) as avg_time
FROM (
    SELECT
        session_id,
        event_type,
        timestamp_ms - FIRST_VALUE(timestamp_ms) OVER (
            PARTITION BY session_id
            ORDER BY timestamp_ms
        ) as elapsed_ms
    FROM connection_events
    WHERE created_at > NOW() - INTERVAL '7 days'
) subquery
GROUP BY event_type
ORDER BY avg_time DESC;

-- Results:
-- livekit_connecting: avg 15,340ms (slow!)
-- token_received: avg 450ms (normal)
-- session_start: avg 50ms (fast)
```

### **Auto-Cleanup & Memory Management:**

**Redis Auto-Expiry:**
```python
# Set 24-hour TTL on first write
redis_client.expire(f"session:{session_id}:frontend_events", 86400)

# Redis automatically deletes data after 24 hours
# No manual cleanup needed!

# Check how much time left:
ttl = redis_client.ttl(f"session:{session_id}:frontend_events")
# Returns: 72341 (20 hours remaining) or -2 (expired)
```

**Database Cleanup (Optional - run daily):**
```sql
-- Delete events older than 90 days
DELETE FROM connection_events
WHERE created_at < NOW() - INTERVAL '90 days';

-- Or keep forever for compliance
-- Just ensure you have enough disk space
```

**Memory Usage Calculation:**

```
Redis Memory per Session:
- Average event: 200 bytes JSON
- Max events per session: 200 (limited by LTRIM)
- Memory per session: 200 × 200 = 40KB
- 1000 concurrent sessions: 40MB
- Cost: Negligible (Redis can handle GBs)

Database Storage:
- Average event: 500 bytes (with indexes)
- Events per day: 10,000 sessions × 10 events = 100,000 events
- Daily storage: 100,000 × 500 bytes = 50MB/day
- 90 days retention: 50MB × 90 = 4.5GB
- Cost: Very cheap (database can handle TBs)
```

### **What Happens When Redis Expires?**

**Timeline:**
```
T+0h:    User has connection issue
T+1h:    You start debugging - query Redis ✅ (data still there)
T+23h:   Still debugging - query Redis ✅ (data still there)
T+24h:   Redis auto-expires data ❌ (Redis data gone)
T+25h:   Query database ✅ (data still there - permanent backup)
T+7 days: Query database ✅ (can analyze historical patterns)
```

**Failover Logic:**
```python
# API automatically tries Redis first, falls back to database
GET /api/session/{session_id}/connection-timeline

# Backend logic:
1. Try Redis (fast)
2. If not found (expired or never existed), query database
3. Return data from whichever has it

# User doesn't need to know which storage was used
```

### **Real-World Example:**

**Day 1 (Issue Occurs):**
```
10:00 AM: User has "stuck connecting" issue
10:01 AM: Frontend reports events to backend
10:01 AM: Backend writes to Redis (5ms) ✅
10:01 AM: Backend queues database write (background) ✅
10:05 AM: Database write completes ✅

Result: Data now in BOTH Redis and Database
```

**Day 1 (Debugging):**
```
11:00 AM: You query timeline
11:00 AM: API checks Redis first → finds data ✅
11:00 AM: Returns in 30ms (fast!)

Result: Quick debugging with Redis
```

**Day 2 (Follow-up Debugging):**
```
Next day 10:00 AM: You query timeline again
10:00 AM: API checks Redis first → data expired ❌
10:00 AM: API falls back to database → finds data ✅
10:00 AM: Returns in 200ms (slower but still acceptable)

Result: Still can debug, just slightly slower
```

**Week Later (Pattern Analysis):**
```
7 days later: Analyzing 1000 failed sessions
Query: "Show me all sessions where livekit_connected never fired"

-- This REQUIRES database (can't do complex queries in Redis)
SELECT DISTINCT session_id
FROM connection_events e1
WHERE NOT EXISTS (
    SELECT 1 FROM connection_events e2
    WHERE e2.session_id = e1.session_id
    AND e2.event_type = 'livekit_connected'
)
AND e1.created_at > NOW() - INTERVAL '7 days';

Result: Found 97 sessions with this pattern
Common factor: All using Chrome 120 on Mac
Bug identified: Chrome 120 WebSocket bug
```

---

### **Summary: Why Dual Storage?**

| Need | Redis | Database | Winner |
|------|-------|----------|--------|
| Debug today's issues | ✅ 30ms | ⚠️ 200ms | Redis |
| Debug last week's issues | ❌ Expired | ✅ 200ms | Database |
| Pattern analysis | ❌ No SQL | ✅ Full SQL | Database |
| Real-time monitoring | ✅ 5ms writes | ❌ 100ms writes | Redis |
| Permanent audit trail | ❌ 24h TTL | ✅ Permanent | Database |
| Memory efficiency | ✅ Auto-expires | ⚠️ Manual cleanup | Redis |

**Best Practice: Use BOTH**
- Redis for speed and real-time (24 hours)
- Database for history and analysis (permanent)
- Frontend gets instant response (doesn't wait for database)
- You can debug issues anytime (even months later)

#### **2. LiveKit Webhook for User Join**

**Current webhooks (orchestrator/main.py:865):**
```python
if event_type in ['participant_left', 'room_finished']:
    # We handle disconnect...
```

**Missing:**
```python
if event_type == 'participant_joined':
    # We need to track WHEN user joins
    # Correlate with session start time
    # Alert if >15 seconds delay
```

#### **3. Structured Error Tracking**

**Create:**
```
POST /api/session/{sessionId}/error
{
  "error_type": "connection_timeout",
  "component": "frontend_livekit",
  "timestamp": "2026-01-24T10:30:00Z",
  "user_agent": "Chrome 120.0",
  "network_info": {...}
}
```

**Store in Redis:**
```
redis_client.lpush(f"session:{session_id}:errors", json.dumps(error))
```

#### **4. End-to-End Latency Tracking**

**Track Every Step:**
```
T+0ms:   Frontend: Session start requested
T+500ms: Backend: Token generated
T+800ms: Backend: Agent spawn started
T+3s:    Backend: Agent joined room
T+5s:    Frontend: Attempting LiveKit connection  ← MISSING
T+7s:    Frontend: Connection established         ← MISSING
T+8s:    Backend: User participant joined         ← MISSING
T+9s:    Frontend: Opening message received       ← MISSING
```

**Store as metrics:**
```python
await redis_client.hset(f"session:{session_id}:timeline", mapping={
    "session_start": 0,
    "token_generated": 500,
    "agent_spawn_started": 800,
    "agent_joined": 3000,
    "user_connection_attempt": 5000,    # NEW
    "user_connection_success": 7000,    # NEW
    "user_joined": 8000,                 # NEW
    "opening_message_received": 9000     # NEW
})
```

---

## Investigation Plan (Before Any Code Changes)

### **Phase 1: Reproduce and Capture (1-2 days)**

**Goal:** Get detailed logs for a failing case

1. **Add Frontend Logging:**
   ```javascript
   // Detailed LiveKit connection logging
   console.log('[LIVEKIT] Initializing room connection');
   console.log('[LIVEKIT] Token received:', token.substring(0, 20));
   console.log('[LIVEKIT] Connecting to:', serverUrl);

   room.on('connectionStateChanged', (state) => {
     console.error('[LIVEKIT] State:', state, new Date().toISOString());
   });

   room.on('connectionError', (error) => {
     console.error('[LIVEKIT] ERROR:', error);
   });
   ```

2. **Add Backend Correlation:**
   ```python
   # Track if user joins within 15 seconds
   asyncio.create_task(check_user_joined(session_id, timeout=15))
   ```

3. **Monitor Production:**
   - Wait for ~10 failures (10% × 100 attempts = 10 failures expected)
   - Collect frontend console logs (need user cooperation OR session replay tool)
   - Check LiveKit dashboard timestamps

---

### **Phase 2: Correlate Data (1 day)**

**Questions to Answer:**

1. **Is this a network issue?**
   - Check frontend IP addresses
   - Check for corporate firewalls blocking WebSocket
   - Check browser versions (Safari WebRTC issues?)

2. **Is this a timing issue?**
   - Measure time between token generation and connection attempt
   - Check if failures correlate with high load

3. **Is this a LiveKit issue?**
   - Check LiveKit server logs
   - Check for rate limiting
   - Check for connection limits

4. **Is this browser-specific?**
   - Correlate failures with User-Agent
   - Test on different browsers

---

### **Phase 3: Hypothesis Testing (2-3 days)**

**Test #1: Disable Status Reporter**
```python
# Temporarily comment out
# status_reporter = AgentStatusReporter(transport)
```
- Deploy to staging
- Run 100 sessions
- Check if "stuck connecting" goes away
- Check if opening message still repeats

**Test #2: Add Delay Before Opening Message**
```python
await asyncio.sleep(2)  # Wait 2s after user joins
await task.queue_frame(TTSSpeakFrame(greeting))
```
- Check if repeated message goes away

**Test #3: Check Event Handler Firing**
```python
@transport.event_handler("on_first_participant_joined")
async def on_first_participant_joined(transport, participant_id):
    logger.error(f"FIRST_PARTICIPANT participant_id={participant_id}")
    # Is this the agent or the user?
    # Log ALL participants in room
    logger.error(f"ALL_PARTICIPANTS count={len(transport.participants)}")
```

**Test #4: Frontend Timeout Adjustment**
```javascript
// If frontend has connection timeout, increase it
const room = new Room({
  connectionTimeout: 30000  // Try 30s instead of default
});
```

---

## Recommendations

### **Immediate Actions (This Week):**

1. ✅ **DO NOT make code changes yet**
2. ✅ **Add comprehensive logging** (frontend + backend)
3. ✅ **Reproduce issue in staging** with full logging
4. ✅ **Collect 10+ failure cases** with complete data
5. ✅ **Analyze correlation** between failures

### **After Investigation (Next Week):**

1. **If root cause is frontend connection:**
   - Fix frontend LiveKit initialization
   - Add retry logic
   - Add better error messages

2. **If root cause is backend race condition:**
   - Fix event handler logic
   - Add participant type checking (agent vs user)

3. **If root cause is LiveKit server:**
   - Configure LiveKit properly
   - Add connection pooling
   - Consider LiveKit Cloud vs self-hosted

### **Commit Decisions:**

#### **Revert Immediately:**
- ❌ 90s timeout (no evidence needed, use 45s)
- ❌ AGENT_ALIVE signal (solves non-problem)
- ❌ Disabled exponential backoff (harmful)
- ❌ Prometheus endpoint (not deployed)
- ❌ Redis log cutoff at 60s (breaks debugging)

#### **Keep with Fixes:**
- ⚠️ AgentStatusReporter (fix fire-and-forget → await delivery)
- ⚠️ Metrics collection (simplify, remove duplicates)

#### **Add New (Based on Investigation):**
- ✅ Frontend connection monitoring
- ✅ User join tracking
- ✅ Error reporting API
- ✅ End-to-end latency metrics

---

## Key Insights

### **What Went Wrong:**

1. **No investigation before fix** - jumped to conclusions
2. **No metrics to validate problem** - guessed cold start was 30-40s
3. **No hypothesis testing** - deployed 589 lines without A/B testing
4. **No monitoring for actual failure mode** - can't see user connection failures
5. **Confirmation bias** - saw "timeout" and assumed spawn was slow

### **What Should Have Happened:**

1. Add logging to measure cold start times → discover it's ~15s
2. Add frontend connection monitoring → discover failures are client-side
3. Reproduce issue in staging with logs → find root cause
4. Write targeted fix (probably 10 lines)
5. Deploy with A/B test → validate improvement

---

## Production Risk Assessment

### **Current State:**
- ⚠️ 10% "stuck connecting" failure rate (pre-existing)
- ⚠️ Opening message repeats (new regression)
- ⚠️ Echo in first 30s (new regression)
- ⚠️ Zero visibility into failures (monitoring gap)

### **If We Revert Commits:**
- ✅ Opening message repeat: Likely fixed
- ✅ Echo issue: Likely fixed
- ❌ "Stuck connecting": Still there (was there before)
- ❌ No status updates: UX slightly worse

### **If We Keep Commits:**
- ❌ All issues persist
- ❌ Harder to debug (more complexity)
- ❌ Future maintenance burden (unused Prometheus code)

---

## Refined Analysis Based on New Information

### **What We Now Know:**

1. **Original Issue May Be Fixed:**
   - Can't safely test in production (new regressions prevent testing)
   - Might have been resolved by accident via status reporter or timeout changes
   - Or might still exist but masked

2. **Frontend Console Lies:**
   - Console shows "Connected", "Ready"
   - But LiveKit dashboard shows user NOT in room
   - This is a **silent failure** - frontend JavaScript state machine bug

3. **Failure Window is 0-30 seconds:**
   - Connection normally takes max 10 seconds
   - All failures happen early (first 30 seconds)
   - Only Pipecat agent visible in LiveKit room

4. **New Regressions Suggest Event Handler Bug:**
   - Opening message repeats
   - Echo in first 30 seconds
   - Timing correlates with `on_first_participant_joined` likely firing for AGENT join, not USER join

### **Root Cause Hypothesis (High Confidence):**

**For Original "Stuck Connecting" Issue:**
- Frontend LiveKit client enters bad state
- JavaScript thinks connection succeeded (logs "Connected")
- WebSocket never actually established
- Frontend UI correctly shows "Connecting" (reading actual WebSocket state)
- Console incorrectly shows "Connected" (reading JavaScript state)
- **This is a frontend bug, not backend**

**For New Regressions (Message Repeat, Echo):**
- `on_first_participant_joined` fires when **agent** joins room (wrong)
- Status "ready" sent when no user in room
- Opening message queued when no user to hear it
- User joins later (or on second attempt)
- Event fires again (or doesn't, but old message still in queue)
- User hears opening message twice
- **This is a backend event handler bug**

---

## Conclusion

**The commits were a shotgun approach that may have accidentally fixed one issue while creating others:**

1. ❓ May have fixed "stuck connecting" (can't verify safely)
2. ✅ Introduced new issues (message repeat, echo)
3. ❌ No investigation or monitoring added
4. ❌ Can't test in production due to new regressions

**Critical Realization:**
- We're flying blind - no monitoring of frontend state
- Console logs are unreliable (show wrong state)
- Need automated backend reporting to know what's really happening

**Recommended Path Forward:**

**Phase 1: Add Monitoring First (2-3 days)**
1. ✅ Add frontend connection event reporting (to Redis, not DB)
2. ✅ Add backend timeline tracking for each session
3. ✅ Deploy monitoring to staging
4. ✅ Reproduce failures with full visibility

**Phase 2: Fix Event Handler Bug (1 day)**
1. ✅ Fix `on_first_participant_joined` to ignore agent join
2. ✅ Only send opening message when USER joins
3. ✅ Add safeguard against duplicate messages
4. ✅ Deploy to staging and verify regressions fixed

**Phase 3: Fix Frontend Silent Failure (2-3 days)**
1. ✅ Review frontend LiveKit connection code
2. ✅ Fix state machine bug (console vs actual state)
3. ✅ Add proper error handling for connection failures
4. ✅ Add retry logic with exponential backoff
5. ✅ Show actual error messages to user (not just "Connecting...")

**Phase 4: Test Original Issue (1 day)**
1. ✅ Revert timeout to 45s (not 30s, not 90s)
2. ✅ Re-enable exponential backoff (but lower max to 30s)
3. ✅ Test 100+ sessions in staging
4. ✅ Check if "stuck connecting" still occurs with fixes

**Phase 5: Gradual Rollout (1 week)**
1. ✅ Deploy to 10% of production traffic
2. ✅ Monitor for 48 hours
3. ✅ If stable, increase to 50%
4. ✅ If stable, full rollout

**This is a monitoring-first, investigate-second, then-fix approach.**

---

## Immediate Next Steps

**Today:**
1. Create the frontend connection event reporting endpoint (Redis-based)
2. Add frontend calls to `reportConnectionEvent()` at every step
3. Add backend timeline query endpoint
4. Deploy to staging

**Tomorrow:**
1. Reproduce "stuck connecting" in staging with monitoring
2. Capture complete frontend event timeline
3. Identify exact point of failure
4. Fix `on_first_participant_joined` to check participant identity

**This Week:**
1. Fix frontend state machine bug
2. Test 100+ sessions in staging
3. Verify both issues fixed
4. Plan production rollout

**The key insight: Monitor first, fix second. We've been coding blind.**

---

## Appendix: Questions for Investigation

### **Frontend Questions:**
1. What exact error does LiveKit client show when connection fails?
2. Does the connection work on retry because of timing or because of state reset?
3. Are there browser console errors during "stuck connecting"?
4. What is the frontend's LiveKit client version?

### **Backend Questions:**
1. Does `on_first_participant_joined` fire when agent joins or when user joins?
2. Can we reliably distinguish agent from user participants?
3. What is the actual average cold start time? (add metrics)
4. Are there any errors in LiveKit server logs?

### **Network Questions:**
1. Are failures correlated with specific geographic regions?
2. Are failures correlated with specific ISPs or networks?
3. Are WebSocket connections being blocked by firewalls?
4. Is there a pattern in successful vs failed attempts?

---

**End of Report**

*Next Steps: Schedule investigation session with full logging enabled*
