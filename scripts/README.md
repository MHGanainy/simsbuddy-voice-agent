# Helper Scripts

Utility scripts for Railway deployment debugging and testing.

## Prerequisites

```bash
# Install Railway CLI (for Railway scripts)
npm install -g @railway/cli
railway login

# Install jq (for test scripts)
brew install jq  # macOS
# or
apt-get install jq  # Linux
```

## Scripts

### test_concurrent_sessions.py - Concurrent Session Isolation Test

**Purpose:** Validates that multiple voice agent sessions can run simultaneously with complete isolation. Tests process group boundaries and prevents cross-contamination between patient consultations.

**What it tests:**
- 5 concurrent sessions with different patients and voices
- Unique process groups (PID, PGID) for each session
- Process group leader verification (PGID == PID)
- Independent session termination (random order)
- Cross-contamination prevention
- Redis namespace isolation
- Separate log files for each session

**Usage:**
```bash
# Run with default orchestrator URL (http://localhost:8000)
python3 scripts/test_concurrent_sessions.py

# Run with custom orchestrator URL
ORCHESTRATOR_URL=http://your-server:8000 python3 scripts/test_concurrent_sessions.py
```

**Requirements:**
- Python 3.7+
- `aiohttp` library (async HTTP requests)
- `colorama` library (colored output)
- Orchestrator must be running

**Install dependencies:**
```bash
pip3 install aiohttp colorama --break-system-packages
# or with --user flag
pip3 install aiohttp colorama --user
```

**Example output:**
```
╔════════════════════════════════════════════════════════════════════╗
║     Concurrent Session Isolation Test - Medical Voice Agents      ║
╚════════════════════════════════════════════════════════════════════╝

Step 1: Starting Concurrent Sessions
[PASS] Session started: patient1 → session_123...
[PASS] Session started: patient2 → session_456...
... (5 sessions total)

Step 2: Verifying Session Isolation
Session Status:
Patient    Session ID         PID   PGID  Leader  Alive  Status
patient1   session_123...     258   258   ✓       ✓      Running
patient2   session_456...     260   260   ✓       ✓      Running
...

Step 3: Isolation Verification
[PASS] All 5 sessions have unique PIDs
[PASS] All 5 sessions have unique PGIDs
[PASS] All sessions are group leaders (PGID == PID)
[PASS] All sessions are alive
[PASS] All 5 sessions have unique log files

Step 4: Testing Independent Termination
[TEST] Terminating in random order: patient3, patient1, patient5...
[PASS] 4 sessions still alive (expected 4)
[PASS] 3 sessions still alive (expected 3)
...

Final Test Report:
  ✓ ALL TESTS PASSED
  Passed: 24 / Failed: 0 / Pass Rate: 100%

Conclusion: Multiple medical consultations can run simultaneously
with complete isolation. Process groups provide proper boundaries.
```

**What this proves:**
- ✅ Multiple medical consultations can run at the same time
- ✅ Each patient's session is completely isolated
- ✅ Terminating one session never affects others
- ✅ Process groups provide proper isolation boundaries
- ✅ System is production-ready for concurrent use

---

### test-termination.sh - Process Group Termination Test

**Purpose:** Validates that voice agent processes and their child processes (ffmpeg, etc.) are properly terminated when a session ends.

**What it tests:**
- Process spawning with correct process group setup
- Process group leader verification (PGID == PID)
- Proper cleanup when session ends
- Redis key cleanup
- All child processes are terminated

**Usage:**
```bash
# Run with default orchestrator URL (http://localhost:8000)
./scripts/test-termination.sh

# Run with custom orchestrator URL
ORCHESTRATOR_URL=http://your-server:8000 ./scripts/test-termination.sh
```

**Requirements:**
- `curl` command (for API calls)
- `jq` command (for JSON parsing)
- `redis-cli` or Docker (optional, for Redis verification)
- Orchestrator must be running

**Example output:**
```
=== Process Group Termination Test ===

=== Step 1: Starting Test Session ===
[PASS] Session started: session_1234567890_abc123def

=== Step 2: Waiting for Agent to Start ===
[INFO] Waiting 5 seconds for agent to fully initialize...

=== Step 3: Verifying Process Group Setup ===
[PASS] Process is alive (PID: 12345)
[PASS] Process is group leader (PID == PGID: 12345)
[PASS] Process group is alive
[INFO] Found 2 process(es) in the group:
  - PID 12345: python3 /app/backend/agent/voice_assistant.py
  - PID 12346: ffmpeg -i pipe:0 -f wav pipe:1

=== Step 4: Terminating Session ===
[PASS] Session end request accepted

=== Step 5: Verifying Process Cleanup ===
[PASS] Process is NOT alive (killed successfully)
[PASS] Process group is NOT alive (killed successfully)

=== Step 6: Verifying Redis Cleanup ===
[PASS] Redis key 'session:...' cleaned up
[PASS] Redis key 'agent:...:pid' cleaned up

=== Test Summary ===
Total checks: 8
Passed: 8
Failed: 0

✓ All tests passed! Process group termination is working correctly.
```

**Troubleshooting:**
- If tests fail, check orchestrator logs for errors
- Ensure all required environment variables are set
- Verify LiveKit, Groq, Inworld, and AssemblyAI credentials are valid

---

### view-railway-logs.sh - View Agent Logs

View voice agent logs from Railway remotely.

**Usage:**
```bash
# List all sessions
./scripts/view-railway-logs.sh --list

# View latest session
./scripts/view-railway-logs.sh --latest

# View specific session (default: 100 lines)
./scripts/view-railway-logs.sh session_1762006306800_xyz

# View specific session (custom lines)
./scripts/view-railway-logs.sh session_1762006306800_xyz 200

# View only errors
./scripts/view-railway-logs.sh session_1762006306800_xyz --errors
```

### railway-ssh.sh - SSH Access

SSH into Railway backend service.

**Usage:**
```bash
./scripts/railway-ssh.sh
```

**Useful commands once inside:**
```bash
# List recent logs
ls -lht /var/log/voice-agents/ | head -10

# View session log
tail -100 /var/log/voice-agents/session_xyz.log

# Follow logs in real-time
tail -f /var/log/voice-agents/session_xyz.log

# Search for errors
grep -i "error" /var/log/voice-agents/session_xyz.log

# Check environment
echo "$INWORLD_API_KEY" | head -c 10

# Check processes
ps aux | grep voice_assistant
```

## Common Workflows

### Debug a Session
```bash
# 1. List recent sessions
./scripts/view-railway-logs.sh --list

# 2. Check for errors
./scripts/view-railway-logs.sh session_xyz --errors

# 3. View full logs if needed
./scripts/view-railway-logs.sh session_xyz 500
```

### Live Monitoring
```bash
# SSH into Railway
./scripts/railway-ssh.sh

# Follow logs in real-time
tail -f /var/log/voice-agents/session_xyz.log
```

## Troubleshooting

### "railway: command not found"
```bash
npm install -g @railway/cli
```

### "Permission denied"
```bash
chmod +x scripts/*.sh
```

### "No logs found"
Check session ID:
```bash
./scripts/view-railway-logs.sh --list
```
