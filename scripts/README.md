# Helper Scripts

Utility scripts for Railway deployment debugging.

## Prerequisites

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login
```

## Scripts

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
