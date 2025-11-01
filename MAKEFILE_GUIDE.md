# Makefile Quick Reference Guide

## 🚀 Quick Start

```bash
make dev-d          # Start all services in background
make logs-all       # View recent logs from all services
make health         # Check if everything is working
make stop           # Stop when done
```

## 📋 Core Commands

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands (default) |
| `make dev` | Start all services (attached, see logs) |
| `make dev-d` | Start all services in background (detached) |
| `make build` | Build all Docker images |
| `make stop` | Stop all services |
| `make restart` | Restart all services |
| `make clean` | Remove all containers, volumes, networks |

## 📊 Logging Commands

| Command | Description |
|---------|-------------|
| `make logs` | Follow logs from all services |
| `make logs-orchestrator` | Follow FastAPI orchestrator logs |
| `make logs-celery` | Follow Celery worker logs |
| `make logs-beat` | Follow Celery beat (scheduler) logs |
| `make logs-agent` | Show running voice agent processes and sessions |
| `make logs-agent-session SESSION=xxx` | View startup logs from Redis (last 100 lines) |
| `make logs-agent-live SESSION=xxx` | Follow live logs for a specific agent ⭐ |
| `make logs-agent-files` | List all agent log files |
| `make logs-redis` | Follow Redis logs |
| `make logs-frontend` | Follow frontend logs |
| `make logs-all` | Show recent logs (last 50 lines each) |

## 🔧 Utility Commands

| Command | Description |
|---------|-------------|
| `make ps` | Show status of all containers |
| `make status` | Detailed status + health checks |
| `make health` | Quick health check of all services |
| `make test` | Run full test suite |
| `make urls` | Show useful URLs |
| `make ports` | Show which ports are in use |

## 🔍 Shell Access

| Command | Description |
|---------|-------------|
| `make shell-orchestrator` | Open bash in orchestrator container |
| `make shell-redis` | Open redis-cli in Redis container |

## 💾 Redis Utilities

| Command | Description |
|---------|-------------|
| `make redis-keys` | Show all Redis keys |
| `make redis-sessions` | Show active sessions in Redis |
| `make redis-stats` | Show Redis statistics |
| `make redis-flush` | Flush Redis database (⚠️ deletes all data) |

## 🎯 Development Shortcuts

| Command | Description |
|---------|-------------|
| `make up` | Alias for `dev-d` |
| `make down` | Alias for `stop` |
| `make rebuild` | Rebuild everything from scratch |
| `make restart-orchestrator` | Restart just the orchestrator |
| `make restart-redis` | Restart just Redis |
| `make restart-frontend` | Restart just the frontend |

## 📝 Common Workflows

### Daily Development

```bash
# Start your day
make dev-d                  # Start services in background
make health                 # Verify everything is running

# During development
make logs-orchestrator      # Watch orchestrator logs
make logs-celery           # Watch Celery worker logs
make logs-agent-files      # List active agent sessions
make logs-agent-live SESSION=xxx  # Watch specific agent logs

# End your day
make stop                   # Stop services
```

### Debugging Issues

```bash
# Check what's running
make status                 # Full status overview
make ps                     # Quick container status

# View logs
make logs-all              # See recent logs from all services
make logs-orchestrator     # Drill into orchestrator
make logs-agent-files      # List all agent log files

# Access services
make shell-orchestrator    # Shell into orchestrator
make shell-redis          # Redis CLI

# Check agent logs
make logs-agent-live SESSION=xxx  # Follow live agent logs
make logs-agent-session SESSION=xxx  # View startup logs

# Check Redis state
make redis-sessions        # See active sessions
make redis-keys           # See all keys
```

### Testing Changes

```bash
# After code changes
make restart-orchestrator  # Restart orchestrator (hot reload)

# Full rebuild
make rebuild              # Rebuild everything from scratch

# Run tests
make test                 # Run full test suite
```

### Production Monitoring

```bash
# Quick health check
make health               # Check all services

# Detailed status
make status              # Container status + health checks

# View logs
make logs-all           # Recent logs from all services
make logs-orchestrator  # Live orchestrator logs
```

### Cleaning Up

```bash
# Stop services
make stop               # Stop containers (keep data)

# Full cleanup
make clean              # Remove containers + volumes
```

## 🎨 Output Colors

The Makefile uses color-coded output:

- **🔵 Blue** - Headers and section titles
- **🟢 Green** - Success messages and healthy status
- **🟡 Yellow** - Warnings and in-progress actions
- **🔴 Red** - Errors and dangerous operations
- **🔶 Cyan** - Information and log headers
- **🟣 Magenta** - Special highlights

## ⚠️ Important Notes

### Destructive Commands

These commands require confirmation:

- `make clean` - Removes all containers and volumes
- `make redis-flush` - Deletes all Redis data
- `make rebuild` - Rebuilds everything from scratch

### Log Locations

Inside the orchestrator container:

- FastAPI: `/var/log/supervisor/fastapi.log`
- Celery Worker: `/var/log/supervisor/celery-worker.log`
- Celery Beat: `/var/log/supervisor/celery-beat.log`

### Voice Agent Logs (Important!)

Voice agents are **subprocesses spawned by Celery workers**, not supervisor-managed processes. **Continuous logging is now fully implemented!**

**Log Storage:**
- **File-based logs**: All logs written to `/var/log/voice-agents/SESSION_ID.log` (persistent)
- **Redis logs**: Last 100 lines cached in Redis for quick API access
- **Background thread**: Continuously reads agent stdout/stderr and writes to both locations

**How to view logs:**

```bash
# List all agent log files (most recent first)
make logs-agent-files

# Follow live logs for a specific session (like tail -f)
make logs-agent-live SESSION=session_1761992887507_24hj1j6l7

# View last 100 lines from Redis (quick access)
make logs-agent-session SESSION=session_1761992887507_24hj1j6l7

# See running processes and available sessions
make logs-agent
```

**Example workflow:**
```bash
# 1. Create a session
curl -X POST http://localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"TestUser","voiceId":"Ashley"}'

# 2. Extract session ID from response
# session_1761992887507_24hj1j6l7

# 3. Follow live logs
make logs-agent-live SESSION=session_1761992887507_24hj1j6l7

# You'll see:
# - Startup logs (environment validation, service initialization)
# - LiveKit connection logs
# - Pipeline activity
# - User interactions
# - Ongoing conversation logs
# - Error messages (if any)
```

**Benefits:**
- ✅ **Complete log history**: All logs from startup through shutdown
- ✅ **Real-time monitoring**: Use tail -f via `make logs-agent-live`
- ✅ **Persistent storage**: Logs saved to volume, survive restarts
- ✅ **No pipe blocking**: Background thread prevents stdout buffer overflow
- ✅ **Dual access**: Both file-based (long-term) and Redis (quick API access)

### Service Names

- Orchestrator: `voice-agent-orchestrator`
- Redis: `voice-agent-redis`
- Frontend: `voice-agent-frontend`

### Ports

- Orchestrator API: `http://localhost:8000`
- Frontend: `http://localhost:3000`
- Redis: `localhost:6379`
- API Docs: `http://localhost:8000/docs`

## 🆘 Troubleshooting

### Services won't start

```bash
make clean              # Clean up everything
make build             # Rebuild images
make dev-d             # Start fresh
```

### Can't see logs

```bash
make ps                # Check if containers are running
make status           # Check detailed status
make logs-all         # Try to view all logs
```

### Services are slow

```bash
make redis-stats      # Check Redis performance
make health          # Check service health
make logs-celery     # Check Celery worker logs
```

### Redis is full

```bash
make redis-keys       # See what's in Redis
make redis-flush      # Clear everything (⚠️ careful!)
```

## 💡 Tips & Tricks

1. **Tab completion**: Most shells support tab completion for make targets

2. **Combine with watch**:
   ```bash
   watch -n 2 make health    # Health check every 2 seconds
   ```

3. **Grep logs**:
   ```bash
   make logs-orchestrator | grep "error"
   make logs-celery | grep "session_123"
   ```

4. **Quick session check**:
   ```bash
   make redis-sessions | less    # View all sessions
   ```

5. **Background logs**:
   ```bash
   make logs-orchestrator > orchestrator.log &
   ```

## 📚 Related Documentation

- **Logging System**: `cat backend/LOGGING.md`
- **Backend README**: `cat backend/README.md`
- **API Docs**: `http://localhost:8000/docs`
- **Docker Compose**: `cat docker-compose.yml`

## 🔗 Useful Commands (Non-Make)

```bash
# Direct docker-compose
docker-compose ps                    # Container status
docker-compose logs -f orchestrator  # Follow specific service

# Direct docker
docker exec voice-agent-orchestrator bash  # Shell into container
docker logs voice-agent-orchestrator       # View logs

# Check ports
lsof -i :8000                       # What's using port 8000
curl http://localhost:8000/health   # Direct health check
```

---

**Pro Tip**: Run `make help` anytime to see all available commands!
