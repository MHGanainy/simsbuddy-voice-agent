import { useState, useEffect, useRef } from 'react';
import { LiveKitRoom, RoomAudioRenderer, useConnectionState } from '@livekit/components-react';
import { ConnectionState } from 'livekit-client';
import '@livekit/components-styles';
import { SessionResponse, VoiceSettings as VoiceSettingsType } from './types';
import { logger } from './logger';
import VoiceSettings from './VoiceSettings';
import TestModeSelector, { SpawnMode } from './TestModeSelector';
import DevTools from './DevTools';
import DevLogs from './DevLogs';
import './styles.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const AGENT_SERVER_URL = import.meta.env.VITE_AGENT_SERVER_URL || 'http://localhost:8001';

/**
 * Simplified App Component
 * Reduced from 459 lines to ~200 lines
 *
 * Simplifications:
 * - Removed: Retry logic, timeout utilities, modal system
 * - Removed: Session info display, user name input
 * - Fixed: Backend URL to port 8000 (was 8080)
 * - Added: Comprehensive logging throughout
 * - Fixed: Duplicate end session calls with refs
 */
export default function App() {
  const [showDevLogs, setShowDevLogs] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isEnding, setIsEnding] = useState(false);

  const [voiceSettings, setVoiceSettings] = useState<VoiceSettingsType>({
    voiceId: 'Ashley',
    openingLine: 'Hello! How can I help you today?',
    systemPrompt: ''
  });

  // Spawn mode state with localStorage persistence
  const [spawnMode, setSpawnMode] = useState<SpawnMode>(() => {
    const saved = localStorage.getItem('spawnMode');
    if (saved === 'direct-agent' || saved === 'direct' || saved === 'orchestrator') {
      return saved;
    }
    return 'orchestrator';
  });

  // Persist spawn mode to localStorage
  useEffect(() => {
    localStorage.setItem('spawnMode', spawnMode);
  }, [spawnMode]);

  // Refs to prevent duplicate end session calls
  const sessionIdRef = useRef<string | null>(null);
  const endedSessionsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    logger.info('App initialized', { apiUrl: API_URL });
  }, []);

  // Start a new session
  const handleStartSession = async () => {
    setIsConnecting(true);
    setError(null);
    logger.info('Starting session...', { spawnMode, voiceSettings });

    try {
      // Request microphone permission BEFORE starting session
      logger.info('Requesting microphone permission...');
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        // Stop the stream immediately - we just needed to get permission
        stream.getTracks().forEach(track => track.stop());
        logger.info('Microphone permission granted');
      } catch (permError) {
        logger.error('Microphone permission denied', { error: permError });
        throw new Error('Microphone access is required. Please grant permission and try again.');
      }

      let data: SessionResponse;

      // Route based on spawn mode
      if (spawnMode === 'direct-agent') {
        // Direct Agent Mode: Connect to standalone agent server
        logger.info('Using direct agent mode', { agentServerUrl: AGENT_SERVER_URL });

        const response = await fetch(`${AGENT_SERVER_URL}/connect`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            userName: `user_${Date.now()}`
          })
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        // Adapt agent server response to SessionResponse format
        const agentResponse = await response.json();
        data = {
          success: agentResponse.success,
          sessionId: agentResponse.roomName, // Use room name as session ID
          token: agentResponse.token,
          serverUrl: agentResponse.serverUrl,
          roomName: agentResponse.roomName,
          message: agentResponse.message
        };

        logger.info('Connected to standalone agent', {
          roomName: agentResponse.roomName,
          voiceId: agentResponse.voiceId
        });

      } else {
        // Direct/Orchestrator Mode: Connect via orchestrator
        const endpoint = spawnMode === 'direct'
          ? `${API_URL}/orchestrator/session/start-direct`
          : `${API_URL}/orchestrator/session/start`;

        logger.info('Using orchestrator', { spawnMode, endpoint });

        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            userName: `user_${Date.now()}`,
            voiceId: voiceSettings.voiceId,
            openingLine: voiceSettings.openingLine,
            ...(voiceSettings.systemPrompt && { systemPrompt: voiceSettings.systemPrompt })
          })
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        data = await response.json();

        logger.info('Session created via orchestrator', {
          sessionId: data.sessionId,
          roomName: data.roomName,
          serverUrl: data.serverUrl
        });
      }

      // Common setup for all modes
      setSessionId(data.sessionId);
      sessionIdRef.current = data.sessionId;
      setToken(data.token);
      setServerUrl(data.serverUrl);
      logger.setSessionId(data.sessionId);

    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      logger.error('Failed to start session', { error: message });
      setError(`Failed to start session: ${message}`);
    } finally {
      setIsConnecting(false);
    }
  };

  // End the current session
  const handleEndSession = async () => {
    if (!sessionId || isEnding) return;

    // Check if we've already ended this session
    if (endedSessionsRef.current.has(sessionId)) {
      logger.info('Session already ended, skipping duplicate call', { sessionId });
      return;
    }

    setIsEnding(true);
    endedSessionsRef.current.add(sessionId);
    logger.info('Ending session...', { sessionId, spawnMode });

    try {
      // Only call orchestrator end endpoint for orchestrator/direct modes
      // Direct agent mode doesn't need explicit end (agent stays running)
      if (spawnMode !== 'direct-agent') {
        const response = await fetch(`${API_URL}/orchestrator/session/end`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId })
        });

        // 404 is expected if session was already ended
        if (response.ok || response.status === 404) {
          logger.info('Session ended successfully', { sessionId });
        } else {
          const errorData = await response.json().catch(() => ({}));
          logger.error('Failed to end session', { error: errorData.error, status: response.status });
        }
      } else {
        logger.info('Direct agent mode - no session end needed', { sessionId });
      }

    } catch (err) {
      logger.error('Error ending session', { error: err });
    } finally {
      // Reset state
      setSessionId(null);
      sessionIdRef.current = null;
      setToken(null);
      setServerUrl(null);
      setIsEnding(false);
    }
  };

  // Cleanup on unmount - use empty dependency array to only run on actual unmount
  useEffect(() => {
    return () => {
      // Only cleanup on actual unmount, use ref to get current sessionId
      const currentSessionId = sessionIdRef.current;
      if (currentSessionId && !endedSessionsRef.current.has(currentSessionId)) {
        logger.info('Cleaning up session on unmount', { sessionId: currentSessionId });
        endedSessionsRef.current.add(currentSessionId);
        // Can't use handleEndSession here as state might be stale
        // Fire and forget cleanup
        fetch(`${API_URL}/orchestrator/session/end`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: currentSessionId })
        }).catch(err => {
          logger.warn('Unmount cleanup error', { error: err });
        });
      }
    };
  }, []); // Empty dependency array - only run on unmount

  // Show DevLogs if toggled
  if (showDevLogs) {
    return (
      <div className="app">
        <header className="app-header">
          <h1>Voice Agent - Dev Interface</h1>
          <button
            onClick={() => setShowDevLogs(false)}
            style={{
              padding: '8px 16px',
              background: '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500'
            }}
          >
            ← Back to Voice Agent
          </button>
        </header>
        <DevLogs />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Voice Agent - Dev Interface</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
          <ConnectionStatus sessionId={sessionId} spawnMode={spawnMode} />
          <button
            onClick={() => setShowDevLogs(true)}
            style={{
              padding: '8px 16px',
              background: '#007bff',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500'
            }}
          >
            🛠️ Dev Logs
          </button>
        </div>
      </header>

      <main className="app-main">
        {error && (
          <div className="error-message">
            <strong>Error:</strong> {error}
          </div>
        )}

        {!sessionId ? (
          <div className="app-controls">
            <TestModeSelector
              value={spawnMode}
              onChange={setSpawnMode}
              disabled={isConnecting}
            />

            <VoiceSettings
              settings={voiceSettings}
              onSettingsChange={setVoiceSettings}
            />

            <div className="app-connect">
              <button
                onClick={handleStartSession}
                disabled={isConnecting}
                className="primary large"
              >
                {isConnecting ? 'Connecting...' : 'Start Session'}
              </button>
            </div>
          </div>
        ) : (
          <>
            {token && serverUrl && (
              <LiveKitRoom
                token={token}
                serverUrl={serverUrl}
                connect={true}
                audio={true}
                onConnected={() => {
                  logger.info('LiveKit room connected');
                }}
                onDisconnected={() => {
                  logger.warn('LiveKit room disconnected');
                }}
                onError={(error) => {
                  logger.error('LiveKit error', { error: error.message });
                }}
              >
                <RoomContent onEndSession={handleEndSession} />
              </LiveKitRoom>
            )}
          </>
        )}
      </main>

      <DevTools />
    </div>
  );
}

/**
 * Room Content - Displayed when connected to LiveKit
 */
function RoomContent({ onEndSession }: { onEndSession: () => void }) {
  const connectionState = useConnectionState();

  useEffect(() => {
    logger.debug('Connection state changed', { state: connectionState });
  }, [connectionState]);

  return (
    <div className="room-content">
      <RoomAudioRenderer />

      <div className="room-status">
        <ConnectionStateIndicator state={connectionState} />

        {connectionState === ConnectionState.Connected && (
          <p className="room-message">
            You're connected! Start speaking to interact with the voice agent.
          </p>
        )}
      </div>

      <div className="room-controls">
        <button onClick={onEndSession} className="danger large">
          End Session
        </button>
      </div>
    </div>
  );
}

/**
 * Connection Status Display
 */
function ConnectionStatus({ sessionId, spawnMode }: { sessionId: string | null; spawnMode?: SpawnMode }) {
  if (!sessionId) return null;

  const modeLabels: Record<SpawnMode, string> = {
    'direct-agent': 'Direct Agent',
    'direct': 'Direct',
    'orchestrator': 'Orchestrator'
  };

  return (
    <div className="connection-status connected">
      <span className="status-dot"></span>
      <span className="status-text">Connected</span>
      {spawnMode && (
        <span className={`session-mode-badge ${spawnMode}`}>
          {modeLabels[spawnMode]}
        </span>
      )}
      <span className="status-session">{sessionId.substring(0, 12)}...</span>
    </div>
  );
}

/**
 * Connection State Indicator
 */
function ConnectionStateIndicator({ state }: { state: ConnectionState }) {
  const stateInfo: Record<ConnectionState, { label: string; className: string }> = {
    [ConnectionState.Disconnected]: { label: 'Disconnected', className: 'disconnected' },
    [ConnectionState.Connecting]: { label: 'Connecting...', className: 'connecting' },
    [ConnectionState.Connected]: { label: 'Connected', className: 'connected' },
    [ConnectionState.Reconnecting]: { label: 'Reconnecting...', className: 'reconnecting' }
  };

  const info = stateInfo[state] || { label: 'Unknown', className: 'unknown' };

  return (
    <div className={`connection-indicator ${info.className}`}>
      <span className="indicator-dot"></span>
      <span className="indicator-label">{info.label}</span>
    </div>
  );
}
