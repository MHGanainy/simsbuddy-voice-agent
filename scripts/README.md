# Railway Helper Scripts

Utilities for viewing Railway deployment logs and debugging.

## Scripts

### `view-railway-logs.sh` - View Agent Logs Remotely

View voice agent logs from Railway without SSHing in.

**Usage:**

```bash
# List all available sessions
./scripts/view-railway-logs.sh --list

# View latest session logs (default: 100 lines)
./scripts/view-railway-logs.sh --latest

# View latest session logs (custom lines)
./scripts/view-railway-logs.sh --latest 50

# View specific session logs (default: 100 lines)
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy

# View specific session logs (custom lines)
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy 200

# View only errors for a session
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy --errors
```

**Examples:**

```bash
# Quick check: list recent sessions
./scripts/view-railway-logs.sh --list

# View the most recent session
./scripts/view-railway-logs.sh --latest

# Debug a specific session
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy --errors

# View full session log
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy 500
```

### `railway-ssh.sh` - Quick SSH Access

SSH into the Railway backend service.

**Usage:**

```bash
./scripts/railway-ssh.sh
```

Once inside, use these commands:

```bash
# List recent session logs
ls -lht /var/log/voice-agents/ | head -10

# View specific session log
tail -100 /var/log/voice-agents/session_1762006306800_95vwu1ldy.log

# Follow logs in real-time (like tail -f)
tail -f /var/log/voice-agents/session_1762006306800_95vwu1ldy.log

# Search for errors
grep -i "error\|exception" /var/log/voice-agents/session_1762006306800_95vwu1ldy.log

# Check environment variables
echo "INWORLD_API_KEY: ${INWORLD_API_KEY:0:10}..."
echo "GROQ_API_KEY: ${GROQ_API_KEY:0:10}..."
echo "LIVEKIT_URL: $LIVEKIT_URL"

# Check running processes
ps aux | grep voice_assistant
```

## Prerequisites

Install Railway CLI:

```bash
# macOS/Linux
curl -fsSL https://railway.app/install.sh | sh

# Or with npm
npm install -g @railway/cli

# Login
railway login
```

## Configuration

The scripts are pre-configured with your Railway project details:

- **Project ID**: `eeadd330-18a4-418d-a072-755fe433b73f`
- **Environment**: `6043171d-fa00-40e8-ade9-7933853fa7b8`
- **Service**: `a03f6883-68b6-4fa4-9fb0-634652ed0a4c` (backend)

If these change, update them in the scripts.

## Common Workflows

### Debugging a Session

```bash
# 1. List recent sessions to find the session ID
./scripts/view-railway-logs.sh --list

# 2. Check for errors in that session
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy --errors

# 3. View full logs if needed
./scripts/view-railway-logs.sh session_1762006306800_95vwu1ldy 500
```

### Live Monitoring

For real-time log following (like `tail -f`):

```bash
# SSH into Railway
./scripts/railway-ssh.sh

# Then inside the container:
tail -f /var/log/voice-agents/session_XXXXX.log
```

### Quick Health Check

```bash
# View the latest session to see if things are working
./scripts/view-railway-logs.sh --latest
```

## Troubleshooting

### "railway: command not found"

Install the Railway CLI:
```bash
npm install -g @railway/cli
```

### "Permission denied"

Make scripts executable:
```bash
chmod +x scripts/*.sh
```

### "No logs found"

The session ID might be wrong or the session hasn't generated logs yet. List available sessions:
```bash
./scripts/view-railway-logs.sh --list
```

## Adding to Makefile (Optional)

You can add these to your Makefile for easier access:

```makefile
# Railway helpers
.PHONY: railway-ssh railway-logs railway-logs-latest

railway-ssh:
	@./scripts/railway-ssh.sh

railway-logs:
	@./scripts/view-railway-logs.sh $(SESSION)

railway-logs-latest:
	@./scripts/view-railway-logs.sh --latest
```

Then use:
```bash
make railway-ssh
make railway-logs-latest
make railway-logs SESSION=session_1762006306800_95vwu1ldy
```
