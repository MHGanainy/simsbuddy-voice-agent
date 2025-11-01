// App.tsx - Replace your existing App.tsx with this
import React, { useState, useCallback, useEffect } from 'react';
import {
  LiveKitRoom,
  AudioConference,
  ControlBar,
  RoomAudioRenderer,
  useConnectionState,
  useRoomContext,
} from '@livekit/components-react';
import '@livekit/components-styles';
import './App.css';
import { VoiceConfiguration } from './components/VoiceConfiguration';

// ==================== CONFIGURATION ====================
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880';
const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL || 'http://localhost:8080';

// Retry and timeout configuration
const REQUEST_TIMEOUT = 30000; // 30 seconds
const MAX_RETRIES = 3;
const RETRY_DELAY = 2000; // 2 seconds

// ==================== UTILITY FUNCTIONS ====================

// Fetch with timeout
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeout = REQUEST_TIMEOUT): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('Request timeout - please check your connection and try again');
    }
    throw error;
  }
}

// Retry logic with exponential backoff
async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  maxRetries = MAX_RETRIES
): Promise<Response> {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const response = await fetchWithTimeout(url, options);

      // If successful, return immediately
      if (response.ok) {
        return response;
      }

      // If server error (5xx), retry
      if (response.status >= 500) {
        throw new Error(`Server error: ${response.status}`);
      }

      // For client errors (4xx), don't retry
      return response;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      // Don't retry on last attempt
      if (attempt === maxRetries - 1) {
        break;
      }

      // Wait before retrying with exponential backoff
      const delay = RETRY_DELAY * Math.pow(2, attempt);
      console.log(`Attempt ${attempt + 1} failed, retrying in ${delay}ms...`);
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }

  throw lastError || new Error('Request failed after retries');
}

interface SessionInfo {
  sessionId: string;
  status: string;
  startTime: number;
}

function App() {
  const [token, setToken] = useState<string>('');
  const [serverUrl, setServerUrl] = useState<string>('');
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string>('');
  const [userName, setUserName] = useState<string>('');
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);
  const [sessionId, setSessionId] = useState<string>('');
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);

  // Handler for voice configuration save
  const handleConfigSaved = (voiceId: string, openingLine: string) => {
    console.log('Voice configuration saved:', { voiceId, openingLine });
    // Optionally close the modal after saving
    // setShowVoiceSettings(false);
  };

  // Start a new chat session with retry logic
  const startSession = async () => {
    const abortController = new AbortController();

    try {
      setIsConnecting(true);
      setError('');

      // Step 1: Request a new bot session with retry
      console.log('Starting new bot session...');
      const botResponse = await fetchWithRetry(`${ORCHESTRATOR_URL}/api/session/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          userId: `user-${Date.now()}`,
          userName: userName || 'Guest',
        }),
      });

      if (!botResponse.ok) {
        let errorMessage = 'Failed to start bot session';
        try {
          const errorData = await botResponse.json();
          errorMessage = errorData.message || errorMessage;

          // Handle specific error cases
          if (botResponse.status === 503) {
            errorMessage = 'Server is at capacity. Please try again in a few moments.';
          } else if (botResponse.status === 429) {
            errorMessage = 'Too many requests. Please wait a moment and try again.';
          }
        } catch (jsonError) {
          console.error('Failed to parse error response:', jsonError);
        }
        throw new Error(errorMessage);
      }

      const botData = await botResponse.json();

      // Validate response data
      if (!botData.sessionId) {
        throw new Error('Invalid response from server: missing session ID');
      }

      console.log('Bot session started:', botData.sessionId);
      setSessionId(botData.sessionId);
      setSessionInfo(botData.info);

      // Step 2: Get token for the user to join the same room
      // Retry with backoff if bot is not ready yet
      let tokenData = null;
      const maxTokenRetries = 5;

      for (let i = 0; i < maxTokenRetries; i++) {
        try {
          console.log(`Getting token for room: ${botData.sessionId} (attempt ${i + 1}/${maxTokenRetries})`);
          const tokenResponse = await fetchWithTimeout(`${ORCHESTRATOR_URL}/api/token`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              sessionId: botData.sessionId,
              userName: userName || 'Guest',
            }),
          });

          if (tokenResponse.ok) {
            tokenData = await tokenResponse.json();
            break;
          }

          const errorData = await tokenResponse.json().catch(() => ({}));

          // If bot is not ready, wait and retry
          if (tokenResponse.status === 503 && errorData.error === 'Bot not ready') {
            const retryAfter = errorData.retryAfter || 2;
            console.log(`Bot not ready, waiting ${retryAfter}s before retry...`);
            await new Promise(resolve => setTimeout(resolve, retryAfter * 1000));
            continue;
          }

          // For other errors, throw immediately
          throw new Error(errorData.message || 'Failed to get access token');
        } catch (error) {
          if (i === maxTokenRetries - 1) {
            throw error;
          }
        }
      }

      if (!tokenData || !tokenData.token) {
        throw new Error('Failed to obtain access token after multiple attempts');
      }

      console.log('Token received, connecting to LiveKit...');

      setToken(tokenData.token);
      setServerUrl(tokenData.url || LIVEKIT_URL);
      setIsConnected(true);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred';
      setError(errorMessage);
      console.error('Error starting session:', err);

      // Clean up any partial session
      if (sessionId) {
        try {
          await fetchWithTimeout(`${ORCHESTRATOR_URL}/api/session/stop`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ sessionId }),
          });
        } catch (cleanupError) {
          console.error('Error cleaning up session:', cleanupError);
        }
      }
    } finally {
      setIsConnecting(false);
    }
  };

  // End the current session
  const endSession = async () => {
    console.log('Ending session:', sessionId);

    // Tell orchestrator to stop the bot
    if (sessionId) {
      try {
        await fetchWithTimeout(`${ORCHESTRATOR_URL}/api/session/stop`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            sessionId: sessionId,
          }),
        }, 5000); // Short timeout for cleanup
      } catch (err) {
        console.error('Error stopping bot:', err);
        // Don't show error to user - just log it
      }
    }

    // Reset state
    setIsConnected(false);
    setToken('');
    setServerUrl('');
    setSessionId('');
    setSessionInfo(null);
    setError(''); // Clear any errors
  };

  // Check server status on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await fetchWithTimeout(`${ORCHESTRATOR_URL}/api/health`, {}, 5000);

        if (response.ok) {
          const data = await response.json();
          console.log('Orchestrator status:', data);
        } else {
          throw new Error(`Health check failed with status ${response.status}`);
        }
      } catch (err) {
        console.error('Orchestrator not reachable:', err);
        const errorMsg = err instanceof Error && err.message.includes('timeout')
          ? 'Orchestrator is not responding. Please check if it\'s running on port 8080.'
          : 'Cannot connect to orchestrator. Make sure it\'s running on port 8080.';
        setError(errorMsg);
      }
    };

    checkHealth();
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (sessionId) {
        // Best effort cleanup on unmount
        fetch(`${ORCHESTRATOR_URL}/api/session/stop`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ sessionId }),
          keepalive: true, // Important for cleanup during page unload
        }).catch(err => console.error('Cleanup error:', err));
      }
    };
  }, [sessionId]);

  if (!isConnected) {
    return (
      <div className="app">
        <div className="connect-container">
          <div className="app-header">
            <h1>🎤 AI Voice Chat</h1>
            <button
              className="settings-button"
              onClick={() => setShowVoiceSettings(!showVoiceSettings)}
            >
              ⚙️ Voice Settings
            </button>
          </div>
          <p>Each conversation is completely private and isolated</p>

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

          <div className="connect-form">
            <div className="form-group">
              <label>Your Name (optional):</label>
              <input
                type="text"
                value={userName}
                onChange={(e) => setUserName(e.target.value)}
                placeholder="Enter your name or stay anonymous"
              />
            </div>

            <button 
              className="start-button"
              onClick={startSession}
              disabled={isConnecting}
            >
              {isConnecting ? '🔄 Starting your session...' : '🚀 Start Private Conversation'}
            </button>

            {error && (
              <div className="error-message">
                ❌ {error}
              </div>
            )}
            
            <div className="info-box">
              <h3>How it works:</h3>
              <ul>
                <li>✅ Each user gets their own private AI assistant</li>
                <li>🔒 Conversations are completely isolated</li>
                <li>⏱️ Sessions auto-end after 30 minutes of inactivity</li>
                <li>🚀 Up to 50 concurrent users supported</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <LiveKitRoom
        token={token}
        serverUrl={serverUrl}
        connectOptions={{
          autoSubscribe: true,
        }}
        audio={true}
        video={false}
        onDisconnected={endSession}
      >
        <ConversationRoom 
          sessionId={sessionId}
          sessionInfo={sessionInfo}
          onEndSession={endSession}
        />
      </LiveKitRoom>
    </div>
  );
}

function ConversationRoom({ 
  sessionId, 
  sessionInfo,
  onEndSession 
}: { 
  sessionId: string;
  sessionInfo: SessionInfo | null;
  onEndSession: () => void;
}) {
  const connectionState = useConnectionState();
  const [elapsedTime, setElapsedTime] = useState<string>('00:00');

  // Update elapsed time every second
  useEffect(() => {
    if (!sessionInfo) return;

    const interval = setInterval(() => {
      const elapsed = Date.now() - sessionInfo.startTime;
      const minutes = Math.floor(elapsed / 60000);
      const seconds = Math.floor((elapsed % 60000) / 1000);
      setElapsedTime(`${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`);
    }, 1000);

    return () => clearInterval(interval);
  }, [sessionInfo]);

  return (
    <div className="conversation-room">
      <div className="room-header">
        <h2>🤖 Your Private AI Assistant</h2>
        <div className="session-info">
          <div className="session-id">
            Session: <code>{sessionId.substring(0, 20)}...</code>
          </div>
          <div className="connection-status">
            Status: <span className={`status-${connectionState.toLowerCase()}`}>
              {connectionState}
            </span>
          </div>
          <div className="session-time">
            Duration: {elapsedTime}
          </div>
        </div>
      </div>

      <div className="audio-container">
        <RoomAudioRenderer />
        <AudioConference />
        
        <div className="agent-status">
          {connectionState === 'connected' ? (
            <div className="listening-indicator">
              <span className="pulse"></span>
              AI Assistant is ready! Start speaking...
            </div>
          ) : (
            <div className="connecting-indicator">
              Connecting to your assistant...
            </div>
          )}
        </div>

        <div className="tips">
          💡 Tip: Speak naturally, as if talking to a friend. The AI will respond after you pause.
        </div>
      </div>

      <div className="controls">
        <ControlBar 
          variation="verbose"
          controls={{
            microphone: true,
            screenShare: false,
            camera: false,
            chat: false,
            leave: true,
          }}
          onLeave={onEndSession}
        />
      </div>

      <div className="end-session-section">
        <button 
          className="end-button"
          onClick={onEndSession}
        >
          🛑 End Conversation
        </button>
      </div>
    </div>
  );
}

export default App;