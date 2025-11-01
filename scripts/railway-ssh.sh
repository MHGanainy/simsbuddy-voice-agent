#!/bin/bash

# Quick SSH into Railway backend service
# Usage: ./scripts/railway-ssh.sh

PROJECT_ID="eeadd330-18a4-418d-a072-755fe433b73f"
ENV_ID="6043171d-fa00-40e8-ade9-7933853fa7b8"
SERVICE_ID="a03f6883-68b6-4fa4-9fb0-634652ed0a4c"

echo "🚂 Connecting to Railway backend service..."
echo ""
echo "Quick commands once inside:"
echo "  ls -lht /var/log/voice-agents/ | head -10    # List recent sessions"
echo "  tail -100 /var/log/voice-agents/SESSION_ID.log   # View session logs"
echo "  grep -i error /var/log/voice-agents/SESSION_ID.log   # Find errors"
echo ""

railway ssh --project "$PROJECT_ID" --environment "$ENV_ID" --service "$SERVICE_ID"
