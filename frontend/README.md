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
- Simple voice selection dropdown (3 Inworld voices)
- Custom opening line input
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

Create a `.env` file (optional):

```env
VITE_API_URL=http://localhost:8000
```

Or export the variable:

```bash
export VITE_API_URL=http://localhost:8000
npm run dev
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
   - Alex - Energetic male, mid-range
   - Ashley - Warm, natural female (default)
   - Dennis - Smooth, calm male
3. **(Optional)** Customize the opening line
4. Click **"Start Session"**
5. Grant microphone permissions if prompted
6. Start speaking when "Connected" status appears

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
- Use correct Inworld voice IDs: `Alex`, `Ashley`, or `Dennis`
- Do NOT use prefixes like `inworld-` or `elevenlabs-`

## Development

### Adding More Voices

Edit `src/VoiceSettings.tsx`:

```typescript
const availableVoices = [
  { id: 'Alex', name: 'Alex - Energetic male, mid-range' },
  { id: 'Ashley', name: 'Ashley - Warm, natural female' },
  { id: 'Dennis', name: 'Dennis - Smooth, calm male' },
  { id: 'YourVoice', name: 'Your Voice Name' },
];
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

The frontend is included in the main docker-compose setup:

```bash
# Build and run all services
docker-compose up --build

# Frontend will be at http://localhost:3000
# Backend at http://localhost:8000
```

## License

Part of the LiveKit Voice Agent project.
