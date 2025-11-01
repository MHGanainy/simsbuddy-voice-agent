# Railway Deployment Guide

Complete guide for deploying the LiveKit Voice Agent to Railway with staging environment and auto-deploy.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Initial Setup](#initial-setup)
4. [Railway Project Setup](#railway-project-setup)
5. [Environment Variables](#environment-variables)
6. [Deploying to Staging](#deploying-to-staging)
7. [Monitoring & Logs](#monitoring--logs)
8. [Troubleshooting](#troubleshooting)
9. [Production Deployment](#production-deployment)

---

## Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Railway Project                                              │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │   Backend        │      │   Frontend       │            │
│  │  (Orchestrator)  │◄─────┤   (React SPA)    │            │
│  │                  │      │                  │            │
│  │  • FastAPI       │      │  • Vite build    │            │
│  │  • Celery worker │      │  • Static serve  │            │
│  │  • Celery beat   │      └──────────────────┘            │
│  └────────┬─────────┘                                       │
│           │                                                 │
│           │                                                 │
│  ┌────────▼─────────┐                                       │
│  │   Redis          │                                       │
│  │  (Existing)      │                                       │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

### Services

| Service | Description | Port | Health Check |
|---------|-------------|------|--------------|
| **orchestrator** | FastAPI + Celery (supervisor) | `$PORT` | `/health` |
| **frontend** | React app (static) | `$PORT` | `/` |
| **redis** | Session & task storage | 6379 | Existing service |

---

## Prerequisites

### 1. Railway CLI

Install the Railway CLI:

```bash
# macOS/Linux
curl -fsSL https://railway.app/install.sh | sh

# Or with npm
npm install -g @railway/cli

# Verify installation
railway --version
```

### 2. Railway Account

- Sign up at https://railway.app
- Create account (GitHub login recommended)
- Have your existing Redis service ready

### 3. API Keys

Collect these API keys (see `.env.railway.example`):

- **LiveKit**: URL, API Key, API Secret
- **Groq**: API Key for LLM
- **AssemblyAI**: API Key for STT
- **Inworld**: API Key for character AI

---

## Initial Setup

### Step 1: Clone and Verify

```bash
# Ensure you're in the project root
cd /path/to/livekit-demo

# Verify Dockerfiles exist
ls -la backend/Dockerfile frontend/Dockerfile

# Verify supervisord is Railway-compatible (uses PORT variable)
grep "%(ENV_PORT)s" backend/supervisord.conf
```

### Step 2: Login to Railway

```bash
# Login (opens browser)
railway login

# Verify login
railway whoami
```

---

## Railway Project Setup

### Step 1: Create New Project

```bash
# Initialize Railway project
railway init

# Enter project name when prompted
# Example: "livekit-voice-agent"
```

### Step 2: Create Staging Environment

```bash
# Create staging environment
railway environment

# When prompted, select:
# • Create new environment
# • Name: staging
```

### Step 3: Link GitHub Repository

```bash
# Link your GitHub repo
railway link

# Select your repository from the list
# This enables auto-deploy on branch push
```

### Step 4: Create Staging Branch

```bash
# Create and push staging branch
git checkout -b staging
git push -u origin staging

# Switch back to main
git checkout main
```

---

## Service Configuration

### Backend Service (Orchestrator)

**Via Railway Dashboard** (Recommended)

1. Go to Railway dashboard → Your Project
2. Click "New Service"
3. Select "GitHub Repo"
4. Choose your repository
5. Configure service:
   - **Name**: `orchestrator` or `backend`
   - **Branch**: `staging`
   - **Root Directory**: `/` (repository root)
   - **Builder**: Dockerfile
   - **Dockerfile Path**: `/backend/Dockerfile`

**Important Notes:**
- The Root Directory MUST be `/` (not `/backend`)
- The Dockerfile Path should be `/backend/Dockerfile` (absolute path from root)
- Railway will automatically inject the `PORT` environment variable
- Supervisord will use this PORT to start FastAPI on the correct port

**Via CLI (Alternative):**

```bash
# Switch to staging environment
railway environment staging

# Link to your repo
railway link

# Deploy
railway up
```

Then configure Root Directory and Dockerfile Path in the Railway dashboard.

### Frontend Service

**Via Railway Dashboard:**

1. Click "New Service" in same project
2. Select "GitHub Repo" (same repository)
3. Configure service:
   - **Name**: `frontend`
   - **Branch**: `staging`
   - **Root Directory**: `/` (repository root)
   - **Builder**: Dockerfile
   - **Dockerfile Path**: `/frontend/Dockerfile`

**Important Notes:**
- The Root Directory MUST be `/` (not `/frontend`)
- The Dockerfile Path should be `/frontend/Dockerfile` (absolute path from root)
- This ensures the Dockerfile can access `frontend/` subdirectory for copying files

### Link Existing Redis

**Via Railway Dashboard:**

1. In your project, click "Add Service"
2. Select "Existing Service"
3. Choose your existing Redis instance
4. Copy the connection URL

---

## Environment Variables

### Backend (Orchestrator)

Set environment variables via CLI:

```bash
# Switch to orchestrator service
railway service orchestrator

# Set all variables at once
railway variables set \
  REDIS_URL="redis://default:YOUR_PASSWORD@hostname:6379" \
  LIVEKIT_URL="wss://your-project.livekit.cloud" \
  LIVEKIT_API_KEY="APIxxxxxxxxxx" \
  LIVEKIT_API_SECRET="xxxxxxxxxxxxxxxxxx" \
  GROQ_API_KEY="gsk_xxxxxxxxxxxxxxxxxx" \
  ASSEMBLY_API_KEY="xxxxxxxxxxxxxxxx" \
  INWORLD_API_KEY="xxxxxxxxxxxxxxxx" \
  LOG_LEVEL="INFO" \
  LOG_FORMAT="json" \
  SERVICE_NAME="orchestrator" \
  PYTHONPATH="/app" \
  PYTHON_SCRIPT_PATH="/app/backend/agent/voice_assistant.py" \
  MAX_BOTS="50" \
  SESSION_TIMEOUT="1800000" \
  BOT_STARTUP_TIMEOUT="30" \
  PREWARM_POOL_SIZE="3"
```

**Or set individually:**

```bash
railway variables set REDIS_URL="redis://..."
railway variables set LIVEKIT_URL="wss://..."
# ... etc
```

**Or via Dashboard:**

1. Go to Service → Variables
2. Click "New Variable"
3. Add each variable from `.env.railway.example`

### Frontend

```bash
# Switch to frontend service
railway service frontend

# Set frontend variables
railway variables set \
  VITE_API_URL="https://orchestrator-staging.railway.app"
```

**Note:** Replace with your actual backend Railway URL once deployed.

---

## Auto-Deploy Configuration

### Step 1: Configure Deployment Triggers

**Via Dashboard:**

1. Go to Service Settings
2. Under "Deployments" section:
   - **Source**: GitHub
   - **Branch**: `staging`
   - **Auto-deploy**: ✓ ON
   - **Deploy on PR**: Optional

### Step 2: Verify GitHub Integration

```bash
# Check current deployment settings
railway status

# Should show:
# • Environment: staging
# • Branch: staging
# • Auto-deploy: enabled
```

### Step 3: Test Auto-Deploy

```bash
# Make a change and push to staging
git checkout staging
git merge main
git push origin staging

# Railway will automatically detect and deploy
```

---

## Deploying to Staging

### Initial Deployment

```bash
# Ensure staging branch is up to date
git checkout staging
git merge main
git push origin staging

# Railway will automatically:
# 1. Detect push to staging branch
# 2. Run GitHub Actions checks
# 3. Build services using nixpacks/Docker
# 4. Deploy to staging environment
```

### Monitor Deployment

```bash
# Watch deployment logs
railway logs --environment staging

# Or for specific service
railway logs --service orchestrator --environment staging
railway logs --service frontend --environment staging
```

### Get Deployment URLs

```bash
# List all services and their URLs
railway status

# Or get specific service URL
railway domain --service orchestrator
railway domain --service frontend
```

---

## Monitoring & Logs

### View Logs

**Via CLI:**

```bash
# Follow all logs in real-time
railway logs --follow

# Filter by service
railway logs --service orchestrator --follow

# View last 100 lines
railway logs --tail 100

# Filter by severity
railway logs | grep ERROR
```

**Via Dashboard:**

1. Go to Service → Deployments
2. Click on latest deployment
3. View logs in real-time

### Health Checks

**Backend Health Check:**

```bash
# Get orchestrator URL
BACKEND_URL=$(railway domain --service orchestrator)

# Check health endpoint
curl https://$BACKEND_URL/health

# Expected response:
# {
#   "status": "healthy",
#   "redis_connected": true,
#   "celery_active": true,
#   "livekit_configured": true
# }
```

**Test Session Creation:**

```bash
curl -X POST https://$BACKEND_URL/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userName":"TestUser"}'

# Expected: Session created with LiveKit token
```

### Railway Dashboard Metrics

Monitor in Railway Dashboard:

- **CPU Usage**: Service → Metrics → CPU
- **Memory Usage**: Service → Metrics → Memory
- **Request Rate**: Service → Metrics → Requests
- **Response Time**: Service → Metrics → Latency

---

## Troubleshooting

### Common Issues

#### 1. Build Fails - Python Dependencies

**Error:** `Could not find a version that satisfies the requirement`

**Solution:**

```bash
# Check nixpacks.toml Python version
cat nixpacks.toml | grep python

# Ensure requirements.txt versions are compatible
# Update if needed and push
```

#### 2. Supervisor Not Starting

**Error:** `unix:///var/run/supervisor.sock no such file`

**Solution:**

```bash
# Verify supervisord.conf uses /tmp paths
grep "logfile=/tmp" supervisord.conf
grep "pidfile=/tmp" supervisord.conf
```

#### 3. Port Binding Error

**Error:** `Address already in use: 8000`

**Solution:**

Ensure `supervisord.conf` uses Railway's `$PORT`:

```ini
command=uvicorn main:app --host 0.0.0.0 --port %(ENV_PORT)s
```

#### 4. Redis Connection Failed

**Error:** `ConnectionError: Error connecting to Redis`

**Solution:**

```bash
# Verify REDIS_URL is set correctly
railway variables --service orchestrator | grep REDIS_URL

# Test Redis connection
railway run --service orchestrator \
  python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.ping())"
```

#### 5. Celery Workers Not Running

**Error:** `No nodes replied within time constraint`

**Check logs:**

```bash
railway logs --service orchestrator | grep celery

# Look for:
# • "celery-worker" process starting
# • "celery@..." node registration
# • Any error messages
```

**Solution:**

Verify supervisor is running all processes:

```bash
# SSH into Railway container
railway shell --service orchestrator

# Check supervisor status
supervisorctl status

# Should show:
# celery-beat    RUNNING
# celery-worker  RUNNING
# fastapi        RUNNING
```

#### 6. Frontend Can't Connect to Backend

**Error:** `Failed to fetch` or CORS errors

**Solution:**

```bash
# Verify frontend has correct backend URL
railway variables --service frontend | grep VITE_

# Update if needed
railway variables set VITE_API_URL="https://your-backend.railway.app"

# Rebuild frontend
railway up --service frontend
```

### Debug Commands

```bash
# View all environment variables
railway variables

# SSH into container
railway shell

# Restart service
railway restart --service orchestrator

# View deployment details
railway status

# Check service health
railway logs --service orchestrator --tail 50 | grep health
```

---

## Production Deployment

### Step 1: Create Production Environment

```bash
# Create production environment
railway environment

# Select: Create new environment
# Name: production
```

### Step 2: Configure Production Branch

**Recommended:** Use `main` branch for production

1. Railway Dashboard → Production environment
2. Service Settings → Source
3. Change branch from `staging` to `main`
4. Enable auto-deploy

### Step 3: Set Production Variables

```bash
# Switch to production environment
railway environment production

# Set production-specific variables
railway variables set LOG_LEVEL="WARNING"
railway variables set MAX_BOTS="100"
railway variables set PREWARM_POOL_SIZE="5"

# Use production API keys if different
```

### Step 4: Custom Domain (Optional)

```bash
# Add custom domain
railway domain --service orchestrator yourdomain.com
railway domain --service frontend app.yourdomain.com

# Follow DNS configuration instructions
```

---

## Workflow Summary

### Development → Staging → Production

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│   Local     │     │   Staging    │     │  Production    │
│ Development │────▶│  Environment │────▶│  Environment   │
│             │     │              │     │                │
│ git push    │     │ staging      │     │ main branch    │
│ staging     │     │ branch       │     │                │
└─────────────┘     └──────────────┘     └────────────────┘
                           ▲                      ▲
                           │                      │
                    Auto-deploy on          Auto-deploy on
                    staging push             main push
```

**Steps:**

1. **Develop locally** → Test with `make dev`
2. **Push to staging** → `git push origin staging`
3. **Verify on staging** → Test staging URLs
4. **Merge to main** → `git merge staging` → `git push origin main`
5. **Auto-deploy to production** → Railway deploys automatically

---

## Quick Reference

### Essential Commands

```bash
# Login
railway login

# View status
railway status

# View logs
railway logs --follow

# Set variable
railway variables set KEY=VALUE

# Restart service
railway restart

# SSH into container
railway shell

# Get service URL
railway domain
```

### Important URLs

- **Railway Dashboard**: https://railway.app/dashboard
- **Railway Docs**: https://docs.railway.app
- **LiveKit Cloud**: https://cloud.livekit.io
- **Project Repository**: [Your GitHub URL]

### Support

- **Railway Discord**: https://discord.gg/railway
- **Railway Support**: support@railway.app
- **Project Issues**: [Your GitHub Issues URL]

---

## Configuration Files Reference

| File | Purpose | Location |
|------|---------|----------|
| `railway.toml` | Backend deployment config | `/railway.toml` |
| `nixpacks.toml` | Build configuration | `/nixpacks.toml` |
| `.railwayignore` | Files to exclude from deploy | `/.railwayignore` |
| `frontend/railway.json` | Frontend deployment config | `/frontend/railway.json` |
| `supervisord.conf` | Multi-process management | `/supervisord.conf` |
| `.env.railway.example` | Environment variable template | `/.env.railway.example` |
| `.github/workflows/staging-checks.yml` | CI/CD checks | `/.github/workflows/` |

---

## Next Steps

1. ✓ Complete initial Railway setup
2. ✓ Deploy to staging environment
3. ✓ Test all endpoints thoroughly
4. □ Set up monitoring and alerts
5. □ Configure custom domains
6. □ Set up production environment
7. □ Implement backup strategy

---

**Last Updated:** 2025-01-11
**Railway CLI Version:** 3.x
**Python Version:** 3.11
**Node Version:** 18
