# Voice Agent - Frontend

Development interface for the LiveKit voice agent with comprehensive logging.

## Overview

This frontend provides a clean, streamlined interface for testing the voice agent. It focuses on core functionality with comprehensive logging and debugging tools.

## Features

### Core Functionality
- ✅ Connect to LiveKit voice agent
- ✅ Start/stop voice sessions
- ✅ Real-time audio transmission
- ✅ Connection status display
- ✅ Session management

### Voice Customization
- Simple voice selection dropdown (6 Inworld voices with speed optimization)
- Custom opening line input
- Custom system prompt input (for AI personality customization)
- Reset to defaults button

### Logging System
- **Console Logging**: Color-coded logs (debug=gray, info=blue, warn=orange, error=red)
- **UI Display Panel**: Real-time log viewer in DevTools
- **Filtering**: Filter logs by level (All/Debug/Info/Warn/Error)
- **Session Correlation**: All logs tagged with sessionId
- **Actions**: Copy logs, clear logs

## Quick Start

### Prerequisites
- Node.js 18+ and npm
- Backend orchestrator running on port 8000
- LiveKit server configured

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
npm run dev
```

The app will be available at **http://localhost:3000**

### Build for Production

```bash
npm run build
npm run preview
```

## Environment Configuration

The frontend requires one environment variable to connect to the backend:

**`VITE_API_URL`** - URL of the backend orchestrator service

### Local Development

The frontend defaults to `http://localhost:8000` if `VITE_API_URL` is not set.

Optionally create a `.env` file:

```env
VITE_API_URL=http://localhost:8000
```

Or export the variable:

```bash
export VITE_API_URL=http://localhost:8000
npm run dev
```

### Railway/Cloud Deployment

Set `VITE_API_URL` in your platform's environment variables:

```bash
# Railway example
railway variables set VITE_API_URL=https://your-backend.railway.app

# Or in Railway dashboard:
# VITE_API_URL=https://your-backend.railway.app
```

## Architecture

| Metric | Value |
|--------|-------|
| **Lines of Code** | ~670 TS/TSX, ~400 CSS |
| **Dependencies** | 5 runtime deps |
| **Bundle Size** | ~250KB (~80KB gzipped) |

### File Structure

```
frontend/
├── index.html                 # Entry HTML
├── package.json               # Dependencies
├── vite.config.ts             # Vite configuration
├── tsconfig.json              # TypeScript config
└── src/
    ├── main.tsx               # React entry point
    ├── App.tsx                # Main component (~250 lines)
    ├── VoiceSettings.tsx      # Voice customization (~95 lines)
    ├── DevTools.tsx           # Log display panel (~164 lines)
    ├── logger.ts              # Logging utility (~121 lines)
    ├── types.ts               # TypeScript types (~30 lines)
    └── styles.css             # Styling (~400 lines)
```

### Component Hierarchy

```
App
├── Header
│   └── ConnectionStatus
├── Main
│   ├── VoiceSettings (collapsible)
│   │   ├── Voice Dropdown
│   │   └── Opening Line Input
│   └── LiveKitRoom
│       └── RoomContent
│           ├── ConnectionStateIndicator
│           └── End Session Button
└── DevTools (collapsible)
    ├── Log Filters
    ├── Actions (Copy/Clear)
    └── Log Display
```

## Usage

### Starting a Session

1. **(Optional)** Expand Voice Settings panel
2. **(Optional)** Select a voice from the dropdown:
   - Ashley (Default) - Warm, natural female (1.0x speed)
   - Craig (Fast) - Professional male (1.2x speed)
   - Edward - Smooth, natural male (1.0x speed)
   - Olivia - Clear, professional female (1.0x speed)
   - Wendy (Fast) - Energetic female (1.2x speed)
   - Priya (Asian) - Warm, clear female (1.0x speed)
3. **(Optional)** Customize the opening line
4. **(Optional)** Customize the system prompt (AI personality/behavior)
5. Click **"Start Session"**
6. Grant microphone permissions if prompted
7. Start speaking when "Connected" status appears

### Using DevTools

- **Expand/Collapse**: Click the "DevTools" header
- **Filter Logs**: Click level buttons (All/Debug/Info/Warn/Error)
- **Copy Logs**: Click "Copy" button to copy filtered logs to clipboard
- **Clear Logs**: Click "Clear" button to remove all logs

### Ending a Session

- Click **"End Session"** button
- Session will be terminated and resources cleaned up

## API Endpoints

The frontend connects to these orchestrator endpoints:

- `POST /orchestrator/session/start` - Create new voice session
  - Body: `{ userName, voiceId, openingLine }`
  - Returns: `{ success, sessionId, token, serverUrl, roomName, message }`

- `POST /orchestrator/session/end` - End active session
  - Body: `{ sessionId }`
  - Returns: `{ success, message, details }`

## Troubleshooting

### Backend Connection Errors

**Error:** `Failed to start session: fetch failed`

**Solution:** Ensure orchestrator is running on port 8000:

```bash
curl http://localhost:8000/
docker-compose up orchestrator
```

### Microphone Permission Issues

**Error:** Browser blocks microphone access

**Solution:**
- Use HTTPS or localhost
- Check browser microphone permissions
- Ensure no other app is using the microphone

### LiveKit Connection Fails

**Error:** `LiveKit error: connection failed`

**Solution:**
- Verify LiveKit credentials in `.env`
- Check LiveKit server is accessible
- Review DevTools logs for details

### Voice TTS Errors

**Error:** `Unknown voice: [voiceId] not found`

**Solution:**
- Use correct Inworld voice IDs: `Ashley`, `Craig`, `Edward`, `Olivia`, `Wendy`, or `Priya`
- Do NOT use prefixes like `inworld-` or `elevenlabs-`
- Ensure voice is configured in both frontend dropdown and backend `VOICE_SPEED_OVERRIDES`

## Development

### Adding More Voices

To add more voices, update both frontend and backend:

**1. Frontend (`src/VoiceSettings.tsx` lines 19-26):**
```typescript
const availableVoices = [
  { id: 'Ashley', name: 'Ashley (Default) - Warm, natural female' },
  { id: 'Craig', name: 'Craig (Fast) - Professional male' },
  { id: 'Edward', name: 'Edward - Smooth, natural male' },
  { id: 'Olivia', name: 'Olivia - Clear, professional female' },
  { id: 'Wendy', name: 'Wendy (Fast) - Energetic female' },
  { id: 'Priya', name: 'Priya (Asian) - Warm, clear female' },
  { id: 'YourVoice', name: 'Your Voice Name' },  // Add here
];
```

**2. Backend (`backend/agent/voice_assistant.py` lines 57-64):**
```python
VOICE_SPEED_OVERRIDES = {
    "Craig": 1.2,
    "Edward": 1.0,
    "Olivia": 1.0,
    "Wendy": 1.2,
    "Priya": 1.0,
    "Ashley": 1.0,
    "YourVoice": 1.0,  # Add here with desired speed
}
```

### Customizing Logging

See `src/logger.ts` to adjust:
- Maximum stored logs (default: 100)
- Console colors
- Log event format

### Changing Styles

All styles are in `src/styles.css`:
- No CSS modules or styled-components
- Simple, flat structure
- Easy to modify

## Design Philosophy

This frontend prioritizes:
- **Simplicity** over feature completeness
- **Developer experience** over polish
- **Debugging** over production features
- **Clarity** over abstraction

## Docker Deployment

### Local Development (docker-compose)

The frontend is included in the main docker-compose setup:

```bash
# From project root
docker-compose up --build

# Or use Makefile shortcuts
make dev      # Development mode with logs
make up       # Detached mode
make down     # Stop services
make logs     # View logs

# Frontend will be at http://localhost:3000
# Backend at http://localhost:8000
```

### Docker Build Details

The frontend Dockerfile uses a **multi-stage build**:

1. **Builder stage** (node:18-alpine):
   - Installs dependencies
   - Builds production bundle with Vite
   - Optimizes assets

2. **Production stage** (node:18-alpine):
   - Serves static files with `serve`
   - Lightweight runtime (~40MB total)
   - Listens on port specified by `$PORT` (default: 3000)

**Build Context**: Repository root (`.`) - this allows the Dockerfile to copy from `frontend/` subdirectory.

```bash
# Manual build from project root
docker build -f frontend/Dockerfile -t frontend:latest .

# Run container
docker run -p 3000:3000 \
  -e VITE_API_URL=http://localhost:8000 \
  frontend:latest
```

### Railway Deployment

**Configuration:**
- Root Directory: `/`
- Dockerfile Path: `/frontend/Dockerfile`
- Builder: Dockerfile

**Environment Variables:**
- `VITE_API_URL` - Set to your backend service URL

See `../RAILWAY_DEPLOYMENT.md` for complete setup guide.

## License

Part of the LiveKit Voice Agent project.
