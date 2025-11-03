import React, { useState, useEffect } from 'react';

interface Session {
  session_id: string;
  user_id: string;
  voice_id: string;
  status: string;
  is_active: boolean;
  start_time: string | null;
  duration_seconds: number | null;
  agent_pid: number | null;
  created_at: string;
}

interface LogEntry {
  message: string;
  raw?: boolean;
  timestamp?: string;
  level?: string;
  event?: string;
}

const DevLogs: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'sessions' | 'orchestrator' | 'celery'>('sessions');
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [sessionLogs, setSessionLogs] = useState<LogEntry[]>([]);
  const [orchestratorLogs, setOrchestratorLogs] = useState<LogEntry[]>([]);
  const [celeryLogs, setCeleryLogs] = useState<LogEntry[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [activeCount, setActiveCount] = useState(0);

  // Use environment variable or default to localhost
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Fetch sessions
  const fetchSessions = async () => {
    try {
      const response = await fetch(`${API_URL}/api/admin/sessions`);
      const data = await response.json();
      setSessions(data.sessions || []);
      setActiveCount(data.active_count || 0);
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
  };

  // Fetch logs for selected session
  const fetchSessionLogs = async (sessionId: string) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/api/admin/sessions/${sessionId}/logs?limit=200`);
      const data = await response.json();
      setSessionLogs(data.logs || []);
    } catch (error) {
      console.error('Failed to fetch session logs:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch orchestrator logs
  const fetchOrchestratorLogs = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/api/admin/logs/orchestrator?lines=500`);
      const data = await response.json();
      setOrchestratorLogs(data.logs || []);
    } catch (error) {
      console.error('Failed to fetch orchestrator logs:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch Celery logs
  const fetchCeleryLogs = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_URL}/api/admin/logs/celery?lines=500`);
      const data = await response.json();
      setCeleryLogs(data.logs || []);
    } catch (error) {
      console.error('Failed to fetch celery logs:', error);
    } finally {
      setLoading(false);
    }
  };

  // Auto-refresh effect
  useEffect(() => {
    if (activeTab === 'sessions') {
      fetchSessions();
      if (autoRefresh) {
        const interval = setInterval(fetchSessions, 5000); // Refresh every 5 seconds
        return () => clearInterval(interval);
      }
    } else if (activeTab === 'orchestrator') {
      fetchOrchestratorLogs();
      if (autoRefresh) {
        const interval = setInterval(fetchOrchestratorLogs, 5000);
        return () => clearInterval(interval);
      }
    } else if (activeTab === 'celery') {
      fetchCeleryLogs();
      if (autoRefresh) {
        const interval = setInterval(fetchCeleryLogs, 5000);
        return () => clearInterval(interval);
      }
    }
  }, [activeTab, autoRefresh]);

  // Format duration
  const formatDuration = (seconds: number | null) => {
    if (!seconds) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  // Format timestamp
  const formatTimestamp = (timestamp: string | null) => {
    if (!timestamp) return 'N/A';
    const date = new Date(parseInt(timestamp) * 1000);
    return date.toLocaleString();
  };

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>🛠️ Dev Logs & Monitoring</h1>
        <div style={styles.headerControls}>
          <label style={styles.checkbox}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span style={{ marginLeft: '8px' }}>Auto-refresh (5s)</span>
          </label>
        </div>
      </div>

      {/* Tabs */}
      <div style={styles.tabs}>
        <button
          style={{
            ...styles.tab,
            ...(activeTab === 'sessions' ? styles.tabActive : {}),
          }}
          onClick={() => setActiveTab('sessions')}
        >
          📋 Sessions ({sessions.length})
          {activeCount > 0 && (
            <span style={styles.activeBadge}>{activeCount} active</span>
          )}
        </button>
        <button
          style={{
            ...styles.tab,
            ...(activeTab === 'orchestrator' ? styles.tabActive : {}),
          }}
          onClick={() => setActiveTab('orchestrator')}
        >
          🚀 Orchestrator Logs
        </button>
        <button
          style={{
            ...styles.tab,
            ...(activeTab === 'celery' ? styles.tabActive : {}),
          }}
          onClick={() => setActiveTab('celery')}
        >
          ⚙️ Celery Logs
        </button>
      </div>

      {/* Tab Content */}
      <div style={styles.tabContent}>
        {/* Sessions Tab */}
        {activeTab === 'sessions' && (
          <div style={styles.sessionsTab}>
            <div style={styles.sessionsList}>
              <h2 style={styles.sectionTitle}>
                Sessions ({sessions.length})
              </h2>
              <div style={styles.tableContainer}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Status</th>
                      <th style={styles.th}>Session ID</th>
                      <th style={styles.th}>User</th>
                      <th style={styles.th}>Voice</th>
                      <th style={styles.th}>Duration</th>
                      <th style={styles.th}>Start Time</th>
                      <th style={styles.th}>PID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((session) => (
                      <tr
                        key={session.session_id}
                        style={{
                          ...styles.tr,
                          ...(selectedSession === session.session_id
                            ? styles.trSelected
                            : {}),
                        }}
                        onClick={() => {
                          setSelectedSession(session.session_id);
                          fetchSessionLogs(session.session_id);
                        }}
                      >
                        <td style={styles.td}>
                          <span
                            style={{
                              ...styles.statusBadge,
                              ...(session.is_active
                                ? styles.statusActive
                                : styles.statusInactive),
                            }}
                          >
                            {session.is_active ? '🟢' : '🔴'}{' '}
                            {session.status}
                          </span>
                        </td>
                        <td style={{ ...styles.td, ...styles.monospace }}>
                          {session.session_id}
                        </td>
                        <td style={styles.td}>{session.user_id}</td>
                        <td style={styles.td}>{session.voice_id}</td>
                        <td style={styles.td}>
                          {formatDuration(session.duration_seconds)}
                        </td>
                        <td style={styles.td}>
                          {formatTimestamp(session.start_time)}
                        </td>
                        <td style={styles.td}>{session.agent_pid || 'N/A'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {selectedSession && (
              <div style={styles.sessionLogs}>
                <h3 style={styles.sectionTitle}>
                  Logs for {selectedSession}
                </h3>
                {loading ? (
                  <div style={styles.loading}>Loading logs...</div>
                ) : (
                  <div style={styles.logViewer}>
                    {sessionLogs.length === 0 ? (
                      <div style={styles.noLogs}>
                        No logs found for this session
                      </div>
                    ) : (
                      sessionLogs.map((log, idx) => (
                        <div key={idx} style={styles.logEntry}>
                          {log.raw ? (
                            <span>{log.message}</span>
                          ) : (
                            <>
                              {log.timestamp && (
                                <span style={styles.logTimestamp}>
                                  {formatTimestamp(log.timestamp)}
                                </span>
                              )}
                              {log.level && (
                                <span
                                  style={{
                                    ...styles.logLevel,
                                    color: getLogLevelColor(log.level),
                                  }}
                                >
                                  {log.level}
                                </span>
                              )}
                              {log.event && (
                                <span style={styles.logEvent}>{log.event}</span>
                              )}
                              <span style={styles.logMessage}>{log.message}</span>
                            </>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Orchestrator Logs Tab */}
        {activeTab === 'orchestrator' && (
          <div style={styles.logsTab}>
            <h2 style={styles.sectionTitle}>
              Orchestrator Logs ({orchestratorLogs.length})
            </h2>
            {loading ? (
              <div style={styles.loading}>Loading logs...</div>
            ) : (
              <div style={styles.logViewer}>
                {orchestratorLogs.length === 0 ? (
                  <div style={styles.noLogs}>
                    No logs available. Logs may be sent to stdout.
                  </div>
                ) : (
                  orchestratorLogs.map((log, idx) => (
                    <div key={idx} style={styles.logEntry}>
                      {log.raw ? (
                        <span>{log.message}</span>
                      ) : (
                        <>
                          {log.timestamp && (
                            <span style={styles.logTimestamp}>
                              {formatTimestamp(log.timestamp)}
                            </span>
                          )}
                          {log.level && (
                            <span
                              style={{
                                ...styles.logLevel,
                                color: getLogLevelColor(log.level),
                              }}
                            >
                              {log.level}
                            </span>
                          )}
                          <span style={styles.logMessage}>{log.message}</span>
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}

        {/* Celery Logs Tab */}
        {activeTab === 'celery' && (
          <div style={styles.logsTab}>
            <h2 style={styles.sectionTitle}>
              Celery Worker Logs ({celeryLogs.length})
            </h2>
            {loading ? (
              <div style={styles.loading}>Loading logs...</div>
            ) : (
              <div style={styles.logViewer}>
                {celeryLogs.length === 0 ? (
                  <div style={styles.noLogs}>
                    No Celery logs available. Logs may be sent to stdout.
                  </div>
                ) : (
                  celeryLogs.map((log, idx) => (
                    <div key={idx} style={styles.logEntry}>
                      <span>{log.message}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// Helper function for log level colors
const getLogLevelColor = (level: string) => {
  const colors: Record<string, string> = {
    INFO: '#4fc3f7',
    WARNING: '#ffb74d',
    ERROR: '#e57373',
    DEBUG: '#9575cd',
    CRITICAL: '#f44336',
  };
  return colors[level.toUpperCase()] || '#d4d4d4';
};

// Inline styles
const styles = {
  container: {
    padding: '20px',
    maxWidth: '1600px',
    margin: '0 auto',
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '20px',
    paddingBottom: '15px',
    borderBottom: '2px solid #e0e0e0',
  },
  title: {
    margin: 0,
    fontSize: '28px',
    fontWeight: '600',
  },
  headerControls: {
    display: 'flex',
    alignItems: 'center',
    gap: '15px',
  },
  checkbox: {
    display: 'flex',
    alignItems: 'center',
    cursor: 'pointer',
    fontSize: '14px',
  },
  tabs: {
    display: 'flex',
    gap: '10px',
    marginBottom: '20px',
  },
  tab: {
    padding: '12px 24px',
    background: '#f5f5f5',
    border: '2px solid #e0e0e0',
    borderRadius: '8px',
    cursor: 'pointer',
    fontSize: '15px',
    fontWeight: '500',
    transition: 'all 0.2s',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  tabActive: {
    background: '#007bff',
    color: 'white',
    borderColor: '#007bff',
  },
  activeBadge: {
    background: 'rgba(255, 255, 255, 0.3)',
    padding: '2px 8px',
    borderRadius: '12px',
    fontSize: '12px',
    fontWeight: '600',
  },
  tabContent: {
    marginTop: '20px',
  },
  sessionsTab: {
    display: 'grid',
    gridTemplateColumns: '60% 40%',
    gap: '20px',
  },
  sessionsList: {},
  sectionTitle: {
    fontSize: '18px',
    fontWeight: '600',
    marginBottom: '15px',
  },
  tableContainer: {
    overflowX: 'auto' as const,
    border: '1px solid #e0e0e0',
    borderRadius: '8px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '13px',
  },
  th: {
    background: '#f8f9fa',
    padding: '12px',
    textAlign: 'left' as const,
    borderBottom: '2px solid #dee2e6',
    fontWeight: '600',
    fontSize: '12px',
    textTransform: 'uppercase' as const,
    color: '#495057',
  },
  td: {
    padding: '12px',
    borderBottom: '1px solid #e9ecef',
  },
  tr: {
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  trSelected: {
    background: '#e7f3ff',
  },
  statusBadge: {
    padding: '4px 10px',
    borderRadius: '12px',
    fontSize: '11px',
    fontWeight: '600',
    display: 'inline-block',
  },
  statusActive: {
    background: '#d4edda',
    color: '#155724',
  },
  statusInactive: {
    background: '#f8d7da',
    color: '#721c24',
  },
  monospace: {
    fontFamily: "'Monaco', 'Courier New', monospace",
    fontSize: '12px',
    color: '#495057',
  },
  sessionLogs: {
    border: '1px solid #e0e0e0',
    borderRadius: '8px',
    padding: '15px',
  },
  logViewer: {
    background: '#1e1e1e',
    color: '#d4d4d4',
    padding: '15px',
    borderRadius: '6px',
    maxHeight: '600px',
    overflowY: 'auto' as const,
    fontSize: '12px',
    lineHeight: '1.6',
    fontFamily: "'Monaco', 'Courier New', monospace",
  },
  logEntry: {
    padding: '6px 0',
    borderBottom: '1px solid #2d2d2d',
    display: 'flex',
    gap: '12px',
    flexWrap: 'wrap' as const,
  },
  logTimestamp: {
    color: '#858585',
    minWidth: '160px',
  },
  logLevel: {
    fontWeight: '600',
    minWidth: '80px',
  },
  logEvent: {
    color: '#81c784',
    fontWeight: '500',
    minWidth: '150px',
  },
  logMessage: {
    color: '#d4d4d4',
    flex: 1,
    wordBreak: 'break-word' as const,
  },
  loading: {
    textAlign: 'center' as const,
    padding: '40px',
    color: '#666',
    fontSize: '14px',
  },
  noLogs: {
    textAlign: 'center' as const,
    padding: '40px',
    color: '#858585',
    fontSize: '14px',
  },
  logsTab: {},
};

export default DevLogs;
