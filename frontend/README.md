# Frontend - Voice Agent Development UI

Simple React interface for testing the voice agent.

## Features

- Connect to LiveKit voice agent
- Start/stop voice sessions
- Real-time audio transmission
- Voice selection (6 voices with speed indicators)
- Custom opening line and system prompt inputs
- Real-time structured logs with filters
- Session status display

## Tech Stack

- React 18 + TypeScript
- Vite (build tool)
- LiveKit Components React
- LiveKit Client SDK

## Quick Start

```bash
# Install dependencies
npm install

# Start dev server
npm run dev
```

Access: http://localhost:3000
Backend API: http://localhost:8000 (default)

## Configuration

Set backend URL via environment variable:

```bash
# .env
VITE_API_URL=http://localhost:8000
```

Or in Railway:
```bash
VITE_API_URL=https://your-backend.railway.app
```

## Project Structure

```
frontend/
├── src/
│   ├── main.tsx           # Entry point
│   ├── App.tsx            # Main component (~250 lines)
│   ├── VoiceSettings.tsx  # Voice selector (~95 lines)
│   ├── DevTools.tsx       # Log viewer (~164 lines)
│   ├── logger.ts          # Logging utility (~121 lines)
│   ├── types.ts           # TypeScript types (~30 lines)
│   └── styles.css         # Styles (~400 lines)
├── index.html
├── package.json
└── vite.config.ts
```

## Components

### App.tsx
Main component handling:
- Session lifecycle (start/end)
- LiveKit room connection
- Connection state management
- Error handling

### VoiceSettings.tsx
Voice configuration panel:
- Voice dropdown (6 voices)
- Opening line input
- System prompt input
- Reset button

Available voices:
- Ashley (Default) - Female
- Craig (Fast) - Male
- Edward - Male
- Olivia - Female
- Wendy (Fast) - Female
- Priya (Asian) - Female

### DevTools.tsx
Log viewer panel:
- Real-time log display
- Filter by level (All/Debug/Info/Warn/Error)
- Auto-scroll to latest
- Copy/clear logs
- Session ID display

### logger.ts
Structured logging:
- Color-coded console output
- Session ID correlation
- Event emission for UI updates
- Log storage (last 100 entries)

## Usage

1. **Start Backend**
```bash
# In project root
make dev
```

2. **Start Frontend**
```bash
cd frontend
npm run dev
```

3. **Test**
   - Visit: http://localhost:3000
   - (Optional) Select voice in Voice Settings
   - Click "Start Session"
   - Grant microphone permissions
   - Speak to agent
   - View logs in DevTools
   - Click "End Session"

## Development

### Adding Voices

**Frontend** (`src/VoiceSettings.tsx`):
```typescript
const availableVoices = [
  { id: 'Ashley', name: 'Ashley (Default)' },
  { id: 'YourVoice', name: 'Your Voice Name' },  // Add here
];
```

**Backend** (`backend/agent/voice_assistant.py`):
```python
VOICE_SPEED_OVERRIDES = {
    "Ashley": 1.0,
    "YourVoice": 1.0,  # Add here with desired speed
}
```

### Customizing Logging

Edit `src/logger.ts`:
- Maximum stored logs (default: 100)
- Console colors
- Log event format

### Styling

All styles in `src/styles.css`:
- No CSS modules
- Flat structure
- Easy to modify

## Build for Production

```bash
npm run build
# Output: dist/

npm run preview
```

## Troubleshooting

### Backend Connection Errors

**Issue:** `Failed to fetch`

**Fix:**
- Verify `VITE_API_URL` is set
- Check backend running: `curl http://localhost:8000/health`

### No Audio

**Issue:** Microphone blocked

**Fix:**
- Use HTTPS or localhost
- Check browser microphone permissions
- Ensure no other app using microphone

### Build Errors

**Issue:** TypeScript errors

**Fix:**
```bash
rm -rf node_modules package-lock.json
npm install
```

## Next Steps

- [API Reference](../backend/API.md)
- [Configuration Options](../CONFIGURATION.md)
- [Deployment Guide](../DEPLOYMENT.md)
