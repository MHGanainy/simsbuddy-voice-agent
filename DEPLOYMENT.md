# Deployment Guide - Railway

Deploy the LiveKit voice assistant to Railway with staging and production environments.

## Prerequisites

- Railway account (https://railway.app)
- Railway CLI installed
- GitHub repository
- API keys ready (see [CONFIGURATION.md](CONFIGURATION.md))

## Install Railway CLI

```bash
# macOS/Linux
curl -fsSL https://railway.app/install.sh | sh

# Or with npm
npm install -g @railway/cli

# Verify
railway --version

# Login
railway login
```

## Initial Setup

### 1. Create Project

```bash
# New project
railway init

# Or link existing
railway link

# Verify
railway status
```

### 2. Create Staging Environment

```bash
# Create staging environment
railway environment create staging

# Switch to staging
railway environment staging
```

### 3. Connect GitHub

In Railway dashboard:
1. Go to project settings
2. Connect GitHub repository
3. Select branch: `staging`
4. Enable "Auto-deploy on push"

### 4. Create Staging Branch

```bash
git checkout -b staging
git push -u origin staging
```

## Redis Setup

### Use Existing Railway Redis

In Railway dashboard:
1. Click "New" → Link existing service
2. Select your Redis instance
3. Copy connection URL

Or create new:
```bash
railway add
# Select: Redis
```

Get Redis URL:
```bash
railway variables --service redis
# Copy REDIS_URL value
```

## Environment Variables

### Set All Variables

```bash
railway variables set REDIS_URL="redis://default:password@host:port"
railway variables set LIVEKIT_URL="wss://your-project.livekit.cloud"
railway variables set LIVEKIT_API_KEY="APIxxxxx"
railway variables set LIVEKIT_API_SECRET="secretxxxxx"
railway variables set GROQ_API_KEY="gsk_xxxxx"
railway variables set ASSEMBLY_API_KEY="xxxxx"
railway variables set INWORLD_API_KEY="xxxxx"
railway variables set LOG_LEVEL="INFO"
railway variables set LOG_FORMAT="json"
railway variables set SERVICE_NAME="orchestrator"
railway variables set PYTHONPATH="/app"
railway variables set PYTHON_SCRIPT_PATH="/app/backend/agent/voice_assistant.py"
railway variables set MAX_BOTS="50"
railway variables set SESSION_TIMEOUT="1800000"
railway variables set BOT_STARTUP_TIMEOUT="30"
railway variables set PREWARM_POOL_SIZE="3"
```

Or copy from `.env.railway.example` and set via Railway dashboard.

See [CONFIGURATION.md](CONFIGURATION.md) for variable details.

## Service Configuration

### Backend Service

**Via Railway Dashboard:**
1. Click "New Service" → "GitHub Repo"
2. Configure:
   - **Name**: `orchestrator`
   - **Branch**: `staging`
   - **Root Directory**: `/`
   - **Dockerfile Path**: `/backend/Dockerfile`
   - **Builder**: Dockerfile

**Important:** Root Directory must be `/` (repository root).

### Frontend Service

**Via Railway Dashboard:**
1. Click "New Service" → "GitHub Repo"
2. Configure:
   - **Name**: `frontend`
   - **Branch**: `staging`
   - **Root Directory**: `/`
   - **Dockerfile Path**: `/frontend/Dockerfile`
   - **Builder**: Dockerfile

**Frontend Environment Variables:**
```bash
railway service frontend
railway variables set VITE_API_URL="https://your-backend.railway.app"
```

## Deploy

### Manual Deploy

```bash
# Switch to staging branch
git checkout staging
git push origin staging

# Railway auto-deploys
```

### Check Status

```bash
railway status --environment staging
```

### View Logs

```bash
railway logs --environment staging --follow
```

## Verify Deployment

### 1. Get Service URL

```bash
railway domain --environment staging
```

### 2. Test Health

```bash
curl https://your-app.railway.app/health

# Expected:
# {"status":"healthy","redis_connected":true,...}
```

### 3. Test Session

```bash
curl -X POST https://your-app.railway.app/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"RailwayTest","voiceId":"Ashley"}'

# Should return sessionId and LiveKit token
```

### 4. Check API Docs

Visit: `https://your-app.railway.app/docs`

## Monitoring

### View Logs

```bash
# Real-time logs
railway logs -f --environment staging

# Last 100 lines
railway logs -n 100

# Filter by service
railway logs --service orchestrator
```

### Railway Dashboard Metrics

- CPU usage
- Memory usage
- Network traffic
- Request count

### Health Checks

Railway automatically monitors:
- `/health` endpoint (every 30s)
- Auto-restart on failure

## Rollback

### Via Dashboard

1. Go to: Deployments
2. Find previous deployment
3. Click "..." → "Rollback"

### Via CLI

```bash
railway rollback
# Select deployment from list
```

## Production Deployment

### 1. Create Production Environment

```bash
railway environment create production
railway environment production
```

### 2. Set Production Variables

Adjust for production:
```bash
railway variables set LOG_LEVEL="WARN"
railway variables set MAX_BOTS="100"
railway variables set PREWARM_POOL_SIZE="5"
```

### 3. Configure Auto-Deploy

Set branch to `main` in Railway dashboard.

### 4. Deploy

```bash
git checkout main
git merge staging  # After testing staging
git push origin main
```

## Troubleshooting

### Deployment Fails

**Check:**
- Build logs: `railway logs --deployment <id>`
- Environment variables set?
- Dockerfile paths correct?

**Common issues:**
- Missing API keys
- Redis URL incorrect
- Build context issues

### Application Won't Start

**Check:**
```bash
railway logs --environment staging | grep -i error
```

**Common issues:**
- Supervisor config incorrect
- Port binding issues (Railway sets `$PORT`)
- Python import errors

### Health Check Fails

**Check:**
- Redis connection: `railway logs | grep redis`
- FastAPI started: `railway logs | grep uvicorn`

### Redis Connection Issues

**Verify URL:**
```bash
railway variables | grep REDIS_URL
```

**Test connection:**
```bash
railway run --service redis redis-cli PING
```

### Agent Spawn Failures

**Check logs:**
```bash
railway logs | grep "voice_assistant"
railway logs | grep "celery"
```

**Verify:**
- All API keys set
- `PYTHON_SCRIPT_PATH` correct
- Redis accessible

## Configuration Files

Railway uses these for deployment:

- **`backend/Dockerfile`** - Backend container image
- **`frontend/Dockerfile`** - Frontend container image
- **`backend/supervisord.conf`** - Process management (uses `$PORT`)
- **`.env.railway.example`** - Environment variable template

## Cost Optimization

**Tips:**
- Use Hobby plan for dev ($5/month)
- Set appropriate `MAX_BOTS` limit
- Monitor usage in dashboard
- Scale down unused services

## Workflow

### Development → Staging → Production

```
Local Dev → push staging → Test Staging → merge main → Production
```

**Steps:**
1. Develop locally (`make dev`)
2. Push to staging (`git push origin staging`)
3. Test staging deployment
4. Merge to main (`git merge staging && git push origin main`)
5. Auto-deploy to production

## Quick Reference

### Essential Commands

```bash
railway login               # Login to Railway
railway status             # View status
railway logs --follow      # Follow logs
railway variables set KEY=VALUE  # Set variable
railway restart            # Restart service
railway shell             # SSH into container
railway domain            # Get service URL
```

### Helper Scripts

Use the helper scripts in `scripts/`:

```bash
# View Railway logs
./scripts/view-railway-logs.sh --latest

# SSH into Railway
./scripts/railway-ssh.sh
```

See [scripts/README.md](scripts/README.md) for details.

## Next Steps

- Set up production environment
- Configure custom domain
- Set up monitoring/alerts
- Implement backup strategy
- Request Inworld TTS rate limit increase for production (if needed)
