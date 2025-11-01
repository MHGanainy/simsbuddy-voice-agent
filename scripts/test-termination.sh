#!/bin/bash
# Process Group Termination Test Script
# Validates that voice agent processes and their children are properly terminated

set -e

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASS_COUNT=0
FAIL_COUNT=0

# Base URL
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8000}"

# Session ID (global for cleanup)
SESSION_ID=""

# Helper functions
pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Cleanup function
cleanup() {
    if [ -n "$SESSION_ID" ]; then
        info "Cleaning up session: $SESSION_ID"
        curl -s -X POST "$ORCHESTRATOR_URL/orchestrator/session/end" \
            -H "Content-Type: application/json" \
            -d "{\"sessionId\":\"$SESSION_ID\"}" > /dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

# Check dependencies
if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is required but not installed${NC}"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo -e "${RED}Error: jq is required but not installed${NC}"
    exit 1
fi

# Main test
header "Process Group Termination Test"
echo "Testing orchestrator at: $ORCHESTRATOR_URL"

# 1. Start a session
header "Step 1: Starting Test Session"
info "Sending session start request..."

RESPONSE=$(curl -s -X POST "$ORCHESTRATOR_URL/orchestrator/session/start" \
    -H "Content-Type: application/json" \
    -d '{"userName":"test-user","voiceId":"Ashley"}' 2>&1)

if [ $? -ne 0 ]; then
    fail "Failed to start session (curl error)"
    echo "Error: $RESPONSE"
    exit 1
fi

# Parse session ID
SESSION_ID=$(echo "$RESPONSE" | jq -r '.sessionId // empty' 2>/dev/null)

if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    fail "Failed to parse session ID from response"
    echo "Response: $RESPONSE"
    exit 1
fi

pass "Session started: $SESSION_ID"

# Extract token and other info
TOKEN=$(echo "$RESPONSE" | jq -r '.token // empty')
ROOM_NAME=$(echo "$RESPONSE" | jq -r '.roomName // empty')
info "Room: $ROOM_NAME"

# 2. Wait for agent to start
header "Step 2: Waiting for Agent to Start"
info "Waiting 5 seconds for agent to fully initialize..."
sleep 5

# 3. Call debug endpoint to verify process
header "Step 3: Verifying Process Group Setup"
info "Calling debug endpoint..."

DEBUG_RESPONSE=$(curl -s "$ORCHESTRATOR_URL/api/debug/session/$SESSION_ID/processes" 2>&1)

if [ $? -ne 0 ]; then
    fail "Failed to call debug endpoint (curl error)"
    echo "Error: $DEBUG_RESPONSE"
    exit 1
fi

# Check if session found
ERROR=$(echo "$DEBUG_RESPONSE" | jq -r '.detail // empty' 2>/dev/null)
if [ -n "$ERROR" ]; then
    fail "Debug endpoint error: $ERROR"
    exit 1
fi

# Extract values
PID=$(echo "$DEBUG_RESPONSE" | jq -r '.pid // 0')
PGID=$(echo "$DEBUG_RESPONSE" | jq -r '.pgid // 0')
IS_GROUP_LEADER=$(echo "$DEBUG_RESPONSE" | jq -r '.is_group_leader // false')
IS_PROCESS_ALIVE=$(echo "$DEBUG_RESPONSE" | jq -r '.is_process_alive // false')
IS_GROUP_ALIVE=$(echo "$DEBUG_RESPONSE" | jq -r '.is_group_alive // false')
CHILD_COUNT=$(echo "$DEBUG_RESPONSE" | jq -r '.child_processes | length')

info "PID: $PID, PGID: $PGID"

# Verify process is alive
if [ "$IS_PROCESS_ALIVE" = "true" ]; then
    pass "Process is alive (PID: $PID)"
else
    fail "Process is NOT alive (expected to be running)"
    echo "Debug response: $DEBUG_RESPONSE"
fi

# Verify process is group leader
if [ "$IS_GROUP_LEADER" = "true" ]; then
    pass "Process is group leader (PID == PGID: $PID)"
else
    fail "Process is NOT group leader (PID: $PID, PGID: $PGID)"
fi

# Verify process group is alive
if [ "$IS_GROUP_ALIVE" = "true" ]; then
    pass "Process group is alive"
else
    fail "Process group is NOT alive (expected to be running)"
fi

# Show child processes
if [ "$CHILD_COUNT" -gt 0 ]; then
    info "Found $CHILD_COUNT process(es) in the group:"
    echo "$DEBUG_RESPONSE" | jq -r '.child_processes[] | "  - PID \(.pid) (PPID: \(.ppid), PGID: \(.pgid)): \(.cmd)"'
else
    info "No child processes found yet (agent may still be initializing)"
fi

# 4. End the session
header "Step 4: Terminating Session"
info "Sending session end request..."

END_RESPONSE=$(curl -s -X POST "$ORCHESTRATOR_URL/orchestrator/session/end" \
    -H "Content-Type: application/json" \
    -d "{\"sessionId\":\"$SESSION_ID\"}" 2>&1)

if [ $? -ne 0 ]; then
    fail "Failed to end session (curl error)"
    echo "Error: $END_RESPONSE"
    exit 1
fi

SUCCESS=$(echo "$END_RESPONSE" | jq -r '.success // false')
MESSAGE=$(echo "$END_RESPONSE" | jq -r '.message // "No message"')

if [ "$SUCCESS" = "true" ]; then
    pass "Session end request accepted"
    info "Message: $MESSAGE"
else
    fail "Session end request failed"
    echo "Response: $END_RESPONSE"
fi

# 5. Wait for cleanup
info "Waiting 3 seconds for cleanup to complete..."
sleep 3

# 6. Verify cleanup
header "Step 5: Verifying Process Cleanup"

# Call debug endpoint again
DEBUG_RESPONSE_AFTER=$(curl -s -w "\n%{http_code}" "$ORCHESTRATOR_URL/api/debug/session/$SESSION_ID/processes" 2>&1)

# Split response and HTTP code (portable way without head -n-1)
HTTP_CODE=$(echo "$DEBUG_RESPONSE_AFTER" | tail -n1)
DEBUG_BODY=$(echo "$DEBUG_RESPONSE_AFTER" | sed '$d')  # Remove last line

info "HTTP response code: $HTTP_CODE"

if [ "$HTTP_CODE" = "404" ]; then
    pass "Session no longer exists (404 - fully cleaned up)"
else
    # Session still exists in Redis, check if process is dead
    IS_PROCESS_ALIVE_AFTER=$(echo "$DEBUG_BODY" | jq -r '.is_process_alive // "unknown"')
    IS_GROUP_ALIVE_AFTER=$(echo "$DEBUG_BODY" | jq -r '.is_group_alive // "unknown"')

    info "Process alive after cleanup: $IS_PROCESS_ALIVE_AFTER"
    info "Process group alive after cleanup: $IS_GROUP_ALIVE_AFTER"

    if [ "$IS_PROCESS_ALIVE_AFTER" = "false" ]; then
        pass "Process is NOT alive (killed successfully)"
    elif [ "$IS_PROCESS_ALIVE_AFTER" = "true" ]; then
        fail "Process is STILL alive after cleanup!"
    else
        info "Could not determine process status"
    fi

    if [ "$IS_GROUP_ALIVE_AFTER" = "false" ]; then
        pass "Process group is NOT alive (killed successfully)"
    elif [ "$IS_GROUP_ALIVE_AFTER" = "true" ]; then
        fail "Process group is STILL alive after cleanup!"
    else
        info "Could not determine process group status"
    fi
fi

# 7. Check Redis keys (requires docker exec or redis-cli)
header "Step 6: Verifying Redis Cleanup"

REDIS_CHECKED=false

# Try redis-cli first
if command -v redis-cli &> /dev/null; then
    info "Checking Redis using redis-cli..."

    SESSION_EXISTS=$(redis-cli EXISTS "session:$SESSION_ID" 2>/dev/null)
    REDIS_STATUS=$?

    if [ $REDIS_STATUS -eq 0 ]; then
        REDIS_CHECKED=true
        PID_EXISTS=$(redis-cli EXISTS "agent:$SESSION_ID:pid" 2>/dev/null)

        if [ "$SESSION_EXISTS" = "0" ]; then
            pass "Redis key 'session:$SESSION_ID' cleaned up"
        else
            fail "Redis key 'session:$SESSION_ID' still exists"
        fi

        if [ "$PID_EXISTS" = "0" ]; then
            pass "Redis key 'agent:$SESSION_ID:pid' cleaned up"
        else
            fail "Redis key 'agent:$SESSION_ID:pid' still exists"
        fi
    fi
fi

# Try docker exec if redis-cli didn't work
if [ "$REDIS_CHECKED" = false ] && command -v docker &> /dev/null; then
    info "Checking Redis via Docker..."

    # Find Redis container
    REDIS_CONTAINER=$(docker ps --format '{{.Names}}' | grep -i redis | head -n1)

    if [ -n "$REDIS_CONTAINER" ]; then
        info "Using Redis container: $REDIS_CONTAINER"

        SESSION_EXISTS=$(docker exec "$REDIS_CONTAINER" redis-cli EXISTS "session:$SESSION_ID" 2>/dev/null)
        DOCKER_STATUS=$?

        if [ $DOCKER_STATUS -eq 0 ]; then
            REDIS_CHECKED=true
            PID_EXISTS=$(docker exec "$REDIS_CONTAINER" redis-cli EXISTS "agent:$SESSION_ID:pid" 2>/dev/null)

            if [ "$SESSION_EXISTS" = "0" ]; then
                pass "Redis key 'session:$SESSION_ID' cleaned up"
            else
                fail "Redis key 'session:$SESSION_ID' still exists"
            fi

            if [ "$PID_EXISTS" = "0" ]; then
                pass "Redis key 'agent:$SESSION_ID:pid' cleaned up"
            else
                fail "Redis key 'agent:$SESSION_ID:pid' still exists"
            fi
        else
            info "Could not connect to Redis container"
        fi
    else
        info "No Redis container found"
    fi
fi

if [ "$REDIS_CHECKED" = false ]; then
    info "Redis check skipped (redis-cli not available and no docker)"
    info "To enable Redis checks, install redis-cli or ensure Redis container is running"
fi

# Final summary
header "Test Summary"
echo ""
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo "Total checks: $TOTAL"
echo -e "${GREEN}Passed: $PASS_COUNT${NC}"
echo -e "${RED}Failed: $FAIL_COUNT${NC}"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed! Process group termination is working correctly.${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Process group termination may not be working correctly.${NC}"
    exit 1
fi
