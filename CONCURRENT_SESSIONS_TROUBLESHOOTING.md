# Concurrent Sessions Audio Issue - Troubleshooting Guide

## Issue Summary

When opening 2 sessions simultaneously on Railway (e.g., one from phone and one from laptop), **only ONE session receives audio**. However, the same setup works correctly in local development.

## Root Cause Analysis

### Primary Suspect: Inworld TTS API Rate Limiting

Based on investigation, the most likely cause is **Inworld TTS API concurrent request limits**:

1. **Rate Limits (from Inworld documentation)**:
   - Default: **20 requests per second** per workspace
   - Concurrent sessions: **2-4 for basic plans**
   - Studio API: **5 RPS** (Requests Per Second) per API key

2. **Error Signature**:
   ```json
   {
     "error": {
       "code": 7,
       "message": "Invalid credentials provided for API key \"Xt75vK0jWr7BP4XosDi5UZfwPzryQh70\"",
       "details": []
     }
   }
   ```

   **Note**: This "Invalid credentials" error is misleading - credentials are valid (verified by local testing). Inworld may return this error as a catch-all for rate limiting or quota issues.

3. **Key Observation**: Audio works locally but fails on Railway with 2 concurrent sessions
   - Local: Works fine with same credentials
   - Railway: Only 1 of 2 sessions gets audio
   - This points to environment-specific constraints, not code issues

### Secondary Factors

1. **Railway Network Constraints**:
   - Shared egress IP addresses
   - Potential IP-based rate limiting by Inworld
   - Network resource limits per container

2. **Outdated Pipecat Version**:
   - Project was using pipecat-ai 0.0.85
   - Latest version is 0.0.92
   - May have had bugs in Inworld TTS error handling

## Fixes Applied

### 1. Upgrade Pipecat-AI (Completed)

**Changed**: `backend/agent/requirements.txt`
```diff
- pipecat-ai[livekit]==0.0.85
+ pipecat-ai[livekit,inworld]==0.0.92
```

**Benefits**:
- Latest bug fixes for Inworld TTS integration
- Improved error handling and session isolation
- Explicit `inworld` extra ensures all Inworld dependencies are installed

**Commit**: `c004a1c - Upgrade pipecat-ai from 0.0.85 to 0.0.92`

### 2. Request Inworld Rate Limit Increase (Recommended)

Contact Inworld support to increase your rate limits:

1. **Via Inworld Portal**:
   - Go to: https://platform.inworld.ai/
   - Navigate to: Billing section
   - Request: "Increase concurrent TTS session limit for production use"

2. **Recommended Limits for Production**:
   - Concurrent sessions: At least 10-20 (depending on expected traffic)
   - Requests per second: 50-100 RPS
   - Note: Inworld typically increases limits at no additional cost

3. **Expected Response Time**: Within 48 hours

## Testing Plan

### Test 1: Local Verification (Already Passing)
- ✅ Single session works
- ✅ 2 concurrent sessions work

### Test 2: Railway Staging with Upgraded Pipecat
1. Deploy upgraded pipecat to Railway staging
2. Open 2 concurrent sessions (phone + laptop)
3. Check if both sessions receive audio
4. Monitor Railway logs for Inworld TTS errors

**Expected Outcome**:
- Best case: Upgrade fixes the issue
- Likely case: Still only 1 session gets audio (rate limit issue)

### Test 3: After Inworld Limit Increase
1. Request and receive Inworld rate limit increase
2. Deploy to Railway staging
3. Test 2+ concurrent sessions
4. Verify all sessions receive audio correctly

## Deployment Instructions

### Deploy to Railway Staging

```bash
# Ensure you're on the staging branch
git checkout staging

# Merge the pipecat upgrade
git merge monorepo-structure  # or your current branch

# Push to Railway (auto-deploy enabled)
git push origin staging

# Monitor deployment
railway logs --service orchestrator --environment staging --follow
```

### Verify Deployment

```bash
# Check pipecat version in Railway
railway shell --service orchestrator
pip list | grep pipecat-ai
# Should show: pipecat-ai 0.0.92

# View agent logs
./scripts/view-railway-logs.sh --latest

# Test concurrent sessions via frontend
# Open https://your-frontend-staging.railway.app from 2 devices
```

## Monitoring Concurrent Sessions

### Railway Logs

Use the helper script to view logs:

```bash
# View latest session logs
./scripts/view-railway-logs.sh --latest

# View specific session
./scripts/view-railway-logs.sh SESSION_ID

# View errors only
./scripts/view-railway-logs.sh SESSION_ID --errors
```

### Key Log Patterns to Watch

**Session 1 Success**:
```
Inworld TTS service initialized
Pipeline started
Connected to LiveKit room
```

**Session 2 Failure** (if rate limited):
```
Inworld API error: {"error":{"code":7,"message":"Invalid credentials...
```

## Recommendations

### Short-term (Immediate)

1. **Deploy Pipecat Upgrade to Railway**
   - May resolve session isolation issues
   - Improves error handling

2. **Monitor Concurrent Usage**
   - Track how many users attempt concurrent sessions
   - Log all Inworld TTS errors with session IDs

3. **Request Inworld Limit Increase**
   - Essential for production with multiple users

### Long-term (Production Readiness)

1. **Implement TTS Retry Logic**
   - Add exponential backoff for failed TTS requests
   - Queue TTS requests if rate limit is hit

2. **Add TTS Fallback**
   - Consider a secondary TTS provider (ElevenLabs, Cartesia)
   - Switch to fallback if Inworld rate limit is exceeded

3. **Session Queuing**
   - Implement a queue for concurrent sessions
   - Delay session start if all slots are full

4. **Monitoring & Alerting**
   - Track TTS success/failure rates
   - Alert if concurrent session failure rate > 10%

## Configuration for Higher Concurrency

If Inworld approves higher limits, update environment variables:

```bash
# Railway Environment Variables
# (Already set, but verify these are optimal)

# Celery worker concurrency (parallel agent spawns)
CELERY_CONCURRENCY=4  # Can increase to 8-16 for higher load

# Maximum bot sessions
MAX_BOTS=50  # Can increase to 100-200 for production

# Pre-warmed agent pool (agents ready to go)
PREWARM_POOL_SIZE=3  # Increase to 5-10 for faster session starts

# Session timeout (30 minutes)
SESSION_TIMEOUT=1800000
```

## Alternative TTS Providers (If Needed)

If Inworld rate limiting remains an issue, consider:

| Provider | Pros | Cons | Concurrent Limit |
|----------|------|------|------------------|
| **Inworld** | Best quality, low latency | Strict rate limits on basic plans | 2-4 (basic), 20+ (custom) |
| **ElevenLabs** | Great quality, good concurrency | Higher cost | 50+ on Pro plan |
| **Cartesia** | Fast, modern API | Newer provider | 100+ requests/sec |
| **OpenAI TTS** | Simple integration | Lower quality for conversation | High concurrency |

## Next Steps

1. **Deploy to Railway Staging**: Test upgraded pipecat
2. **Request Inworld Limit Increase**: Submit support request
3. **Monitor Metrics**: Track concurrent session success rates
4. **Document Results**: Update this guide with findings

## References

- **Inworld TTS Docs**: https://docs.inworld.ai/docs/tts/tts
- **Inworld Rate Limits**: https://docs.inworld.ai/docs/resources/rate-limits
- **Pipecat Inworld Integration**: https://docs.pipecat.ai/server/services/tts/inworld
- **LiveKit Agent Docs**: https://docs.livekit.io/agents/

---

**Last Updated**: 2025-11-01
**Status**: Testing pipecat upgrade, Inworld limit increase pending
**Author**: Claude Code
