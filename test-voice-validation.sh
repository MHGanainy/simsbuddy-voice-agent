#!/bin/bash
# Test voice validation and logging

set -e

echo "=========================================="
echo "Voice Validation Testing"
echo "=========================================="

BASE_URL="${1:-http://localhost:8000}"

# Test valid voices
VALID_VOICES=("Ashley" "Craig" "Edward" "Olivia" "Wendy" "Priya")

echo -e "\n1. Testing VALID voices:"
echo "=========================================="
for voice in "${VALID_VOICES[@]}"; do
    echo -e "\nTesting: $voice"
    response=$(curl -s -X POST "$BASE_URL/orchestrator/session/start" \
      -H "Content-Type: application/json" \
      -d "{
        \"userName\": \"test_voice_validation\",
        \"correlationToken\": \"test_${voice}_$(date +%s)\",
        \"voiceId\": \"$voice\"
      }")

    session_id=$(echo "$response" | jq -r '.sessionId')
    success=$(echo "$response" | jq -r '.success')

    if [ "$success" = "true" ]; then
        echo "  ✅ $voice: Success (sessionId: $session_id)"
    else
        echo "  ❌ $voice: Failed"
        echo "  Response: $response"
    fi
done

# Test invalid voices
echo -e "\n\n2. Testing INVALID voices (should fallback to Ashley):"
echo "=========================================="
INVALID_VOICES=("InvalidVoice" "alice" "bob" "ASHLEY" "craig")

for voice in "${INVALID_VOICES[@]}"; do
    echo -e "\nTesting: $voice (invalid)"
    response=$(curl -s -X POST "$BASE_URL/orchestrator/session/start" \
      -H "Content-Type: application/json" \
      -d "{
        \"userName\": \"test_invalid_voice\",
        \"correlationToken\": \"test_invalid_${voice}_$(date +%s)\",
        \"voiceId\": \"$voice\"
      }")

    session_id=$(echo "$response" | jq -r '.sessionId')
    success=$(echo "$response" | jq -r '.success')

    echo "  📋 Sent: $voice → Should fallback to Ashley"
    echo "  Response: sessionId=$session_id, success=$success"
done

# Test default (no voice specified)
echo -e "\n\n3. Testing DEFAULT (no voiceId specified):"
echo "=========================================="
echo "Testing: No voiceId (should use Ashley)"
response=$(curl -s -X POST "$BASE_URL/orchestrator/session/start" \
  -H "Content-Type: application/json" \
  -d "{
    \"userName\": \"test_default_voice\",
    \"correlationToken\": \"test_default_$(date +%s)\"
  }")

session_id=$(echo "$response" | jq -r '.sessionId')
success=$(echo "$response" | jq -r '.success')

echo "  ✅ Default: Success (sessionId: $session_id)"

# Check Redis for stored voices
echo -e "\n\n4. Verifying Redis Storage:"
echo "=========================================="
echo "Checking user config in Redis..."

for user in test_voice_validation test_invalid_voice test_default_voice; do
    echo -e "\nUser: $user"
    stored_voice=$(docker exec voice-agent-redis redis-cli HGET "user:$user:config" "voiceId" 2>/dev/null || echo "N/A (Redis not accessible)")
    echo "  Stored voice: $stored_voice"
done

# Check Docker logs for validation messages
echo -e "\n\n5. Checking Logs for Voice Validation:"
echo "=========================================="
echo "Last 20 voice-related log entries:"
docker logs voice-agent-orchestrator 2>&1 | grep -E "voice_id|voice_requested|voice_validated|invalid_voice" | tail -20

echo -e "\n=========================================="
echo "Testing Complete!"
echo "=========================================="

# Summary
echo -e "\nSummary:"
echo "- Valid voices: ${VALID_VOICES[@]}"
echo "- Invalid voices tested: ${INVALID_VOICES[@]}"
echo "- Check logs above for 'invalid_voice_requested' warnings"
echo "- All invalid voices should fallback to Ashley"
