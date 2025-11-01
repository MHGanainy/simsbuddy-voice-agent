#!/bin/bash

# View local agent logs for a specific session
# Usage: ./scripts/view-local-logs.sh [session_id] [lines]

set -e

# Configuration
CONTAINER_NAME="voice-agent-orchestrator"
LOG_DIR="/var/log/voice-agents"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
SESSION_ID="${1}"
LINES="${2:-100}"

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}Error: Container ${CONTAINER_NAME} is not running${NC}"
    echo "Start it with: docker-compose up -d"
    exit 1
fi

# Function to list available sessions
list_sessions() {
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}Available Session Logs${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "ls -lht $LOG_DIR 2>/dev/null | head -20" || {
        echo -e "${YELLOW}No log files found yet${NC}"
    }
}

# Function to view specific session logs
view_session_logs() {
    local session_id=$1
    local num_lines=$2

    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}Session: $session_id${NC}"
    echo -e "${GREEN}Last $num_lines lines${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" tail -"$num_lines" "$LOG_DIR/$session_id.log" 2>/dev/null || {
        echo -e "${RED}Error: Log file not found${NC}"
        echo "Available sessions:"
        list_sessions
        exit 1
    }
}

# Function to grep logs for errors
grep_errors() {
    local session_id=$1

    echo -e "${RED}════════════════════════════════════════${NC}"
    echo -e "${RED}Errors in Session: $session_id${NC}"
    echo -e "${RED}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "grep -i 'error\|exception\|warning' $LOG_DIR/$session_id.log 2>/dev/null || echo 'No errors found'"
}

# Function to view timing logs
grep_timing() {
    local session_id=$1

    echo -e "${CYAN}════════════════════════════════════════${NC}"
    echo -e "${CYAN}Timing Data for Session: $session_id${NC}"
    echo -e "${CYAN}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "grep 'TIMING:' $LOG_DIR/$session_id.log 2>/dev/null || echo 'No timing data found (LOG_LEVEL=DEBUG required)'"

    echo ""
    echo -e "${CYAN}════════════════════════════════════════${NC}"
    echo -e "${CYAN}Key Events${NC}"
    echo -e "${CYAN}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "grep -E 'participant_joined|opening_line_sent' $LOG_DIR/$session_id.log 2>/dev/null || echo 'No key events found'"
}

# Function to view latest session
view_latest() {
    local num_lines=$1

    echo -e "${YELLOW}════════════════════════════════════════${NC}"
    echo -e "${YELLOW}Latest Session Logs (last $num_lines lines)${NC}"
    echo -e "${YELLOW}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "LATEST=\$(ls -t $LOG_DIR/*.log 2>/dev/null | head -1); if [ -n \"\$LATEST\" ]; then echo \"File: \$LATEST\"; echo ''; tail -$num_lines \"\$LATEST\"; else echo 'No logs found'; fi"
}

# Function to follow logs (tail -f)
follow_logs() {
    local session_id=$1

    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}Following Session: $session_id${NC}"
    echo -e "${GREEN}Press Ctrl+C to stop${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" tail -f "$LOG_DIR/$session_id.log" 2>/dev/null || {
        echo -e "${RED}Error: Log file not found${NC}"
        echo "Available sessions:"
        list_sessions
        exit 1
    }
}

# Function to search logs
search_logs() {
    local session_id=$1
    local pattern=$2

    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}Search Results for: $pattern${NC}"
    echo -e "${BLUE}Session: $session_id${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"

    docker exec "$CONTAINER_NAME" sh -c "grep -i '$pattern' $LOG_DIR/$session_id.log 2>/dev/null || echo 'No matches found'"
}

# Main logic
if [ -z "$SESSION_ID" ]; then
    echo -e "${YELLOW}Usage: $0 [session_id] [lines|options]${NC}"
    echo ""
    echo -e "${YELLOW}Options:${NC}"
    echo "  [session_id] [number]      View last N lines (default: 100)"
    echo "  [session_id] --errors      Show only errors/warnings"
    echo "  [session_id] --timing      Show timing instrumentation data"
    echo "  [session_id] --follow      Follow logs in real-time (tail -f)"
    echo "  [session_id] --search TEXT Search for specific text"
    echo "  --list                     List all session logs"
    echo "  --latest [number]          View latest session"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  $0 session_1762006306800_95vwu1ldy 100"
    echo "  $0 session_1762006306800_95vwu1ldy --errors"
    echo "  $0 session_1762006306800_95vwu1ldy --timing"
    echo "  $0 session_1762006306800_95vwu1ldy --follow"
    echo "  $0 session_1762006306800_95vwu1ldy --search 'Connected to'"
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
        case "$LINES" in
            --errors)
                grep_errors "$SESSION_ID"
                ;;
            --timing)
                grep_timing "$SESSION_ID"
                ;;
            --follow)
                follow_logs "$SESSION_ID"
                ;;
            --search)
                if [ -z "$3" ]; then
                    echo -e "${RED}Error: --search requires a search pattern${NC}"
                    echo "Usage: $0 $SESSION_ID --search 'pattern'"
                    exit 1
                fi
                search_logs "$SESSION_ID" "$3"
                ;;
            *)
                view_session_logs "$SESSION_ID" "$LINES"
                ;;
        esac
        ;;
esac
