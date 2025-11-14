#!/bin/bash
# Test voice agent with frontend

SESSION_ID=${1:-"test_session_$(date +%s)"}

echo "Starting voice agent test with frontend..."
echo "Session ID: $SESSION_ID"
echo ""

# Start voice agent in background
echo "1. Starting voice agent..."
export TEST_MODE=true
python scripts/test_voice_agent_direct.py --session-id "$SESSION_ID" &
AGENT_PID=$!

echo "   Voice agent PID: $AGENT_PID"
echo ""

# Wait for agent to initialize
echo "2. Waiting for voice agent to initialize (10 seconds)..."
sleep 10

# Start frontend
echo "3. Starting frontend..."
echo "   Opening http://localhost:3000"
echo "   Use session ID: $SESSION_ID"
echo ""
echo "Instructions:"
echo "  1. Frontend will open in browser"
echo "  2. Enter session ID: $SESSION_ID"
echo "  3. Click 'Join Room'"
echo "  4. Speak into your microphone"
echo ""
echo "Press Ctrl+C to stop both services"

cd frontend && npm run dev

# Cleanup on exit
trap "kill $AGENT_PID 2>/dev/null" EXIT
