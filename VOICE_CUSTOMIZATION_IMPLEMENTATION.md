# Voice Customization Implementation Guide

Complete frontend-to-backend flow for Inworld TTS voice selection and opening line customization.

**Status**: ✅ Backend Complete | ⏳ Frontend Pending

**Date**: October 28, 2025

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Backend Implementation](#backend-implementation)
3. [Frontend Implementation](#frontend-implementation)
4. [Testing Guide](#testing-guide)
5. [Deployment](#deployment)

---

## Architecture Overview

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│   React     │          │   Express    │          │   Celery    │
│  Frontend   │◄────────►│     API      │◄────────►│   Worker    │
└─────────────┘          └──────────────┘          └─────────────┘
      │                         │                         │
      │                         │                         │
      ▼                         ▼                         ▼
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│ Voice Picker│          │    Redis     │          │   Python    │
│  Component  │          │  State Store │          │ Voice Agent │
└─────────────┘          └──────────────┘          └─────────────┘
```

### Data Flow

1. **User Configuration**
   - User selects voice + custom opening line in React UI
   - Frontend calls `POST /api/agent/configure`
   - Configuration saved in Redis: `user:{userId}:config`

2. **Session Start**
   - User clicks "Start Call"
   - Frontend calls `POST /api/session/start` with userId
   - Celery task spawns agent with user's voice preferences

3. **Agent Initialization**
   - Celery task fetches configuration from Redis
   - Spawns Python process with `--voice-id` and `--opening-line` arguments
   - Agent joins LiveKit room with customized voice

---

## Backend Implementation

### ✅ Completed Components

#### 1. Voice Catalog Service
**File**: `orchestrator/voices-catalog.js`

- 25+ voice options across 6 languages
- Voice metadata: gender, age, category, tier, tags
- Default opening lines for each voice persona
- Validation functions for voice ID and opening line text

**Key Functions**:
```javascript
getVoiceById(voiceId)
getVoicesByLanguage(languageCode)
validateVoiceId(voiceId, userTier)
validateOpeningLine(text)
getDefaultOpeningLine(voiceId)
```

#### 2. API Endpoints
**File**: `orchestrator/celery-orchestrator.js`

##### GET /api/voices
List all available voices with filtering

**Query Parameters**:
- `language`: Filter by language code (en, es, fr, etc.)
- `category`: Filter by category (professional, educational, character, assistant)
- `tier`: Filter by tier (free, premium, enterprise)

**Response**:
```json
{
  "success": true,
  "voices": [...],
  "groupedVoices": {
    "professional": [...],
    "educational": [...]
  },
  "totalCount": 25,
  "filters": {
    "languages": ["en", "es", "fr", "ko", "zh", "nl"],
    "categories": ["professional", "educational", "character", "assistant"],
    "tiers": ["free", "premium", "enterprise"]
  }
}
```

##### GET /api/voices/:id
Get details for a specific voice

**Response**:
```json
{
  "success": true,
  "voice": {
    "id": "Ashley",
    "name": "Ashley",
    "language": "en",
    "gender": "female",
    "age": "adult",
    "description": "TV Host - Delivers news and podcast introductions",
    "category": "professional",
    "tier": "free",
    "tags": ["news", "podcast", "enthusiastic"]
  },
  "defaultOpeningLine": "Hello! I'm Ashley, your AI assistant...",
  "previewSample": "Hello! This is a sample of my voice..."
}
```

##### POST /api/agent/configure
Save user's voice and opening line preferences

**Request**:
```json
{
  "userId": "user123",
  "voiceId": "Mark",
  "openingLine": "Hey there! Ready to chat about tech?",
  "userTier": "free"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Agent configuration saved",
  "config": {
    "userId": "user123",
    "voiceId": "Mark",
    "openingLine": "Hey there! Ready to chat about tech?",
    "voice": {...}
  }
}
```

**Validation**:
- Voice ID must exist in catalog
- Tier access (free users can't use premium voices)
- Opening line: 5-500 characters
- No unsupported characters (HTML tags, template literals)

##### GET /api/agent/configure/:userId
Get current configuration for a user

**Response**:
```json
{
  "success": true,
  "config": {
    "userId": "user123",
    "voiceId": "Ashley",
    "openingLine": "Hello! I'm Ashley...",
    "voice": {...},
    "updatedAt": 1730139600000,
    "isDefault": false
  }
}
```

##### POST /api/voices/:id/preview
Generate preview audio (placeholder for now)

Currently returns metadata for client-side TTS generation. In production, this would call Inworld TTS API to generate actual audio preview.

#### 3. Python Voice Agent
**File**: `voice_assistant.py`

**New Command-Line Arguments**:
```bash
python3 voice_assistant.py \
  --room session123 \
  --voice-id Mark \
  --opening-line "Hey! I'm Mark, your tech-savvy AI assistant"
```

**Changes**:
- Added argparse for `--voice-id` and `--opening-line`
- Updated `InworldTTSService` to use voice_id parameter
- Dynamic opening line in `on_first_participant_joined` event handler
- Fallback to auto-generated greeting if no custom line provided

#### 4. Celery Task Integration
**File**: `orchestrator/tasks.py`

**Updated `spawn_voice_agent` Task**:
```python
def spawn_voice_agent(self, session_id, user_id=None, prewarm=False):
    # Fetch user configuration from Redis
    voice_id = 'Ashley'  # Default
    opening_line = None

    if user_id:
        config = redis_client.hgetall(f'user:{user_id}:config')
        if config:
            voice_id = config['voiceId']
            opening_line = config['openingLine']

    # Build command with voice customization
    cmd = ['python3', PYTHON_SCRIPT_PATH, '--room', session_id,
           '--voice-id', voice_id]
    if opening_line:
        cmd.extend(['--opening-line', opening_line])

    # Spawn process
    process = subprocess.Popen(cmd, ...)
```

**Redis Schema**:
```
user:{userId}:config {
  voiceId: "Mark",
  openingLine: "Hey there! Ready to chat?",
  updatedAt: 1730139600000
}

session:{sessionId} {
  status: "ready",
  userId: "user123",
  voiceId: "Mark",
  agentPid: 1234,
  createdAt: 1730139600000
}
```

---

## Frontend Implementation

### ⏳ Pending Components

#### 1. Voice Picker Component

**File**: `livekit-react-app/src/components/VoicePicker.tsx`

**Features**:
- Grid/list view of available voices
- Filter by language, category, tier
- Voice preview audio playback
- Visual indicator for current selection
- Tier badge (free/premium/enterprise)

**Component Structure**:
```tsx
<VoicePicker
  selectedVoiceId={voiceId}
  onVoiceSelect={(voice) => setVoiceId(voice.id)}
  userTier="free"
  showPreviews={true}
/>
```

#### 2. Opening Line Customization Component

**File**: `livekit-react-app/src/components/OpeningLineEditor.tsx`

**Features**:
- Text input with character counter (5-500 chars)
- Real-time validation
- Preview button to test TTS
- Reset to default button
- Suggested templates for selected voice

**Component Structure**:
```tsx
<OpeningLineEditor
  voiceId={voiceId}
  value={openingLine}
  onChange={(text) => setOpeningLine(text)}
  onPreview={async (text) => {
    // Play TTS preview
  }}
/>
```

#### 3. Configuration Manager Hook

**File**: `livekit-react-app/src/hooks/useVoiceConfig.ts`

**API**:
```typescript
const {
  config,
  voices,
  isLoading,
  updateConfig,
  fetchVoices,
  previewVoice
} = useVoiceConfig(userId);

// Update configuration
await updateConfig({
  voiceId: 'Mark',
  openingLine: 'Hey there!'
});

// Fetch available voices
const voices = await fetchVoices({
  language: 'en',
  category: 'professional'
});
```

#### 4. State Management

**File**: `livekit-react-app/src/store/voiceConfigSlice.ts` (if using Redux)

Or use React Context:

**File**: `livekit-react-app/src/contexts/VoiceConfigContext.tsx`

**State**:
```typescript
interface VoiceConfigState {
  userId: string | null;
  config: {
    voiceId: string;
    openingLine: string;
    voice: Voice;
  };
  availableVoices: Voice[];
  filters: {
    language: string;
    category: string;
    tier: string;
  };
}
```

---

## Testing Guide

### Backend Testing

#### 1. Test Voice Catalog
```bash
# List all voices
curl http://localhost:8080/api/voices | jq

# Filter by category
curl "http://localhost:8080/api/voices?category=professional" | jq

# Get specific voice
curl http://localhost:8080/api/voices/Mark | jq
```

#### 2. Test Configuration API
```bash
# Save configuration
curl -X POST http://localhost:8080/api/agent/configure \
  -H "Content-Type: application/json" \
  -d '{
    "userId": "test_user",
    "voiceId": "Mark",
    "openingLine": "Hey! Ready to chat about tech?"
  }' | jq

# Get configuration
curl http://localhost:8080/api/agent/configure/test_user | jq
```

#### 3. Test Agent Spawn with Voice Customization
```bash
# Start session (will use saved configuration)
curl -X POST http://localhost:8080/api/session/start \
  -H "Content-Type: application/json" \
  -d '{
    "userId": "test_user",
    "roomName": "test-room-123"
  }' | jq

# Check session status
curl http://localhost:8080/api/session/{sessionId} | jq
```

#### 4. Manual Agent Test
```bash
# Test voice agent directly
python3 voice-assistant-project/voice_assistant.py \
  --room test-room \
  --voice-id Mark \
  --opening-line "Hey there! Let's talk tech!"
```

### Frontend Testing (Once Implemented)

#### 1. Voice Picker Component
```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import VoicePicker from './VoicePicker';

test('renders voice options', async () => {
  render(<VoicePicker onVoiceSelect={jest.fn()} />);
  expect(await screen.findByText('Ashley')).toBeInTheDocument();
  expect(await screen.findByText('Mark')).toBeInTheDocument();
});

test('filters voices by category', async () => {
  render(<VoicePicker onVoiceSelect={jest.fn()} />);
  fireEvent.click(screen.getByText('Professional'));
  // Assert filtered results
});
```

#### 2. Opening Line Editor Component
```typescript
test('validates opening line length', () => {
  const onChange = jest.fn();
  render(<OpeningLineEditor onChange={onChange} />);

  const input = screen.getByPlaceholderText('Enter opening line');
  fireEvent.change(input, { target: { value: 'Hi' } });

  expect(screen.getByText(/must be at least 5 characters/i)).toBeInTheDocument();
});
```

#### 3. Integration Test
```typescript
test('complete voice configuration flow', async () => {
  const user = userEvent.setup();

  render(<VoiceConfigPage userId="test_user" />);

  // Select voice
  await user.click(screen.getByText('Mark'));

  // Enter opening line
  const input = screen.getByPlaceholderText('Opening line');
  await user.type(input, 'Hey! Ready to chat about tech?');

  // Save
  await user.click(screen.getByText('Save Configuration'));

  // Verify API call
  expect(mockFetch).toHaveBeenCalledWith(
    '/api/agent/configure',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        userId: 'test_user',
        voiceId: 'Mark',
        openingLine: 'Hey! Ready to chat about tech?'
      })
    })
  );
});
```

---

## Deployment

### Environment Variables

**Backend (.env)**:
```bash
# Existing variables
LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
GROQ_API_KEY=...
ASSEMBLY_API_KEY=...
INWORLD_API_KEY=...

# Voice customization (no new variables needed)
# Configuration is stored in Redis
```

**Frontend (.env)**:
```bash
VITE_API_URL=http://localhost:8080
VITE_LIVEKIT_URL=wss://simsbuddy-mdszuvzz.livekit.cloud
```

### Docker Deployment

The voice customization system works with existing `docker-compose.celery.yml`:

```bash
# Rebuild containers with updated code
docker-compose -f docker-compose.celery.yml down
docker-compose -f docker-compose.celery.yml up --build -d

# Verify API endpoints
curl http://localhost:8080/api/voices | jq
curl http://localhost:8080/api/health | jq
```

### Railway Deployment

No additional services required. The voice customization system uses:
- ✅ Existing Redis service (for configuration storage)
- ✅ Existing Express API (new endpoints added)
- ✅ Existing Celery workers (updated to fetch config)
- ✅ Existing Python agents (new CLI args added)

---

## Voice Catalog

### English Voices

**Professional/News**:
- Ashley (TV Host) - Female, Adult, Free
- Mark (TV Host) - Male, Adult, Free
- Deborah (News Anchor) - Female, Adult, Free

**Educational**:
- Alex (Teacher) - Male, Adult, Free
- Olivia (Teacher) - Female, Adult, Free
- Edward (Instructor) - Male, Adult, Free

**Character/Narrative**:
- Sarah (Adventurer) - Female, Adult, Premium
- Hades (Dark Character) - Male, Adult, Premium
- Theodore (Detective) - Male, Adult, Premium
- Julia (Friend) - Female, Adult, Free
- Wendy (Critic) - Female, Adult, Premium

**Service/Assistant**:
- Elizabeth (Assistant) - Female, Adult, Free
- Timothy (Customer Service) - Male, Teen, Free

### Multilingual Voices

**Chinese (Mandarin)**:
- Jing (Assistant) - Female, Free
- Xinyi (News Anchor) - Female, Free
- Yichen (Storyteller) - Male, Premium

**Spanish**:
- Diego (Customer Service) - Male, Free
- Lupita (Friend) - Female, Free
- Miguel (Host) - Male, Free

**French**:
- Hélène (Friend) - Female, Free
- Mathieu (Host) - Male, Free

**Korean**:
- Hyunwoo (Host) - Male, Free
- Yoona (Customer Service) - Female, Free

**Dutch**:
- Lore (Customer Service) - Female, Free

---

## Next Steps

### Frontend Implementation

1. ✅ **Create React Components** (Estimated: 2-3 hours)
   - VoicePicker component with grid/list view
   - OpeningLineEditor component with validation
   - VoicePreview component for audio playback

2. ✅ **State Management** (Estimated: 1 hour)
   - useVoiceConfig custom hook
   - API integration functions
   - Configuration persistence

3. ✅ **UI/UX Polish** (Estimated: 1-2 hours)
   - Voice category filtering
   - Audio preview playback
   - Character counter
   - Tier badges (Free/Premium/Enterprise)

4. ✅ **Testing** (Estimated: 2 hours)
   - Unit tests for components
   - Integration tests for API calls
   - E2E test for complete flow

### Future Enhancements

- **Voice Cloning**: Integration with Inworld's zero-shot voice cloning
- **Preview Audio Generation**: Real server-side TTS preview generation
- **WebSocket Updates**: Live updates when voice config changes
- **Voice Analytics**: Track which voices are most popular
- **A/B Testing**: Test different opening lines for conversion optimization
- **Multi-language Support**: Automatic language detection from user profile

---

## API Reference Quick Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/voices` | GET | List all voices (with filters) |
| `/api/voices/:id` | GET | Get voice details |
| `/api/agent/configure` | POST | Save user configuration |
| `/api/agent/configure/:userId` | GET | Get user configuration |
| `/api/voices/:id/preview` | POST | Generate voice preview |

---

## Success Metrics

- ✅ 25+ voice options available
- ✅ Configuration persistence in Redis
- ✅ Tier-based access control
- ✅ Real-time validation
- ✅ Command-line argument passing to Python agents
- ✅ Backward compatible (defaults to Ashley if no config)

---

## Support & Troubleshooting

### Common Issues

**Issue**: Voice not changing in active session
**Solution**: Voice is set when agent spawns. Need to restart session for changes to take effect.

**Issue**: Premium voice not working for free user
**Solution**: Check tier validation. Upgrade user tier or select free voice.

**Issue**: Opening line not speaking
**Solution**: Verify opening line is 5-500 characters and doesn't contain unsupported characters.

**Issue**: Configuration not persisting
**Solution**: Check Redis connection. Verify `user:{userId}:config` key exists.

### Debug Commands

```bash
# Check Redis for user config
docker exec voice-agent-redis redis-cli GET "user:test_user:config"

# Check session voice assignment
docker exec voice-agent-redis redis-cli HGETALL "session:session123"

# Check Celery task logs
docker logs voice-agent-orchestrator | grep "voice="

# Test voice argument directly
docker exec voice-agent-orchestrator python3 /app/voice-assistant-project/voice_assistant.py --voice-id Mark --room test
```

---

**Implementation Status**:
- ✅ Backend: 100% Complete
- ⏳ Frontend: 0% Complete (Ready to start)

**Total Estimated Time for Frontend**: 6-8 hours
