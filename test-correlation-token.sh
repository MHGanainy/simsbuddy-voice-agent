#!/bin/bash
# Test correlation token acceptance

echo "=========================================="
echo "Testing Correlation Token Feature"
echo "=========================================="

# Test 1: With correlation token
echo -e "\n1. Testing WITH correlation token (sim_abc123_1234567890):"
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "test_user",
    "correlationToken": "sim_abc123_1234567890",
    "voiceId": "Ashley"
  }' | jq

echo -e "\n=========================================="

# Test 2: Without correlation token (should auto-generate)
echo -e "\n2. Testing WITHOUT correlation token (should auto-generate):"
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "test_user2",
    "voiceId": "Craig"
  }' | jq

echo -e "\n=========================================="

# Test 3: Custom correlation format
echo -e "\n3. Testing custom format (call_12345_xyz):"
curl -X POST http://localhost:8000/orchestrator/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userName": "test_user3",
    "correlationToken": "call_12345_xyz",
    "voiceId": "Olivia"
  }' | jq

echo -e "\n=========================================="
echo "Tests completed!"
