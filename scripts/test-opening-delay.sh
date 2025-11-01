#!/bin/bash

# This script tests the opening line delay and captures timing data

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== Opening Line Delay Test ===${NC}"
echo ""

# Set orchestrator URL
ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:8000"}

# Check if LOG_LEVEL=DEBUG is set in docker-compose.yml
echo -e "${YELLOW}Checking LOG_LEVEL configuration...${NC}"
if ! docker exec voice-agent-orchestrator printenv LOG_LEVEL 2>/dev/null | grep -q "DEBUG"; then
    echo -e "${RED}⚠️  WARNING: LOG_LEVEL is not set to DEBUG${NC}"
    echo "To enable timing instrumentation, add to docker-compose.yml under orchestrator service:"
    echo "  environment:"
    echo "    - LOG_LEVEL=DEBUG"
    echo ""
    echo "Or add to .env file:"
    echo "  LOG_LEVEL=DEBUG"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓ LOG_LEVEL=DEBUG is set${NC}"
fi
echo ""

# Start a session
echo -e "${YELLOW}Starting test session...${NC}"
START_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")

RESPONSE=$(curl -s -X POST "$ORCHESTRATOR_URL/orchestrator/session/start" \
  -H "Content-Type: application/json" \
  -d '{"userName":"timing_test","voiceId":"Ashley","openingLine":"Testing greeting delay"}')

SESSION_ID=$(echo "$RESPONSE" | jq -r '.sessionId')
echo -e "${GREEN}Session started:${NC} $SESSION_ID"

# Wait for agent to spawn and connect
echo -e "${YELLOW}Waiting for agent to spawn and connect...${NC}"
sleep 5

# Get the log file path from the orchestrator logs
LOG_FILE="/var/log/voice-agents/${SESSION_ID}.log"
echo "Agent log file: $LOG_FILE"

# Wait for greeting to be spoken
echo -e "${YELLOW}Waiting for greeting...${NC}"
sleep 5

END_TIME=$(python3 -c "import time; print(int(time.time() * 1000))")

# Extract the agent logs
echo -e "${YELLOW}Extracting agent logs...${NC}"
docker exec voice-agent-orchestrator cat "$LOG_FILE" 2>/dev/null > /tmp/agent_log.txt || {
    echo -e "${RED}Failed to read agent log file${NC}"
    exit 1
}

# End the session
echo -e "${YELLOW}Ending session...${NC}"
curl -s -X POST "$ORCHESTRATOR_URL/orchestrator/session/end" \
  -H "Content-Type: application/json" \
  -d "{\"sessionId\":\"$SESSION_ID\"}" > /dev/null

# Analyze the timing logs
echo ""
echo -e "${BLUE}=== Timing Analysis ===${NC}"

# Extract timing data
if [ -f /tmp/agent_log.txt ]; then
    # Check for timing events
    if grep -q "TIMING:" /tmp/agent_log.txt; then
        echo -e "${GREEN}✓ Found TIMING logs${NC}"
        echo ""
        echo "Captured timing events:"
        grep "TIMING:" /tmp/agent_log.txt
        echo ""
    else
        echo -e "${YELLOW}⚠️  No TIMING logs found. LOG_LEVEL=DEBUG may not be enabled.${NC}"
        echo ""
    fi

    # Parse specific timing values
    echo -e "${BLUE}=== Breakdown ===${NC}"

    # Check for main events
    if grep -q "participant_joined" /tmp/agent_log.txt; then
        echo "✓ Participant joined event fired"
    fi

    if grep -q "opening_line_sent" /tmp/agent_log.txt; then
        echo "✓ Opening line sent"
    fi

    # Extract timing values
    REDIS_TIME=$(grep "TIMING: redis_operation_complete" /tmp/agent_log.txt | grep -oE "duration_ms=[0-9.]+" | cut -d= -f2 | head -1)
    SLEEP_TIME=$(grep "TIMING: sleep_complete" /tmp/agent_log.txt | grep -oE "duration_ms=[0-9.]+" | cut -d= -f2 | head -1)
    QUEUE_TIME=$(grep "TIMING: opening_line_queued" /tmp/agent_log.txt | grep -oE "queue_duration_ms=[0-9.]+" | cut -d= -f2 | head -1)
    HANDLER_TIME=$(grep "TIMING: opening_line_queued" /tmp/agent_log.txt | grep -oE "total_handler_duration_ms=[0-9.]+" | cut -d= -f2 | head -1)

    echo ""
    echo "Event Handler Breakdown:"
    [ -n "$REDIS_TIME" ] && echo "  Redis operation: ${REDIS_TIME}ms"
    [ -n "$SLEEP_TIME" ] && echo "  Sleep delay: ${SLEEP_TIME}ms (reduced from 1000ms)"
    [ -n "$QUEUE_TIME" ] && echo "  Queue frame: ${QUEUE_TIME}ms"
    [ -n "$HANDLER_TIME" ] && echo "  Total handler: ${HANDLER_TIME}ms"

    # Calculate total session time
    TOTAL_TIME=$((END_TIME - START_TIME))
    echo ""
    echo "Total test duration: ${TOTAL_TIME}ms"

    # Check if we need to look elsewhere for delays
    if [ -n "$HANDLER_TIME" ]; then
        HANDLER_MS=$(echo "$HANDLER_TIME" | cut -d. -f1)
        if [ "$HANDLER_MS" -lt "500" ]; then
            echo ""
            echo -e "${YELLOW}⚠️  Handler only took ${HANDLER_TIME}ms but total duration is ${TOTAL_TIME}ms${NC}"
            echo -e "${YELLOW}The delay might be in:${NC}"
            echo "  1. Between session start and participant joined event"
            echo "  2. In the TTS processing pipeline"
            echo "  3. In the WebRTC/LiveKit connection establishment"
            echo "  4. In agent spawn time (check startup_time_seconds in logs above)"
        fi
    fi
else
    echo -e "${YELLOW}No agent logs found.${NC}"
fi

# Cleanup
rm -f /tmp/agent_log.txt

echo ""
echo -e "${GREEN}Test complete!${NC}"
