# Frontend Integration Guide
## Voice Customization Components

This guide shows how to integrate the voice customization components into your React app.

---

## ✅ Components Created

### 1. Custom Hook
- **File**: `src/hooks/useVoiceConfig.ts`
- **Purpose**: Manages voice configuration state and API calls
- **Exports**: `useVoiceConfig()` hook

### 2. React Components
- **VoicePicker** (`src/components/VoicePicker.tsx`)
  - Grid/list view of available voices
  - Filtering by language, category, tier
  - Tier-based access control

- **OpeningLineEditor** (`src/components/OpeningLineEditor.tsx`)
  - Text editor with validation (5-500 chars)
  - Template suggestions
  - Character counter
  - Real-time validation

- **VoiceConfiguration** (`src/components/VoiceConfiguration.tsx`)
  - Container component that integrates VoicePicker and OpeningLineEditor
  - Handles save/reset logic
  - Shows loading and error states

### 3. Styling
- `src/components/VoicePicker.css`
- `src/components/OpeningLineEditor.css`
- `src/components/VoiceConfiguration.css`

---

## 📋 Integration Steps

### Option 1: Add as Settings Modal

Add a "Settings" button to your App that opens a modal with voice configuration:

```tsx
// App.tsx
import React, { useState } from 'react';
import { VoiceConfiguration } from './components/VoiceConfiguration';

function App() {
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
  const [userName, setUserName] = useState('');

  // ... existing state and functions ...

  const handleConfigSaved = (voiceId: string, openingLine: string) => {
    console.log('Voice configuration saved:', { voiceId, openingLine });
    // Optionally close the modal after saving
    // setShowVoiceSettings(false);
  };

  return (
    <div className="app">
      {/* Existing UI */}
      <div className="app-header">
        <h1>🎤 AI Voice Chat</h1>
        <button
          className="settings-button"
          onClick={() => setShowVoiceSettings(!showVoiceSettings)}
        >
          ⚙️ Voice Settings
        </button>
      </div>

      {/* Voice Settings Modal */}
      {showVoiceSettings && (
        <div className="modal-overlay" onClick={() => setShowVoiceSettings(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button
              className="modal-close"
              onClick={() => setShowVoiceSettings(false)}
            >
              ✕
            </button>
            <VoiceConfiguration
              userId={userName || 'guest'}
              onConfigSaved={handleConfigSaved}
              disabled={false}
            />
          </div>
        </div>
      )}

      {/* Rest of your app */}
    </div>
  );
}
```

**Add modal styling to App.css:**

```css
.settings-button {
  padding: 10px 20px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 16px;
}

.settings-button:hover {
  background: #45a049;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-content {
  background: white;
  border-radius: 12px;
  max-width: 1200px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  position: relative;
}

.modal-close {
  position: absolute;
  top: 20px;
  right: 20px;
  background: #f5f5f5;
  border: none;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 20px;
  cursor: pointer;
  z-index: 10;
}

.modal-close:hover {
  background: #e0e0e0;
}
```

---

### Option 2: Add as Separate Page/Tab

Add voice configuration as a separate page or tab in your app:

```tsx
// App.tsx
import { VoiceConfiguration } from './components/VoiceConfiguration';

function App() {
  const [currentView, setCurrentView] = useState<'chat' | 'settings'>('chat');
  const [userName, setUserName] = useState('');

  return (
    <div className="app">
      <nav className="app-nav">
        <button
          className={currentView === 'chat' ? 'active' : ''}
          onClick={() => setCurrentView('chat')}
        >
          💬 Chat
        </button>
        <button
          className={currentView === 'settings' ? 'active' : ''}
          onClick={() => setCurrentView('settings')}
        >
          ⚙️ Voice Settings
        </button>
      </nav>

      {currentView === 'chat' ? (
        <div className="chat-view">
          {/* Your existing chat UI */}
        </div>
      ) : (
        <div className="settings-view">
          <VoiceConfiguration
            userId={userName || 'guest'}
            onConfigSaved={(voiceId, openingLine) => {
              console.log('Saved:', { voiceId, openingLine });
              // Switch back to chat after saving
              setCurrentView('chat');
            }}
          />
        </div>
      )}
    </div>
  );
}
```

---

### Option 3: Add to Pre-Call Screen

Show voice configuration before starting a call:

```tsx
function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [userName, setUserName] = useState('');

  return (
    <div className="app">
      {!isConnected ? (
        <div className="pre-call-screen">
          <h1>Configure Your AI Assistant</h1>

          <input
            type="text"
            placeholder="Enter your name"
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
            className="name-input"
          />

          <VoiceConfiguration
            userId={userName || 'guest'}
            onConfigSaved={(voiceId, openingLine) => {
              console.log('Voice configured:', { voiceId, openingLine });
            }}
          />

          <button
            className="start-call-button"
            onClick={handleStartCall}
            disabled={!userName}
          >
            🎤 Start Call
          </button>
        </div>
      ) : (
        <LiveKitRoom /* ... your existing LiveKit setup ... */>
          {/* Your call UI */}
        </LiveKitRoom>
      )}
    </div>
  );
}
```

---

## 🔌 API Connection

The components automatically connect to your backend API using the environment variable:

```bash
# .env file
VITE_ORCHESTRATOR_URL=http://localhost:8080
```

For production:
```bash
VITE_ORCHESTRATOR_URL=https://your-api.railway.app
```

---

## 🧪 Testing the Integration

### 1. Start the Backend
```bash
docker-compose -f docker-compose.celery.yml up -d
```

### 2. Start the Frontend
```bash
cd voice-assistant-project/livekit-react-app
npm run dev
```

### 3. Test the Flow

1. **Open the app** at `http://localhost:5173`
2. **Open voice settings** (modal/tab/pre-call screen)
3. **See 25+ voices** loaded from the API
4. **Select a voice** (e.g., Mark)
5. **Customize opening line**: "Hey there! I'm Mark, ready to help with tech!"
6. **Click "Save Configuration"**
7. **See success message** ✓ Configuration saved successfully!
8. **Start a call**
9. **Hear Mark's voice** with your custom greeting!

---

## 📊 Component Props

### VoiceConfiguration

```typescript
interface VoiceConfigurationProps {
  userId: string;              // Required: User identifier
  onConfigSaved?: (voiceId: string, openingLine: string) => void;  // Optional callback
  disabled?: boolean;           // Optional: Disable all controls
}
```

### Usage Example

```tsx
<VoiceConfiguration
  userId="user123"
  onConfigSaved={(voiceId, openingLine) => {
    console.log(`User selected ${voiceId}`);
    console.log(`Opening line: ${openingLine}`);
  }}
  disabled={isLoading}
/>
```

---

## 🎨 Customization

### Change Colors

Edit the CSS files to match your brand:

```css
/* VoicePicker.css */
.voice-card.selected {
  background: #your-brand-color;
  border-color: #your-brand-color;
}

/* VoiceConfiguration.css */
.save-button {
  background: #your-brand-color;
}
```

### Add Custom Tiers

Modify `useVoiceConfig.ts` to support your pricing tiers:

```typescript
// Update the updateConfig function
body: JSON.stringify({
  userId,
  voiceId,
  openingLine,
  userTier: getUserTier(), // Function to get user's subscription tier
}),
```

---

## 🔍 Debugging

### Check API Connection

```javascript
// In browser console
fetch('http://localhost:8080/api/voices')
  .then(r => r.json())
  .then(data => console.log('Voices:', data));
```

### Enable Hook Debugging

```typescript
// In useVoiceConfig.ts, add console.logs
useEffect(() => {
  console.log('Config loaded:', config);
}, [config]);
```

### Check Redux DevTools (if using Redux)

Install Redux DevTools Extension to see state changes in real-time.

---

## ✅ Checklist

Before deploying:

- [ ] Voices load from API
- [ ] Voice selection works
- [ ] Opening line validation works (5-500 chars)
- [ ] Save button works
- [ ] Configuration persists (refresh page, config remains)
- [ ] Tier restrictions work (premium voices locked for free users)
- [ ] Error handling works (network errors shown)
- [ ] Mobile responsive (test on phone)
- [ ] Loading states work
- [ ] Success/error messages display correctly

---

## 🚀 Production Deployment

### Frontend (.env.production)

```bash
VITE_ORCHESTRATOR_URL=https://your-api.railway.app
VITE_LIVEKIT_URL=wss://your-livekit.cloud
```

### Build and Deploy

```bash
npm run build
# Deploy the dist/ folder to your hosting service
```

---

## 📚 Additional Resources

- **Backend API Docs**: See `VOICE_CUSTOMIZATION_IMPLEMENTATION.md`
- **Voice Catalog**: 25+ voices with descriptions
- **Hook API**: See `src/hooks/useVoiceConfig.ts` comments

---

## 💡 Tips

1. **User Experience**: Show voice settings BEFORE the first call
2. **Onboarding**: Guide new users to customize their voice
3. **Analytics**: Track which voices are most popular
4. **A/B Testing**: Test different default opening lines
5. **Accessibility**: Add keyboard navigation to voice picker

---

## 🐛 Troubleshooting

**Problem**: Voices not loading
**Solution**: Check VITE_ORCHESTRATOR_URL and ensure backend is running

**Problem**: Configuration not saving
**Solution**: Check browser console for API errors

**Problem**: Premium voices accessible to free users
**Solution**: Update userTier prop based on user's subscription

**Problem**: Opening line not speaking
**Solution**: Verify the agent is being spawned with the --opening-line argument

---

## 🎉 You're Done!

Your voice customization system is now fully integrated! Users can:
- ✅ Choose from 25+ voices
- ✅ Customize opening greetings
- ✅ Save preferences persistently
- ✅ Hear their customized voice in calls

Happy coding! 🚀
