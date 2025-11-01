# Changelog

All notable changes to the LiveKit Voice Assistant Platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2025-11-01

### Added

#### 1. Dynamic System Prompts per Session
- Added `systemPrompt` parameter to `/orchestrator/session/start` API endpoint
- Allows customization of LLM behavior and personality per session
- Stored in Redis (`user:{userName}:config` and `session:{sessionId}`)
- Passed to voice agent via `--system-prompt` command-line argument
- Default: "You are a helpful AI voice assistant."
- **Files Modified:**
  - `backend/orchestrator/main.py` - Request model and Redis storage
  - `backend/orchestrator/tasks.py` - Fetch from Redis and pass to agent
  - `backend/agent/voice_assistant.py` - Accept arg and use in LLM context

**Use Cases:**
- Customer service agents with company-specific instructions
- Technical support specialists with troubleshooting guidelines
- Educational tutors with subject-specific teaching styles
- Sales assistants with product knowledge

**Example:**
```json
{
  "userName": "user123",
  "systemPrompt": "You are a technical support agent for ACME Corp."
}
```

#### 2. Opening Line in Conversation History
- Opening greeting now added to LLM conversation context
- Ensures AI "remembers" what it said when greeting the user
- Implemented by appending opening line to initial messages array
- LLM sees: `[{role: "system"}, {role: "assistant", content: opening_line}]`
- **Files Modified:**
  - `backend/agent/voice_assistant.py:174-179` - Append to initial context

**Benefit:** Users can ask "What did you just say?" and get accurate responses

**Technical Details:**
- Passed via `--opening-line` argument (existing)
- Added to context BEFORE first user utterance
- Maintained throughout conversation by Pipecat's LLMContext

#### 3. Conversation Duration Tracking
- Tracks conversation time from first participant join to session end
- Returns duration in both seconds and minutes (rounded up)
- Stores in Redis for billing integration
- **Files Modified:**
  - `backend/agent/voice_assistant.py` - Track start time on participant join, calculate duration on cleanup
  - `backend/orchestrator/main.py` - Extract duration from Redis and return in `/session/end` response

**Features:**
- `conversationStartTime` stored in Redis when user joins room
- `conversationDuration` (seconds) calculated on session end
- `conversationDurationMinutes` (rounded up with math.ceil) for billing
- Celery can read `conversationStartTime` from Redis every 60s for real-time billing enforcement

**API Response:**
```json
{
  "details": {
    "durationSeconds": 125,
    "durationMinutes": 3
  }
}
```

**Billing Integration:**
- Minutes rounded UP using `math.ceil()` for "1 credit per minute" model
- Duration available in `/orchestrator/session/end` response
- Redis fields enable real-time credit monitoring by Celery tasks

### Changed

- Updated API endpoint paths to use `/orchestrator/` prefix consistently
- Enhanced session cleanup response to include duration metrics
- Improved Redis schema documentation with new fields
- Updated default LLM system prompt to be more generic

### Redis Schema Updates

**New Fields in `user:{userName}:config`:**
- `systemPrompt` - Custom LLM system prompt (optional)

**New Fields in `session:{sessionId}`:**
- `systemPrompt` - Custom LLM system prompt (optional, default: "")
- `conversationStartTime` - Unix timestamp (first participant join)
- `conversationDuration` - Total conversation seconds
- `conversationDurationMinutes` - Rounded up minutes for billing

### Technical Details

**Lines of Code Added:** ~69 lines
**Files Modified:** 3
- `backend/agent/voice_assistant.py` (+35 lines)
- `backend/orchestrator/main.py` (+26 lines)
- `backend/orchestrator/tasks.py` (+8 lines)

**Dependencies Added:**
- `import math` - For ceiling function in duration rounding
- `import time` - For timestamp management
- `import redis` - For direct Redis access in voice agent

**Backward Compatibility:** ✅
- All new parameters are optional
- Existing sessions continue to work without modification
- Default values provided for all new fields

**Error Handling:**
- Redis failures logged, don't crash agent
- Missing system prompt → uses default
- Missing opening line → skips context injection
- Duration tracking errors logged, non-fatal

**Testing:**
- All features tested locally with Docker Compose
- Redis storage verified
- Celery log integration confirmed
- Agent processes spawn successfully with new parameters

### Documentation Updates

- Updated `README.md` with new features section
- Updated `backend/README.md` with implementation details
- Added API endpoint examples for new parameters
- Documented Redis schema changes
- Added billing integration examples

---

## [1.0.0] - 2025-10-XX

### Initial Release

- Full-stack voice assistant platform
- LiveKit WebRTC integration
- Pipecat voice agent framework
- FastAPI + Celery orchestration
- React frontend
- Docker Compose deployment
- Railway deployment support
- Agent pool management
- Session lifecycle management

---

[2.0.0]: https://github.com/your-repo/livekit-demo/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/your-repo/livekit-demo/releases/tag/v1.0.0
