# Executive Summary: Connection Failures & Commit Analysis

**Date:** 2026-01-24
**Status:** Critical - Production Issue
**Action Required:** Revert commits + Add monitoring

---

## Part 1: Two Recent Commits - Analysis

### Commits Under Review:
- `57ba402` - Prometheus metrics endpoints (209 lines)
- `69a690b` - Agent spawn reliability improvements (589 lines)

### What They Caused:

**New Regressions (appeared after commits):**
1. ✅ **Opening message repeats** - User hears greeting twice
2. ✅ **Echo sound** - Audio artifacts in first 30 seconds

**Original Issue Status:**
- ⚠️ **Unknown if fixed** - Can't safely test in production due to new regressions
- May have accidentally fixed "stuck connecting" issue, but at what cost?

### Commit Usefulness Score:

| Commit | Total Lines | Useful Lines | Usefulness % | Verdict |
|--------|-------------|--------------|--------------|---------|
| `69a690b` (Reliability) | 589 | ~90 | **15%** | ❌ Revert |
| `57ba402` (Prometheus) | 209 | ~30 | **14%** | ❌ Revert |

**Key Problems:**
- 90s timeout (was 30s) - No evidence cold starts take >30s
- AGENT_ALIVE signal - Solves imaginary problem
- Disabled exponential backoff - Creates thundering herd during outages
- Prometheus endpoint - Not deployed, unused code
- Redis log cutoff at 60s - Breaks debugging for long sessions

**Only Good Feature:**
- AgentStatusReporter - Good idea, poor implementation (fire-and-forget)

### Recommendation:
**✅ REVERT BOTH COMMITS**

Reasons:
1. Introduced 2 new regressions (echo, repeated message)
2. Only 15% of code is useful
3. No investigation was done before implementing
4. Can't test if original issue is fixed (new issues prevent testing)

---

## Part 2: The Core Issue - Connection Failures

### The Real Problem (~10% Failure Rate)

**User Experience:**
```
User clicks "Start Session"
  ↓
Frontend shows: "Connecting to voice agent..."
  ↓
...waits 30+ seconds...
  ↓
Still shows: "Connecting..." (stuck forever)
  ↓
User refreshes page → Works on second try
```

**What Backend Logs Show:**
- ✅ Room created successfully
- ✅ Pipecat agent connected to LiveKit room
- ✅ No errors logged

**What LiveKit Dashboard Shows:**
- ✅ Room exists
- ✅ Pipecat agent joined (1 participant)
- ❌ **User never joined** (only 1 participant, should be 2)

**What Frontend Console Shows:**
- ✅ Logs: "Connected"
- ✅ Logs: "Ready"
- ✅ **NO ERRORS**
- ❌ **But LiveKit proves user is NOT actually connected**

**Critical Discovery:**
- Frontend console **lies** - says "Connected" when it's not
- Frontend UI **correct** - shows "Connecting..." (reading actual state)
- This is a **frontend JavaScript state machine bug**

---

### Failure Window

**Timeline:**
- Normal connection: Takes max **10 seconds**
- Failures: Happen within **first 30 seconds**
- Retry success: **Always works on page refresh**

**This means:**
- Issue is in frontend connection initialization
- Not a timeout issue (happens too fast)
- Not a backend issue (backend works, agent connects)

---

### Possible Root Causes

#### **Theory #1: Frontend State Machine Bug (HIGHEST LIKELIHOOD)**

**Evidence:**
- Console shows "Connected" (JavaScript state)
- LiveKit shows NOT connected (actual state)
- UI shows "Connecting" (reading actual state)
- Works on retry (state reset fixes it)

**What's Happening:**
```javascript
// Frontend probably does:
setConnectionState('connected');  // Sets state too early
// But WebSocket still connecting...
// Connection fails silently
// Console reads JavaScript state → "Connected"
// UI reads WebSocket state → "Connecting"
```

**Action Required:**
- Review frontend LiveKit connection code
- Fix state machine to reflect actual connection status
- Add error handling for silent connection failures

---

#### **Theory #2: LiveKit Event Handler Timing**

**Evidence:**
- Connection works eventually (after retry)
- Failures are transient, not permanent
- No errors logged anywhere

**What's Happening:**
```javascript
// If we attach listeners AFTER connection starts:
room.connect();  // Starts connection
room.on('connected', () => {...});  // Too late! Missed event
// Frontend thinks still connecting
```

**Action Required:**
- Attach event listeners BEFORE calling connect()
- Ensure listeners are ready before initiating connection

---

#### **Theory #3: Token or WebSocket Failure**

**Evidence:**
- Works on retry (new token or fresh WebSocket)
- Only affects 10% of attempts (not systematic)
- No pattern found yet (need more data)

**Possible Causes:**
- WebSocket connection blocked by firewall
- Token generated but frontend receives it corrupted
- Network timeout before handshake completes
- Browser-specific WebSocket issues (Safari?)

**Action Required:**
- Log WebSocket state transitions
- Log token reception and validation
- Track browser/network correlation

---

## Part 3: Comprehensive Logging Solution

### What We Need to Log

**Currently Missing:**
| Event | Currently Logged? | Severity |
|-------|------------------|----------|
| Frontend token received | ❌ NO | Critical |
| Frontend LiveKit connecting | ❌ NO | Critical |
| Frontend LiveKit connected | ❌ NO | Critical |
| Frontend connection failed | ❌ NO | Critical |
| Frontend WebSocket state | ❌ NO | Critical |
| User joined LiveKit room | ❌ Backend only | High |
| Agent joined LiveKit room | ✅ Yes | Medium |

**Problem:** We have ZERO visibility into frontend connection lifecycle.

---

### Logging Architecture: Dual-Storage (Redis + Database)

#### **Tier 1: Redis (Real-Time - 24 Hours)**
- **Purpose:** Debug active/recent sessions
- **Speed:** 5ms write latency
- **Retention:** 24 hours (auto-expires)
- **Use case:** "User just reported issue, need to debug NOW"

#### **Tier 2: Database (Long-Term - Permanent)**
- **Purpose:** Historical analysis, pattern detection
- **Speed:** 100ms write latency
- **Retention:** 90 days (or permanent)
- **Use case:** "Show me all failures from last month"

#### **Why Both?**

**Redis Advantages:**
- ✅ Lightning fast (5ms vs 100ms)
- ✅ Non-blocking (frontend doesn't wait)
- ✅ Auto-cleanup (TTL expires old data)
- ✅ Query during active session

**Database Advantages:**
- ✅ Permanent storage (audit trail)
- ✅ Complex queries (SQL joins, aggregations)
- ✅ Pattern analysis (across 1000s of sessions)
- ✅ Compliance/reporting

**Strategy:**
1. Frontend reports event → Backend
2. Backend writes to Redis immediately (5ms) → Returns OK to frontend
3. Backend queues async database write (background, non-blocking)
4. Frontend gets instant response, no delays

---

### Implementation

#### **Frontend: Report Every Event**

```javascript
// Call this at EVERY step of connection lifecycle
async function reportConnectionEvent(event, data = {}) {
  try {
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
    }).catch(() => {});  // Never let monitoring break the app
  } catch (e) {
    // Swallow errors silently
  }
}

// Track every step:
reportConnectionEvent('session_start_requested');
reportConnectionEvent('token_received', { tokenLength: token.length });
reportConnectionEvent('livekit_connecting', { serverUrl });

// THIS WON'T FIRE WHEN IT FAILS - that's the bug!
reportConnectionEvent('livekit_connected');

reportConnectionEvent('first_audio_received');

// Track errors too:
room.on('connectionError', (error) => {
  reportConnectionEvent('connection_error', {
    error: error.message,
    code: error.code
  });
});
```

---

#### **Backend: Dual-Storage Endpoint**

```python
@app.post("/api/session/connection-event")
async def record_connection_event(request: Request):
    """
    Records frontend connection events with dual storage.

    TIER 1: Redis (5ms) - For real-time debugging
    TIER 2: Database (async) - For long-term analysis
    """
    data = await request.json()
    session_id = data.get('sessionId')
    event = data.get('event')

    event_data = {
        'event': event,
        'timestamp': data.get('timestamp'),
        'userAgent': data.get('userAgent'),
        'sessionId': session_id,
        **data
    }

    # TIER 1: Write to Redis (FAST - 5ms)
    redis_client.rpush(
        f"session:{session_id}:frontend_events",
        json.dumps(event_data)
    )
    redis_client.expire(f"session:{session_id}:frontend_events", 86400)  # 24h TTL
    redis_client.ltrim(f"session:{session_id}:frontend_events", -200, -1)  # Keep last 200

    # TIER 2: Write to Database (async background - non-blocking)
    asyncio.create_task(store_event_to_database(event_data))

    # Return immediately (don't wait for database)
    return {"status": "ok"}


async def store_event_to_database(event_data: dict):
    """Background task - stores to database for long-term analysis."""
    await Database.execute(
        """
        INSERT INTO connection_events (
            session_id, event_type, timestamp_ms,
            user_agent, event_data, created_at
        ) VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        event_data.get('sessionId'),
        event_data.get('event'),
        event_data.get('timestamp'),
        event_data.get('userAgent'),
        json.dumps(event_data)
    )
```

---

#### **Database Schema**

```sql
CREATE TABLE connection_events (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    user_agent TEXT,
    event_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),

    INDEX idx_session_id (session_id),
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at)
);
```

---

#### **Query for Debugging**

```python
@app.get("/api/session/{session_id}/connection-timeline")
async def get_connection_timeline(session_id: str, source: str = 'redis'):
    """
    Get complete connection timeline.

    Args:
        source: 'redis' (fast, 24h) or 'database' (slower, permanent)

    Returns:
        Timeline showing exactly where connection failed
    """
    if source == 'redis':
        events = redis_client.lrange(f"session:{session_id}:frontend_events", 0, -1)
        if not events:
            # Fallback to database if not in Redis (expired)
            source = 'database'

    if source == 'database':
        rows = await Database.fetch(
            "SELECT * FROM connection_events WHERE session_id = $1 ORDER BY timestamp_ms",
            session_id
        )
        # Parse and return...

    # Returns timeline with relative timestamps
    return {
        "session_id": session_id,
        "events": [
            {"event": "session_start_requested", "elapsed_ms": 0},
            {"event": "token_received", "elapsed_ms": 450},
            {"event": "livekit_connecting", "elapsed_ms": 500},
            # "livekit_connected" MISSING - this is the failure point!
            {"event": "timeout_waiting", "elapsed_ms": 30000}
        ]
    }
```

---

### Log Backend Errors Too

**Also track backend failures:**

```python
# When agent fails to spawn
await Database.execute(
    """
    INSERT INTO connection_events (
        session_id, event_type, timestamp_ms, event_data
    ) VALUES ($1, $2, $3, $4)
    """,
    session_id,
    'agent_spawn_failed',
    int(time.time() * 1000),
    json.dumps({'error': str(error), 'component': 'backend'})
)

# When LiveKit webhook fires
await Database.execute(
    """
    INSERT INTO connection_events (
        session_id, event_type, timestamp_ms, event_data
    ) VALUES ($1, $2, $3, $4)
    """,
    session_id,
    'user_joined_room',  # or 'user_left_room'
    int(time.time() * 1000),
    json.dumps({'participant_id': participant_id})
)
```

---

## Part 4: Data Retention & Debugging

### How Long Data Lasts

| Storage | Retention | Auto-Cleanup? |
|---------|-----------|---------------|
| Redis | 24 hours | ✅ Yes (TTL) |
| Database | 90 days | ⚠️ Manual (optional) |

### How to Debug Later

**Today's Issues (within 24h):**
```bash
GET /api/session/{id}/connection-timeline?source=redis
# Returns in 30ms - super fast
```

**Last Week's Issues:**
```bash
GET /api/session/{id}/connection-timeline?source=database
# Returns in 200ms - still fast enough
```

**Pattern Analysis (SQL):**
```sql
-- Find all sessions where user never connected
SELECT DISTINCT session_id
FROM connection_events e1
WHERE NOT EXISTS (
    SELECT 1 FROM connection_events e2
    WHERE e2.session_id = e1.session_id
    AND e2.event_type = 'livekit_connected'
)
AND e1.created_at > NOW() - INTERVAL '7 days';

-- Results: 97 sessions failed
-- Pattern: All using Chrome 120 on Mac
-- Root cause identified: Chrome WebSocket bug
```

---

## Part 5: Action Plan

### Immediate Actions (Today)

**1. Revert Both Commits**
```bash
git revert 57ba402  # Prometheus metrics
git revert 69a690b  # Agent spawn reliability
git push origin staging
```

**2. Create Logging Infrastructure**
- [ ] Add `connection_events` table to database
- [ ] Create `/api/session/connection-event` endpoint (dual storage)
- [ ] Create `/api/session/{id}/connection-timeline` query endpoint
- [ ] Deploy to staging

**3. Add Frontend Logging**
- [ ] Add `reportConnectionEvent()` function to frontend
- [ ] Call it at every connection step
- [ ] Track WebSocket state transitions
- [ ] Track LiveKit events (connected, disconnected, error)

### Week 1: Investigation

**1. Deploy Monitoring to Staging**
- [ ] Test 100+ sessions with full logging
- [ ] Capture both successful and failed attempts
- [ ] Review timelines for failed sessions

**2. Identify Failure Pattern**
- [ ] Query database for all failed sessions
- [ ] Look for common factors:
  - Browser version
  - Network type
  - Geographic location
  - Time of day (load-related?)

**3. Fix Frontend State Machine**
- [ ] Review LiveKit connection initialization
- [ ] Fix state tracking (console vs actual)
- [ ] Add proper error handling
- [ ] Add retry logic

### Week 2: Test & Deploy

**1. Test in Staging**
- [ ] 100+ sessions with fixes
- [ ] Verify no "stuck connecting" issues
- [ ] Verify no echo/repeat issues

**2. Gradual Production Rollout**
- [ ] 10% of traffic
- [ ] Monitor for 48 hours
- [ ] 50% of traffic
- [ ] Monitor for 48 hours
- [ ] 100% rollout

---

## Summary

### The Two Commits
- ❌ **Revert both** - Introduced regressions, 85% useless code
- Only 15% useful (status reporter concept)
- May have accidentally fixed original issue, but can't verify

### The Core Issue
- **NOT a backend problem** - Backend works fine
- **Frontend state machine bug** - Console lies about connection status
- **10% failure rate** - User stuck on "Connecting..." forever
- **Works on retry** - Page refresh fixes it (state reset)

### The Solution
- **NOT more coding** - We've been coding blind
- **ADD MONITORING FIRST** - Track every connection step
- **Dual storage** - Redis (fast, 24h) + Database (permanent)
- **Then investigate** - Find pattern in failures
- **Then fix** - Targeted fix based on data

### Key Insight
**You can't fix what you can't see. Stop coding, start monitoring.**

---

**Next Step:** Revert commits, add logging, investigate with data.
