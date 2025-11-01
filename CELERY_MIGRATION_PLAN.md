# Celery Migration Plan: Voice Agent Orchestration

## Executive Summary

**Current Pain Points:**
- 15-20 second blocking agent startup (line 421 in `simple-orchestrator.js`)
- Lost sessions on restart (in-memory state)
- Sequential request handling limits concurrency
- No failure recovery mechanisms

**Solution Overview:**
Migrate to async Celery task queue with **streamlined 3-service architecture** optimized for Railway deployment.

**Target Improvements:**
- Agent startup: 15-20s → <2s (via pre-warming pool)
- Concurrent spawning: Sequential → Parallel (10+ simultaneous)
- Session persistence: In-memory → Redis (survives restarts)
- Failure handling: None → Automated retries + circuit breakers

---

## Architecture Overview

### Current Architecture (2 Services)
```
┌─────────────────────────────────────────────────────────┐
│ Railway Service 1: Frontend (React)                     │
│ Port: 3000                                              │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Railway Service 2: Orchestrator + Python Agents        │
│ - Express API (8080)                                    │
│ - Spawns Python subprocesses                           │
│ - In-memory state (Map objects)                        │
│ - BLOCKING agent initialization                        │
└─────────────────────────────────────────────────────────┘
```

### Proposed Architecture (3 Services)

```
┌──────────────────────────────────────────────────────────┐
│ Railway Service 1: Frontend (React)                      │
│ Port: 3000                                               │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP
                       ▼
┌──────────────────────────────────────────────────────────┐
│ Railway Service 2: Orchestrator (Supervisor Container)   │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Process 1: Express API (Port 8080)                  │ │
│ │ - Non-blocking endpoints                            │ │
│ │ - Returns task IDs immediately                      │ │
│ │ - Queries Redis for state                           │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Process 2: Celery Worker + Beat (single process)   │ │
│ │ $ celery -A tasks worker --beat --loglevel=info     │ │
│ │                                                      │ │
│ │ Tasks:                                              │ │
│ │ - spawn_voice_agent()    (spawn new agents)        │ │
│ │ - prewarm_agent_pool()   (maintain hot pool)       │ │
│ │ - health_check_agents()  (monitor processes)       │ │
│ │ - cleanup_stale_agents() (garbage collection)      │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                           │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Process 3+: Python Voice Agent Processes            │ │
│ │ - Spawned by Celery workers                         │ │
│ │ - Long-running (not Celery tasks)                   │ │
│ │ - Connect to LiveKit                                │ │
│ │ - Register status in Redis                          │ │
│ └─────────────────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│ Railway Addon: Managed Redis                             │
│                                                           │
│ Purpose:                                                  │
│ - Celery broker (task queue)                            │
│ - Celery result backend (task results)                  │
│ - Session state (active agents, user mappings)          │
│ - Pre-warm pool tracking                                │
│ - Rate limiting state                                   │
└──────────────────────────────────────────────────────────┘
```

**Key Points:**
- Single container runs Express + Celery via **Supervisor**
- Celery worker uses `--beat` flag (no separate beat container)
- No Flower monitoring (use Railway logs + Redis CLI)
- Managed Redis for everything (broker, backend, state)

---

## Detailed Design

### 1. Supervisor Configuration

**File:** `supervisord.conf`

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisord.log
pidfile=/var/run/supervisord.pid

[program:express-api]
command=node /app/orchestrator/celery-orchestrator.js
directory=/app/orchestrator
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=NODE_ENV=production

[program:celery-worker]
command=celery -A tasks worker --beat --loglevel=info --concurrency=4
directory=/app/orchestrator
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
stopwaitsecs=60
killasgroup=true
environment=PYTHONUNBUFFERED=1

[group:orchestrator]
programs=express-api,celery-worker
priority=999
```

**Key Features:**
- Both processes start together
- Logs to stdout/stderr (Railway native logging)
- Graceful shutdown (60s timeout for cleanup)
- `--beat` flag runs scheduler in worker process
- `--concurrency=4` allows parallel agent spawning

---

### 2. Redis Schema Design

**Database Purpose:** Single Redis instance for all needs

#### Key Namespaces:

```
# Celery (managed by Celery)
celery:task:*              # Task metadata
celery:result:*            # Task results
celery:beat:*              # Scheduled tasks

# Session State
session:{sessionId}        # Hash: {status, userId, agentPid, createdAt, lastActive}
session:user:{userId}      # String: sessionId (user → session lookup)
session:ready              # Set: sessionIds of ready agents
session:starting           # Set: sessionIds of agents being spawned

# Pre-Warm Pool
pool:ready                 # Set: sessionIds of unassigned, ready agents
pool:target                # String: target pool size (default: 3)
pool:stats                 # Hash: {total_spawned, total_assigned, avg_startup_time}

# Process Tracking
agent:{sessionId}:pid      # String: process ID
agent:{sessionId}:logs     # List: last 100 log lines
agent:{sessionId}:health   # Hash: {last_check, status, error_count}

# Rate Limiting
ratelimit:{ip}             # String: request count (TTL: 60s)
```

#### Example Data:

```bash
# Session metadata
HSET session:abc123 status "ready" userId "user_456" agentPid "12345" createdAt "1698765432"

# Pre-warm pool
SADD pool:ready "abc123" "def456" "ghi789"

# Process tracking
SET agent:abc123:pid "12345"
LPUSH agent:abc123:logs "Connected to LiveKit room: abc123"
```

---

### 3. Celery Task Definitions

**File:** `orchestrator/tasks.py`

```python
from celery import Celery, Task
from celery.schedules import crontab
import subprocess
import redis
import time
import os
import uuid

# Initialize Celery
app = Celery('voice_agent_tasks')
app.config_from_object('celeryconfig')

# Redis client
redis_client = redis.from_url(os.getenv('REDIS_URL'))

# Configuration
PYTHON_SCRIPT_PATH = '/app/voice_assistant.py'
BOT_STARTUP_TIMEOUT = 20
PREWARM_POOL_SIZE = 3


class AgentSpawnTask(Task):
    """Base task with retry logic and error handling"""
    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3, 'countdown': 5}
    retry_backoff = True
    retry_backoff_max = 60
    retry_jitter = True


@app.task(base=AgentSpawnTask, bind=True, name='spawn_voice_agent')
def spawn_voice_agent(self, session_id, user_id=None, prewarm=False):
    """
    Spawn a voice agent process asynchronously.

    Args:
        session_id: Unique session identifier
        user_id: User ID (None for pre-warmed agents)
        prewarm: If True, agent goes to pool instead of ready state

    Returns:
        dict: {session_id, pid, status, startup_time}
    """
    start_time = time.time()

    try:
        # Update session status
        redis_client.hset(f'session:{session_id}', mapping={
            'status': 'starting',
            'userId': user_id or '',
            'createdAt': int(time.time()),
            'taskId': self.request.id
        })
        redis_client.sadd('session:starting', session_id)

        # Spawn Python process
        process = subprocess.Popen(
            ['python3', PYTHON_SCRIPT_PATH, '--room', session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        pid = process.pid
        redis_client.set(f'agent:{session_id}:pid', pid)

        # Monitor stdout/stderr for connection success
        connected = False
        error_output = []

        while time.time() - start_time < BOT_STARTUP_TIMEOUT:
            # Check if process died
            if process.poll() is not None:
                stderr = process.stderr.read()
                raise Exception(f"Agent process died: {stderr}")

            # Read stdout line
            line = process.stdout.readline()
            if line:
                redis_client.rpush(f'agent:{session_id}:logs', line.strip())
                redis_client.ltrim(f'agent:{session_id}:logs', -100, -1)  # Keep last 100

                # Check for connection success
                if 'Connected to' in line or 'Pipeline started' in line:
                    connected = True
                    break

            # Read stderr line
            err_line = process.stderr.readline()
            if err_line:
                error_output.append(err_line)
                redis_client.rpush(f'agent:{session_id}:logs', f"ERROR: {err_line.strip()}")

                # Also check stderr for success (some logs go there)
                if 'Connected to' in err_line or 'Pipeline started' in err_line:
                    connected = True
                    break

            time.sleep(0.1)

        if not connected:
            process.terminate()
            raise Exception(f"Agent failed to connect within {BOT_STARTUP_TIMEOUT}s")

        # Update session to ready
        startup_time = time.time() - start_time
        redis_client.hset(f'session:{session_id}', mapping={
            'status': 'ready',
            'agentPid': pid,
            'startupTime': startup_time
        })

        # Move to appropriate state
        redis_client.srem('session:starting', session_id)
        if prewarm:
            redis_client.sadd('pool:ready', session_id)
        else:
            redis_client.sadd('session:ready', session_id)
            if user_id:
                redis_client.set(f'session:user:{user_id}', session_id)

        # Update pool stats
        redis_client.hincrby('pool:stats', 'total_spawned', 1)

        return {
            'session_id': session_id,
            'pid': pid,
            'status': 'ready',
            'startup_time': startup_time
        }

    except Exception as e:
        # Mark session as failed
        redis_client.hset(f'session:{session_id}', mapping={
            'status': 'error',
            'error': str(e)
        })
        redis_client.srem('session:starting', session_id)

        # Retry if not max retries
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)

        raise


@app.task(name='prewarm_agent_pool')
def prewarm_agent_pool():
    """
    Maintain a pool of pre-warmed agents ready for instant assignment.
    Runs every 30 seconds via Beat scheduler.
    """
    target_size = int(redis_client.get('pool:target') or PREWARM_POOL_SIZE)
    current_size = redis_client.scard('pool:ready')

    deficit = target_size - current_size

    if deficit > 0:
        print(f"Pre-warming {deficit} agents (current: {current_size}, target: {target_size})")

        for _ in range(deficit):
            session_id = f"prewarm_{uuid.uuid4().hex[:8]}"
            spawn_voice_agent.delay(session_id, user_id=None, prewarm=True)


@app.task(name='health_check_agents')
def health_check_agents():
    """
    Check health of all running agents.
    Runs every 60 seconds via Beat scheduler.
    """
    all_sessions = redis_client.keys('session:*')

    for key in all_sessions:
        if key.startswith(b'session:user:'):
            continue

        session_id = key.decode().split(':')[1]
        session_data = redis_client.hgetall(f'session:{session_id}')

        if not session_data or session_data.get(b'status') not in [b'ready', b'active']:
            continue

        pid = session_data.get(b'agentPid')
        if not pid:
            continue

        # Check if process is alive
        try:
            os.kill(int(pid), 0)  # Signal 0 = check existence
            redis_client.hset(f'agent:{session_id}:health', mapping={
                'last_check': int(time.time()),
                'status': 'healthy'
            })
        except ProcessLookupError:
            # Process is dead
            print(f"Agent {session_id} process {pid} is dead, marking as failed")
            redis_client.hset(f'session:{session_id}', 'status', 'error')
            redis_client.hset(f'session:{session_id}', 'error', 'Process died unexpectedly')
            redis_client.srem('pool:ready', session_id)
            redis_client.srem('session:ready', session_id)


@app.task(name='cleanup_stale_agents')
def cleanup_stale_agents():
    """
    Clean up stale sessions and terminated agents.
    Runs every 5 minutes via Beat scheduler.
    """
    now = int(time.time())
    timeout = 1800  # 30 minutes

    all_sessions = redis_client.keys('session:*')

    for key in all_sessions:
        if key.startswith(b'session:user:'):
            continue

        session_id = key.decode().split(':')[1]
        session_data = redis_client.hgetall(f'session:{session_id}')

        if not session_data:
            continue

        last_active = int(session_data.get(b'lastActive', session_data.get(b'createdAt', 0)))

        if now - last_active > timeout:
            print(f"Cleaning up stale session: {session_id}")

            # Stop agent process
            pid = session_data.get(b'agentPid')
            if pid:
                try:
                    os.kill(int(pid), 15)  # SIGTERM
                    time.sleep(2)
                    os.kill(int(pid), 9)   # SIGKILL if still alive
                except ProcessLookupError:
                    pass

            # Clean up Redis keys
            redis_client.delete(f'session:{session_id}')
            redis_client.delete(f'agent:{session_id}:pid')
            redis_client.delete(f'agent:{session_id}:logs')
            redis_client.delete(f'agent:{session_id}:health')
            redis_client.srem('pool:ready', session_id)
            redis_client.srem('session:ready', session_id)
            redis_client.srem('session:starting', session_id)


# Beat Schedule Configuration
app.conf.beat_schedule = {
    'prewarm-pool-every-30s': {
        'task': 'prewarm_agent_pool',
        'schedule': 30.0,  # Every 30 seconds
    },
    'health-check-every-60s': {
        'task': 'health_check_agents',
        'schedule': 60.0,  # Every 60 seconds
    },
    'cleanup-stale-every-5m': {
        'task': 'cleanup_stale_agents',
        'schedule': 300.0,  # Every 5 minutes
    },
}

app.conf.timezone = 'UTC'
```

---

### 4. Celery Configuration

**File:** `orchestrator/celeryconfig.py`

```python
import os

# Redis URL from Railway
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Broker settings
broker_url = redis_url
broker_connection_retry_on_startup = True
broker_connection_retry = True
broker_connection_max_retries = 10

# Result backend
result_backend = redis_url
result_expires = 3600  # 1 hour

# Task settings
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Worker settings
worker_prefetch_multiplier = 2
worker_max_tasks_per_child = 100  # Restart worker after 100 tasks (prevent memory leaks)
worker_disable_rate_limits = True

# Task execution
task_acks_late = True  # Acknowledge task after completion
task_reject_on_worker_lost = True
task_track_started = True

# Performance tuning
result_compression = 'gzip'
result_cache_max = 1000

# Logging
worker_log_format = '[%(asctime)s: %(levelname)s/%(processName)s] %(message)s'
worker_task_log_format = '[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s'
```

---

### 5. Updated Express API (Non-Blocking)

**File:** `orchestrator/celery-orchestrator.js`

```javascript
const express = require('express');
const cors = require('cors');
const Redis = require('ioredis');
const { AccessToken } = require('livekit-server-sdk');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 8080;

// Redis client
const redis = new Redis(process.env.REDIS_URL);

// Middleware
app.use(cors());
app.use(express.json());
app.use((req, res, next) => {
  req.setTimeout(30000);
  next();
});

// Configuration
const LIVEKIT_URL = process.env.LIVEKIT_URL;
const LIVEKIT_API_KEY = process.env.LIVEKIT_API_KEY;
const LIVEKIT_API_SECRET = process.env.LIVEKIT_API_SECRET;
const MAX_BOTS = parseInt(process.env.MAX_BOTS) || 50;

// Rate limiting helper
async function checkRateLimit(ip) {
  const key = `ratelimit:${ip}`;
  const count = await redis.incr(key);

  if (count === 1) {
    await redis.expire(key, 60); // 60 second window
  }

  return count <= 10; // Max 10 requests per minute
}

// Helper: Get session from Redis
async function getSession(sessionId) {
  const data = await redis.hgetall(`session:${sessionId}`);
  if (!data || Object.keys(data).length === 0) return null;
  return data;
}

// Helper: Assign pre-warmed agent to user
async function assignPrewarmedAgent(userId) {
  const prewarmedId = await redis.spop('pool:ready');

  if (!prewarmedId) return null;

  // Update session with user info
  await redis.hset(`session:${prewarmedId}`, 'userId', userId);
  await redis.hset(`session:${prewarmedId}`, 'status', 'ready');
  await redis.set(`session:user:${userId}`, prewarmedId);
  await redis.sadd('session:ready', prewarmedId);
  await redis.hincrby('pool:stats', 'total_assigned', 1);

  return prewarmedId;
}

/**
 * POST /api/session/start
 * Start a voice agent session (NON-BLOCKING)
 */
app.post('/api/session/start', async (req, res) => {
  try {
    const { userId } = req.body;
    const ip = req.headers['x-forwarded-for'] || req.connection.remoteAddress;

    // Rate limiting
    const allowed = await checkRateLimit(ip);
    if (!allowed) {
      return res.status(429).json({
        success: false,
        error: 'Rate limit exceeded. Max 10 requests per minute.'
      });
    }

    // Check capacity
    const activeSessions = await redis.scard('session:ready') +
                          await redis.scard('session:starting');

    if (activeSessions >= MAX_BOTS) {
      return res.status(503).json({
        success: false,
        error: 'Maximum capacity reached. Please try again later.'
      });
    }

    // Check if user already has session
    const existingSessionId = await redis.get(`session:user:${userId}`);
    if (existingSessionId) {
      const session = await getSession(existingSessionId);
      if (session && (session.status === 'ready' || session.status === 'starting')) {
        return res.json({
          success: true,
          sessionId: existingSessionId,
          status: session.status,
          message: 'Using existing session'
        });
      }
    }

    // Try to assign pre-warmed agent first (INSTANT)
    const prewarmedId = await assignPrewarmedAgent(userId);

    if (prewarmedId) {
      return res.json({
        success: true,
        sessionId: prewarmedId,
        status: 'ready',
        message: 'Assigned pre-warmed agent',
        prewarmed: true
      });
    }

    // No pre-warmed agent available, spawn new one (ASYNC)
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    // Queue Celery task (non-blocking)
    const axios = require('axios');
    const celeryTask = {
      task: 'spawn_voice_agent',
      args: [sessionId, userId, false],
      kwargs: {}
    };

    // Send task to Celery (Redis backend)
    // Note: In production, use python-shell or dedicated Celery client
    // For now, we'll use Redis directly
    const taskId = `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    await redis.lpush('celery', JSON.stringify({
      id: taskId,
      task: 'spawn_voice_agent',
      args: [sessionId, userId, false],
      kwargs: {},
      retries: 0
    }));

    // Return immediately with "starting" status
    res.json({
      success: true,
      sessionId,
      status: 'starting',
      message: 'Agent is being spawned. Poll /api/session/:id for status.',
      taskId,
      prewarmed: false
    });

  } catch (error) {
    console.error('Error starting session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/session/:id
 * Get session status (for polling)
 */
app.get('/api/session/:id', async (req, res) => {
  try {
    const { id } = req.params;

    const session = await getSession(id);

    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }

    // Update last active timestamp
    await redis.hset(`session:${id}`, 'lastActive', Date.now());

    res.json({
      success: true,
      sessionId: id,
      status: session.status,
      userId: session.userId || null,
      createdAt: parseInt(session.createdAt),
      startupTime: parseFloat(session.startupTime) || null,
      error: session.error || null
    });

  } catch (error) {
    console.error('Error fetching session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/session/stop
 * Stop a session
 */
app.post('/api/session/stop', async (req, res) => {
  try {
    const { sessionId } = req.body;

    const session = await getSession(sessionId);

    if (!session) {
      return res.status(404).json({
        success: false,
        error: 'Session not found'
      });
    }

    const pid = session.agentPid;

    if (pid) {
      // Graceful shutdown
      try {
        process.kill(parseInt(pid), 'SIGTERM');

        // Give it 5 seconds, then force kill
        setTimeout(() => {
          try {
            process.kill(parseInt(pid), 'SIGKILL');
          } catch (e) {
            // Process already dead
          }
        }, 5000);
      } catch (error) {
        // Process already dead
      }
    }

    // Clean up Redis
    const userId = session.userId;
    await redis.del(`session:${sessionId}`);
    await redis.del(`agent:${sessionId}:pid`);
    await redis.del(`agent:${sessionId}:logs`);
    await redis.del(`agent:${sessionId}:health`);
    await redis.srem('session:ready', sessionId);
    await redis.srem('session:starting', sessionId);
    await redis.srem('pool:ready', sessionId);
    if (userId) {
      await redis.del(`session:user:${userId}`);
    }

    res.json({
      success: true,
      message: 'Session stopped'
    });

  } catch (error) {
    console.error('Error stopping session:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * POST /api/token
 * Generate LiveKit access token
 */
app.post('/api/token', async (req, res) => {
  try {
    const { sessionId, userName } = req.body;

    const session = await getSession(sessionId);

    if (!session || session.status !== 'ready') {
      return res.status(400).json({
        success: false,
        error: 'Session not ready or not found'
      });
    }

    // Generate token
    const token = new AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET, {
      identity: userName || `user_${Date.now()}`,
      ttl: '2h'
    });

    token.addGrant({
      room: sessionId,
      roomJoin: true,
      canPublish: true,
      canSubscribe: true
    });

    res.json({
      success: true,
      token: await token.toJwt(),
      url: LIVEKIT_URL,
      roomName: sessionId
    });

  } catch (error) {
    console.error('Error generating token:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

/**
 * GET /api/health
 * Health check endpoint
 */
app.get('/api/health', async (req, res) => {
  try {
    // Check Redis connection
    await redis.ping();

    const readyCount = await redis.scard('session:ready');
    const startingCount = await redis.scard('session:starting');
    const poolCount = await redis.scard('pool:ready');
    const stats = await redis.hgetall('pool:stats');

    res.json({
      success: true,
      status: 'healthy',
      sessions: {
        ready: readyCount,
        starting: startingCount,
        pool: poolCount
      },
      stats: {
        totalSpawned: parseInt(stats.total_spawned) || 0,
        totalAssigned: parseInt(stats.total_assigned) || 0
      }
    });
  } catch (error) {
    res.status(503).json({
      success: false,
      status: 'unhealthy',
      error: error.message
    });
  }
});

/**
 * GET /api/sessions
 * List all active sessions (admin endpoint)
 */
app.get('/api/sessions', async (req, res) => {
  try {
    const readySessions = await redis.smembers('session:ready');
    const startingSessions = await redis.smembers('session:starting');
    const poolSessions = await redis.smembers('pool:ready');

    const allSessions = [...readySessions, ...startingSessions, ...poolSessions];

    const sessions = await Promise.all(
      allSessions.map(async (id) => {
        const data = await getSession(id);
        return { sessionId: id, ...data };
      })
    );

    res.json({
      success: true,
      count: sessions.length,
      sessions
    });
  } catch (error) {
    console.error('Error listing sessions:', error);
    res.status(500).json({
      success: false,
      error: error.message
    });
  }
});

// Graceful shutdown
process.on('SIGTERM', async () => {
  console.log('SIGTERM received, shutting down gracefully...');

  // Stop accepting new requests
  server.close(() => {
    console.log('HTTP server closed');
  });

  // Close Redis connection
  await redis.quit();

  process.exit(0);
});

const server = app.listen(PORT, () => {
  console.log(`Orchestrator API listening on port ${PORT}`);
  console.log(`Redis connected: ${process.env.REDIS_URL ? 'Yes' : 'No'}`);
});

module.exports = app;
```

---

### 6. Updated Dockerfile

**File:** `Dockerfile.orchestrator`

```dockerfile
FROM python:3.10-slim

# Install Node.js
RUN apt-get update && apt-get install -y \
    curl \
    supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python dependencies
COPY voice-assistant-project/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy Node.js dependencies
COPY voice-assistant-project/orchestrator/package*.json /app/orchestrator/
WORKDIR /app/orchestrator
RUN npm ci --only=production

# Copy application code
COPY voice-assistant-project/voice_assistant.py /app/voice_assistant.py
COPY voice-assistant-project/orchestrator/ /app/orchestrator/

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create log directory
RUN mkdir -p /var/log

# Expose port
EXPOSE 8080

# Start supervisor (runs Express + Celery)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

---

### 7. Railway Configuration

**File:** `railway.json`

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile.orchestrator"
  },
  "deploy": {
    "startCommand": "/usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf",
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

**Required Railway Services:**
1. **Orchestrator Service** (uses Dockerfile.orchestrator)
   - Runs Supervisor → Express + Celery
   - ENV: All existing vars + `REDIS_URL`

2. **Frontend Service** (existing React app)
   - No changes needed

3. **Redis Addon** (managed by Railway)
   - Provision: Railway Dashboard → Add Redis
   - Auto-injects `REDIS_URL` into orchestrator service

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Tasks:**
1. Add Redis addon in Railway dashboard
2. Install dependencies:
   ```bash
   cd orchestrator
   npm install ioredis celery-node
   pip install celery redis
   ```
3. Create `tasks.py` with basic `spawn_voice_agent` task
4. Create `celeryconfig.py`
5. Create `supervisord.conf`
6. Test locally with Docker Compose

**Testing:**
```bash
# Terminal 1: Start Redis
docker run -p 6379:6379 redis:7-alpine

# Terminal 2: Start Celery worker
celery -A tasks worker --beat --loglevel=info

# Terminal 3: Start Express
node celery-orchestrator.js

# Terminal 4: Test spawning
curl -X POST http://localhost:8080/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userId": "test_user"}'
```

### Phase 2: Pre-Warming Pool (Week 2)

**Tasks:**
1. Implement `prewarm_agent_pool()` task
2. Implement `assignPrewarmedAgent()` logic in Express
3. Add Beat scheduler configuration
4. Add pool monitoring endpoints
5. Tune pool size based on load patterns

**Expected Outcome:**
- Pre-warmed agents spawn in background
- User requests get instant response (<500ms)
- Pool automatically refills

### Phase 3: Resilience (Week 3)

**Tasks:**
1. Implement `health_check_agents()` task
2. Implement `cleanup_stale_agents()` task
3. Add retry logic with exponential backoff
4. Add circuit breaker for external service calls
5. Add graceful degradation (fallback to sync spawn if pool empty)

**Error Scenarios Covered:**
- Agent process crashes → detected by health check
- LiveKit connection fails → retry up to 3 times
- High load → graceful degradation
- Redis connection loss → reconnect logic

### Phase 4: Observability (Week 4)

**Tasks:**
1. Add structured logging (JSON format for Railway)
2. Add metrics tracking (startup time, pool stats)
3. Add alert thresholds (pool depleted, high error rate)
4. Create admin dashboard endpoint (`/api/admin/stats`)
5. Document ops playbook

**Monitoring via Railway Logs:**
```bash
# Search for errors
railway logs --filter "ERROR"

# Monitor Celery tasks
railway logs --filter "spawn_voice_agent"

# Check pool health
railway logs --filter "prewarm_agent_pool"
```

---

## Migration Strategy

### Option A: Blue-Green Deployment (Recommended)

1. Deploy new Celery-based orchestrator as separate Railway service
2. Route 10% of traffic to new service
3. Monitor for 24-48 hours
4. Gradually increase traffic to 50%, then 100%
5. Decommission old service

**Pros:** Zero downtime, easy rollback
**Cons:** Runs both systems temporarily (cost)

### Option B: In-Place Migration

1. Add Redis addon to existing orchestrator service
2. Deploy Celery code alongside existing code
3. Add feature flag: `USE_CELERY=true`
4. Test with internal users
5. Flip flag for all users
6. Remove old code after 1 week

**Pros:** Lower cost
**Cons:** Higher risk, harder rollback

---

## Performance Comparison

### Current Architecture (Synchronous)

| Metric | Value |
|--------|-------|
| Agent startup latency | 15-20s (blocking) |
| Concurrent spawns | 1 (sequential) |
| Time to spawn 10 agents | 150-200s |
| Session persistence | None (in-memory) |
| Recovery from restart | Manual (all sessions lost) |

### Celery Architecture (Async + Pool)

| Metric | Value | Improvement |
|--------|-------|-------------|
| Agent startup latency | <500ms (pre-warmed) | **97% faster** |
| Fallback latency | 15-20s (on-demand spawn) | Same as current |
| Concurrent spawns | 4+ (parallel workers) | **4x parallelism** |
| Time to spawn 10 agents | 40-50s (parallel) | **75% faster** |
| Session persistence | Redis (survives restarts) | **100% reliability** |
| Recovery from restart | Automatic (reconnect to Redis) | **Zero manual intervention** |
| Pre-warm pool refill | Automatic (every 30s) | **Proactive scaling** |

---

## Redis vs RabbitMQ Trade-off Analysis

### Why Redis is Better for This Use Case

| Factor | Redis | RabbitMQ | Winner |
|--------|-------|----------|--------|
| **Setup Complexity** | Single service, dual-purpose (broker + state) | Separate broker + Redis for state | Redis |
| **Latency** | <5ms (in-memory) | 10-20ms (message routing) | Redis |
| **Throughput** | 100k+ ops/sec | 10-50k msgs/sec | Redis |
| **Cost on Railway** | $5/month (managed addon) | Not available as managed addon | Redis |
| **Failure Recovery** | Built-in persistence (AOF/RDB) | Requires disk persistence config | Redis |
| **Monitoring** | Railway dashboard + Redis CLI | Requires management plugin | Redis |
| **Message Guarantees** | At-least-once (via ACKs) | At-least-once (default) | Tie |
| **Task Routing** | Supported (via keys) | More sophisticated routing | RabbitMQ |
| **Load Balancing** | Round-robin (Celery handles) | Native exchange/queue patterns | RabbitMQ |

**Decision:** Redis wins for 50-100 user scale due to:
1. Simplicity (one service instead of two)
2. Lower latency (critical for real-time voice)
3. Native Railway support (managed addon)
4. Dual-purpose (broker + session state)

**When to Consider RabbitMQ:**
- If scaling beyond 10,000 tasks/sec
- If need complex routing (topic exchanges, priority queues)
- If need strict message ordering guarantees
- If already running RabbitMQ infrastructure

---

## Error Handling & Retry Mechanisms

### 1. Task-Level Retries (Celery)

```python
class AgentSpawnTask(Task):
    autoretry_for = (Exception,)       # Retry on any exception
    retry_kwargs = {
        'max_retries': 3,               # Max 3 attempts
        'countdown': 5                  # Wait 5s between retries
    }
    retry_backoff = True                # Exponential backoff: 5s, 10s, 20s
    retry_backoff_max = 60              # Max 60s between retries
    retry_jitter = True                 # Add random jitter to avoid thundering herd
```

**Scenarios Handled:**
- Transient network failures (LiveKit connection timeout)
- Temporary resource exhaustion (port unavailable)
- Race conditions (session ID collision)

### 2. Process-Level Monitoring

```python
@app.task(name='health_check_agents')
def health_check_agents():
    # Check if agent process is alive
    os.kill(int(pid), 0)

    # If dead, mark session as failed
    redis_client.hset(f'session:{session_id}', 'status', 'error')
```

**Scenarios Handled:**
- Agent process crashes (segfault, OOM)
- Python interpreter hangs
- LiveKit connection drops after successful start

### 3. Circuit Breaker Pattern (Express API)

```javascript
// Track consecutive failures
let failureCount = 0;
const FAILURE_THRESHOLD = 5;
const CIRCUIT_OPEN_DURATION = 60000; // 1 minute

app.post('/api/session/start', async (req, res) => {
  // If too many failures, reject new requests temporarily
  if (failureCount >= FAILURE_THRESHOLD) {
    const timeSinceLastFailure = Date.now() - lastFailureTime;

    if (timeSinceLastFailure < CIRCUIT_OPEN_DURATION) {
      return res.status(503).json({
        error: 'Service temporarily unavailable. Please try again in 1 minute.'
      });
    } else {
      // Reset circuit breaker
      failureCount = 0;
    }
  }

  // ... rest of logic
});
```

**Scenarios Handled:**
- Cascading failures (prevent overload)
- External service outages (LiveKit down)
- Resource exhaustion (out of memory)

### 4. Graceful Degradation

```javascript
// Try pre-warmed agent first
const prewarmedId = await assignPrewarmedAgent(userId);

if (prewarmedId) {
  // FAST PATH: Instant assignment
  return res.json({ sessionId: prewarmedId, status: 'ready' });
}

// FALLBACK: Spawn new agent (slower but guaranteed)
const sessionId = await spawnNewAgent(userId);
return res.json({ sessionId, status: 'starting' });
```

**User Experience:**
- Best case: <500ms (pre-warmed pool)
- Worst case: 15-20s (on-demand spawn)
- Never fails completely

### 5. Session Cleanup & Orphan Prevention

```python
@app.task(name='cleanup_stale_agents')
def cleanup_stale_agents():
    # Find sessions inactive for >30 minutes
    # Stop agent processes
    # Clean up Redis keys
```

**Prevents:**
- Memory leaks (orphaned processes)
- Resource exhaustion (zombie agents)
- Redis bloat (stale session data)

---

## Monitoring & Observability

### 1. Health Check Endpoint

```bash
curl http://localhost:8080/api/health
```

**Response:**
```json
{
  "success": true,
  "status": "healthy",
  "sessions": {
    "ready": 12,
    "starting": 2,
    "pool": 3
  },
  "stats": {
    "totalSpawned": 87,
    "totalAssigned": 84
  }
}
```

### 2. Railway Logs (Structured JSON)

**Agent Spawn Success:**
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "task": "spawn_voice_agent",
  "session_id": "session_abc123",
  "user_id": "user_456",
  "startup_time": 16.7,
  "status": "success"
}
```

**Agent Spawn Failure:**
```json
{
  "timestamp": "2024-01-15T10:31:00Z",
  "level": "ERROR",
  "task": "spawn_voice_agent",
  "session_id": "session_def456",
  "error": "Agent failed to connect within 20s",
  "retry_count": 2,
  "status": "retrying"
}
```

### 3. Redis Inspection (CLI)

```bash
# Connect to Railway Redis
railway run redis-cli -u $REDIS_URL

# Check pool size
SCARD pool:ready

# List all sessions
KEYS session:*

# Inspect specific session
HGETALL session:abc123

# View recent logs for agent
LRANGE agent:abc123:logs 0 -1

# Check Celery queue depth
LLEN celery
```

### 4. Metrics to Track

| Metric | Redis Key | Alert Threshold |
|--------|-----------|-----------------|
| Pre-warm pool size | `SCARD pool:ready` | <1 (pool depleted) |
| Agents starting | `SCARD session:starting` | >10 (slow spawns) |
| Total spawned | `HGET pool:stats total_spawned` | N/A |
| Average startup time | Calculated from session data | >25s (degraded) |
| Error rate | Count sessions with status=error | >10% |
| Celery queue depth | `LLEN celery` | >20 (backlog) |

### 5. Alerting Strategy (Railway Webhooks)

```javascript
// In Express, send webhook on critical errors
async function sendAlert(message) {
  await fetch(process.env.WEBHOOK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: `🚨 Voice Agent Alert: ${message}`,
      timestamp: new Date().toISOString()
    })
  });
}

// Example usage
if (poolSize === 0 && startingCount > 5) {
  sendAlert('Pre-warm pool depleted and spawns are slow!');
}
```

---

## Rollback Plan

### If Celery Migration Fails

**Immediate Rollback (5 minutes):**
1. In Railway dashboard, redeploy previous version
2. Remove Redis addon (optional, can keep for future)
3. Verify old orchestrator is running
4. Test session creation

**Data Recovery:**
- Redis data is non-critical (ephemeral sessions)
- No persistent state to migrate back
- Users can simply reconnect

**Rollback Triggers:**
- Error rate >25% for 10 minutes
- Average latency >30s (worse than current)
- Celery workers repeatedly crashing
- Redis connection failures

---

## Cost Analysis

### Current Architecture (Railway)

| Service | Monthly Cost |
|---------|--------------|
| Orchestrator (512MB RAM) | $5 |
| Frontend (256MB RAM) | $5 |
| **Total** | **$10/month** |

### Celery Architecture (Railway)

| Service | Monthly Cost |
|---------|--------------|
| Orchestrator (1GB RAM, runs Express + Celery) | $10 |
| Frontend (256MB RAM) | $5 |
| Redis Managed Addon (256MB) | $5 |
| **Total** | **$20/month** |

**Cost Increase:** $10/month (+100%)

**Value Delivered:**
- 97% latency reduction (pre-warmed pool)
- 4x concurrent spawning capacity
- 100% session persistence
- Automatic failure recovery
- Horizontal scaling foundation

**ROI:** Cost increase is acceptable for the reliability and UX improvements.

---

## Next Steps

1. **Review this plan** and confirm architecture decisions
2. **Provision Redis** addon in Railway dashboard
3. **Create feature branch** for Celery migration
4. **Implement Phase 1** (foundation: Celery + Redis)
5. **Test locally** with Docker Compose
6. **Deploy to Railway** staging environment
7. **Monitor for 48 hours** before production rollout
8. **Iterate** based on real-world performance

Would you like me to proceed with implementation, or do you have questions about any part of the plan?
