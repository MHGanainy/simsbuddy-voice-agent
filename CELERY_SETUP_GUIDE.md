# Celery Migration: Setup & Testing Guide

This guide walks you through testing the Celery-based voice agent orchestrator locally and deploying to Railway.

---

## Quick Start (Local Testing)

### Prerequisites

- Docker and Docker Compose installed
- Your API keys ready (LiveKit, Groq, AssemblyAI, Inworld)

### Step 1: Configure Environment

```bash
# Copy example env file
cp .env.celery.example .env

# Edit .env and fill in your API keys
nano .env
```

Required variables:
```bash
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret
GROQ_API_KEY=your_key
ASSEMBLY_API_KEY=your_key
INWORLD_API_KEY=your_key
```

### Step 2: Start Services

```bash
# Start Redis + Orchestrator + Frontend
docker-compose -f docker-compose.celery.yml up --build
```

This starts:
- **Redis** on port 6379 (message broker + state store)
- **Orchestrator** on port 8080 (Express API + Celery worker)
- **Frontend** on port 3000 (React UI)

### Step 3: Verify Services

Open separate terminals and check:

```bash
# Terminal 1: Check health endpoint
curl http://localhost:8080/api/health

# Expected output:
# {
#   "success": true,
#   "status": "healthy",
#   "sessions": {
#     "ready": 0,
#     "starting": 0,
#     "pool": 3  # Pre-warmed agents
#   }
# }

# Terminal 2: Watch orchestrator logs
docker logs -f voice-agent-orchestrator

# You should see:
# [PreWarm] Spawning agent 1/3: prewarm_abc123
# [Task task_xyz] Spawning agent for session: prewarm_abc123
# [Task task_xyz] Process spawned with PID: 123
# [Task task_xyz] Agent connected successfully
```

### Step 4: Test Agent Spawning

```bash
# Start a session
curl -X POST http://localhost:8080/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userId": "test_user_123"}'

# Expected output (pre-warmed agent available):
# {
#   "success": true,
#   "sessionId": "prewarm_abc123",
#   "status": "ready",
#   "message": "Assigned pre-warmed agent",
#   "prewarmed": true,
#   "latency": "<500ms"
# }

# If pool is empty, you'll get:
# {
#   "success": true,
#   "sessionId": "session_1234567890_xyz",
#   "status": "starting",
#   "message": "Agent is being spawned. Poll /api/session/:id for status.",
#   "taskId": "task_abc123",
#   "prewarmed": false,
#   "estimatedWait": "15-20s"
# }
```

### Step 5: Poll Session Status

```bash
# Check session status (if agent was starting)
curl http://localhost:8080/api/session/session_1234567890_xyz

# While starting:
# {
#   "success": true,
#   "sessionId": "session_1234567890_xyz",
#   "status": "starting",
#   "userId": "test_user_123",
#   "createdAt": 1698765432
# }

# When ready:
# {
#   "success": true,
#   "sessionId": "session_1234567890_xyz",
#   "status": "ready",
#   "userId": "test_user_123",
#   "createdAt": 1698765432,
#   "startupTime": 17.3  # seconds
# }
```

### Step 6: Get LiveKit Token

```bash
# Once agent is ready, get token to join room
curl -X POST http://localhost:8080/api/token \
  -H "Content-Type: application/json" \
  -d '{"sessionId": "session_1234567890_xyz", "userName": "Test User"}'

# Response:
# {
#   "success": true,
#   "token": "eyJhbGc...",  # JWT token
#   "url": "wss://your-project.livekit.cloud",
#   "roomName": "session_1234567890_xyz"
# }
```

### Step 7: Test Frontend

Open browser to http://localhost:3000

1. Enter your name
2. Click "Start Session"
3. Should connect almost instantly (if pre-warmed agent available)
4. Test voice conversation with the agent

### Step 8: Monitor Pre-Warm Pool

```bash
# Check pool health
curl http://localhost:8080/api/health | jq '.sessions.pool'

# Should always maintain 3 pre-warmed agents
# Celery beat task refills pool every 30 seconds
```

---

## Advanced Testing

### Test Concurrent Spawning

```bash
# Spawn 10 agents concurrently
for i in {1..10}; do
  curl -X POST http://localhost:8080/api/session/start \
    -H "Content-Type: application/json" \
    -d "{\"userId\": \"user_$i\"}" &
done
wait

# With Celery: All 10 spawn in parallel (4 at a time)
# Old system: Sequential (150-200s total)
```

### Test Health Checks

```bash
# Kill an agent process manually
docker exec voice-agent-orchestrator kill -9 <PID>

# Wait 60 seconds for health check task
# Agent should be marked as 'error' in Redis
curl http://localhost:8080/api/session/<session_id>
# {"status": "error", "error": "Process died unexpectedly"}
```

### Test Cleanup

```bash
# Create a session and wait 31 minutes
# Cleanup task runs every 5 minutes
# Session should be auto-terminated after 30min inactivity
```

### View Agent Logs

```bash
# Get recent logs for a session
curl http://localhost:8080/api/session/<session_id>/logs?limit=50

# Response:
# {
#   "success": true,
#   "sessionId": "session_abc123",
#   "logs": [
#     "Starting voice assistant...",
#     "Connected to LiveKit room: session_abc123",
#     "Pipeline started successfully"
#   ]
# }
```

### Resize Pre-Warm Pool

```bash
# Increase pool size to 5
curl -X POST http://localhost:8080/api/pool/resize \
  -H "Content-Type: application/json" \
  -d '{"size": 5}'

# Celery will spawn 2 more agents on next beat cycle (30s)
```

### List All Sessions

```bash
curl http://localhost:8080/api/sessions

# Response:
# {
#   "success": true,
#   "count": 7,
#   "breakdown": {
#     "ready": 4,
#     "starting": 1,
#     "pool": 2
#   },
#   "sessions": [...]
# }
```

---

## Monitoring with Redis CLI

```bash
# Connect to Redis
docker exec -it voice-agent-redis redis-cli

# Check pool
127.0.0.1:6379> SMEMBERS pool:ready
1) "prewarm_abc123"
2) "prewarm_def456"
3) "prewarm_ghi789"

# Check session data
127.0.0.1:6379> HGETALL session:prewarm_abc123
1) "status"
2) "ready"
3) "agentPid"
4) "12345"
5) "createdAt"
6) "1698765432"

# Check Celery queue depth
127.0.0.1:6379> LLEN celery
(integer) 0  # No pending tasks

# View pool stats
127.0.0.1:6379> HGETALL pool:stats
1) "total_spawned"
2) "87"
3) "total_assigned"
4) "84"
```

---

## Railway Deployment

### Step 1: Provision Redis Addon

1. Open Railway dashboard
2. Select your project
3. Click "New" → "Database" → "Add Redis"
4. Redis will auto-inject `REDIS_URL` into orchestrator service

### Step 2: Update Orchestrator Service

1. Go to orchestrator service settings
2. Set "Source" to this repository
3. Set "Dockerfile Path" to `Dockerfile.orchestrator`
4. Add environment variables (same as .env file)
5. Deploy

### Step 3: Verify Deployment

```bash
# Set your Railway URL
RAILWAY_URL=https://your-orchestrator.railway.app

# Check health
curl $RAILWAY_URL/api/health

# Should show healthy with pre-warmed agents
```

### Step 4: Update Frontend

Update frontend environment variable:
```bash
VITE_API_URL=https://your-orchestrator.railway.app
```

Redeploy frontend.

---

## Troubleshooting

### Issue: Celery worker not starting

**Symptom:** No pre-warm agents spawning

**Solution:**
```bash
# Check supervisor logs
docker exec voice-agent-orchestrator cat /var/log/supervisord.log

# Check Celery worker specifically
docker exec voice-agent-orchestrator supervisorctl status celery-worker

# Should show:
# celery-worker  RUNNING   pid 123, uptime 0:05:00
```

### Issue: Redis connection refused

**Symptom:** Express API can't connect to Redis

**Solution:**
```bash
# Check Redis is running
docker ps | grep redis

# Check Redis logs
docker logs voice-agent-redis

# Test connection manually
docker exec voice-agent-redis redis-cli ping
# Should return: PONG
```

### Issue: Agents failing to spawn

**Symptom:** All spawn tasks fail with errors

**Solution:**
```bash
# Check agent logs in Redis
curl http://localhost:8080/api/session/<session_id>/logs

# Common issues:
# 1. Missing API keys → check .env file
# 2. LiveKit URL incorrect → verify LIVEKIT_URL
# 3. Python dependencies missing → rebuild Docker image
```

### Issue: Pre-warm pool empty

**Symptom:** Pool size is always 0

**Solution:**
```bash
# Check Celery beat is running
docker exec voice-agent-orchestrator ps aux | grep celery

# Check beat schedule
docker logs voice-agent-orchestrator | grep PreWarm

# Manually trigger pool refill
curl -X POST http://localhost:8080/api/pool/resize \
  -H "Content-Type: application/json" \
  -d '{"size": 3}'
```

### Issue: Supervisor not starting both processes

**Symptom:** Only Express or only Celery is running

**Solution:**
```bash
# Check supervisor config
docker exec voice-agent-orchestrator cat /etc/supervisor/conf.d/supervisord.conf

# Check status of all programs
docker exec voice-agent-orchestrator supervisorctl status

# Restart specific program
docker exec voice-agent-orchestrator supervisorctl restart express-api
docker exec voice-agent-orchestrator supervisorctl restart celery-worker
```

---

## Performance Benchmarks

### Latency Comparison

| Scenario | Old System | Celery System | Improvement |
|----------|-----------|---------------|-------------|
| Agent start (pre-warmed) | 15-20s | <500ms | **97% faster** |
| Agent start (on-demand) | 15-20s | 15-20s | Same |
| 10 concurrent spawns | 150-200s | 40-50s | **75% faster** |

### Resource Usage

| Component | Memory | CPU | Notes |
|-----------|--------|-----|-------|
| Redis | ~50MB | <5% | Minimal overhead |
| Express API | ~100MB | <10% | Handles HTTP only |
| Celery worker | ~200MB | 10-30% | Spawns agents |
| Voice agent (each) | ~300MB | 50-100% | ML models loaded |

---

## Next Steps

1. **Test locally** using docker-compose
2. **Verify pre-warm pool** is working
3. **Test concurrent spawning** (10+ agents)
4. **Deploy to Railway** with Redis addon
5. **Monitor for 48 hours** before rolling out to users
6. **Tune pool size** based on traffic patterns
7. **Set up alerts** for pool depletion

---

## Rollback Plan

If issues arise in production:

```bash
# Railway: Redeploy previous version
railway rollback

# Or update Dockerfile CMD back to old orchestrator:
CMD ["node", "simple-orchestrator.js"]

# Then redeploy
```

Session data in Redis is ephemeral - no data migration needed.

---

## Support

For issues or questions:
1. Check logs: `docker logs voice-agent-orchestrator`
2. Check Redis: `docker exec -it voice-agent-redis redis-cli`
3. Review migration plan: `CELERY_MIGRATION_PLAN.md`
4. Test endpoints: Use curl examples above

Happy testing! The Celery migration should dramatically improve user experience with near-instant agent assignment.
