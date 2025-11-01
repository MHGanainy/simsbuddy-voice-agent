import { useState, useEffect, useRef } from 'react';
import { LiveKitRoom, RoomAudioRenderer, useConnectionState } from '@livekit/components-react';
import { ConnectionState } from 'livekit-client';
import '@livekit/components-styles';
import { SessionResponse, VoiceSettings as VoiceSettingsType } from './types';
import { logger } from './logger';
import VoiceSettings from './VoiceSettings';
import DevTools from './DevTools';
import './styles.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
    logger.info('Starting session...', { voiceSettings });

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

      const response = await fetch(`${API_URL}/orchestrator/session/start`, {
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

      const data: SessionResponse = await response.json();

      logger.info('Session created', {
        sessionId: data.sessionId,
        roomName: data.roomName,
        serverUrl: data.serverUrl
      });

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
    logger.info('Ending session...', { sessionId });

    try {
      const response = await fetch(`${API_URL}/orchestrator/session/end`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId })
      });

      // 404 is expected if session was already ended
      if (!response.ok && response.status !== 404) {
        throw new Error(`HTTP ${response.status}`);
      }

      logger.info('Session ended', { sessionId, status: response.status });

    } catch (err) {
      logger.warn('Error ending session (continuing cleanup)', { error: err });
    }

    // Cleanup state
    setSessionId(null);
    setToken(null);
    setServerUrl(null);
    setIsEnding(false);
    sessionIdRef.current = null;
    logger.clearSessionId();
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

  return (
    <div className="app">
      <header className="app-header">
        <h1>Voice Agent - Dev Interface</h1>
        <ConnectionStatus sessionId={sessionId} />
      </header>

      <main className="app-main">
        {error && (
          <div className="error-message">
            <strong>Error:</strong> {error}
          </div>
        )}

        {!sessionId ? (
          <div className="app-controls">
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
function ConnectionStatus({ sessionId }: { sessionId: string | null }) {
  if (!sessionId) return null;

  return (
    <div className="connection-status connected">
      <span className="status-dot"></span>
      <span className="status-text">Connected</span>
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
