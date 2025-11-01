#!/bin/bash

# View Railway agent logs for a specific session
# Usage: ./scripts/view-railway-logs.sh [session_id] [lines]

set -e

# Configuration
PROJECT_ID="eeadd330-18a4-418d-a072-755fe433b73f"
ENV_ID="6043171d-fa00-40e8-ade9-7933853fa7b8"
SERVICE_ID="a03f6883-68b6-4fa4-9fb0-634652ed0a4c"
LOG_DIR="/var/log/voice-agents"

# Railway CLI options
RAILWAY_OPTS="--project $PROJECT_ID --environment $ENV_ID --service $SERVICE_ID"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
SESSION_ID="${1}"
LINES="${2:-100}"

# Function to list available sessions
list_sessions() {
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}Available Session Logs${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"

    railway ssh $RAILWAY_OPTS sh -c "ls -lht $LOG_DIR | head -20"
}

# Function to view specific session logs
view_session_logs() {
    local session_id=$1
    local num_lines=$2

    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}Session: $session_id${NC}"
    echo -e "${GREEN}Last $num_lines lines${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}\n"

    railway ssh $RAILWAY_OPTS tail -$num_lines "$LOG_DIR/$session_id.log"
}

# Function to grep logs for errors
grep_errors() {
    local session_id=$1

    echo -e "${RED}════════════════════════════════════════${NC}"
    echo -e "${RED}Errors in Session: $session_id${NC}"
    echo -e "${RED}════════════════════════════════════════${NC}\n"

    railway ssh $RAILWAY_OPTS sh -c "grep -i 'error\|exception\|warning' $LOG_DIR/$session_id.log || echo 'No errors found'"
}

# Function to view latest session
view_latest() {
    local num_lines=$1

    echo -e "${YELLOW}════════════════════════════════════════${NC}"
    echo -e "${YELLOW}Latest Session Logs (last $num_lines lines)${NC}"
    echo -e "${YELLOW}════════════════════════════════════════${NC}\n"

    railway ssh $RAILWAY_OPTS sh -c "LATEST=\$(ls -t $LOG_DIR/*.log 2>/dev/null | head -1); if [ -n \"\$LATEST\" ]; then echo \"File: \$LATEST\"; tail -$num_lines \"\$LATEST\"; else echo 'No logs found'; fi"
}

# Function to follow logs (tail -f)
follow_logs() {
    local session_id=$1

    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}Following Session: $session_id${NC}"
    echo -e "${GREEN}Press Ctrl+C to stop${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}\n"

    # Note: tail -f doesn't work well with railway run, use SSH instead
    echo -e "${YELLOW}For live tail, use SSH:${NC}"
    echo "railway ssh --project=$PROJECT_ID --environment=$ENV_ID --service=$SERVICE_ID"
    echo -e "${YELLOW}Then run:${NC} tail -f $LOG_DIR/$session_id.log"
}

# Main logic
if [ -z "$SESSION_ID" ]; then
    echo -e "${YELLOW}Usage: $0 [session_id] [lines]${NC}"
    echo -e "${YELLOW}   OR: $0 --list          ${NC}# List all sessions"
    echo -e "${YELLOW}   OR: $0 --latest [lines]${NC}# View latest session"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  $0 session_1762006306800_95vwu1ldy 100"
    echo "  $0 session_1762006306800_95vwu1ldy --errors"
    echo "  $0 --list"
    echo "  $0 --latest 50"
    echo ""
    echo -e "${BLUE}Listing available sessions...${NC}\n"
    list_sessions
    exit 0
fi

# Handle flags
case "$SESSION_ID" in
    --list)
        list_sessions
        ;;
    --latest)
        view_latest "$LINES"
        ;;
    *)
        if [ "$LINES" == "--errors" ]; then
            grep_errors "$SESSION_ID"
        else
            view_session_logs "$SESSION_ID" "$LINES"
        fi
        ;;
esac
