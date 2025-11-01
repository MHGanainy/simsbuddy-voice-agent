import { useState, useEffect, useRef } from 'react';
import { LogEntry, LogLevel } from './types';
import { logger } from './logger';

/**
 * DevTools component - Real-time log display panel
 * Features:
 * - Collapsible panel
 * - Filter by log level
 * - Auto-scroll to bottom
 * - Copy logs to clipboard
 * - Clear logs
 * - Shows current session ID
 */
export default function DevTools() {
  const [logs, setLogs] = useState<LogEntry[]>(logger.getLogs());
  const [isExpanded, setIsExpanded] = useState(true);
  const [filterLevel, setFilterLevel] = useState<LogLevel | 'all'>('all');
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Listen for new log events
  useEffect(() => {
    const handleLogEvent = (event: Event) => {
      const customEvent = event as CustomEvent<LogEntry>;
      setLogs(logger.getLogs());
    };

    window.addEventListener('log', handleLogEvent);
    return () => window.removeEventListener('log', handleLogEvent);
  }, []);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (isExpanded && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isExpanded]);

  // Filter logs by level
  const filteredLogs = filterLevel === 'all'
    ? logs
    : logs.filter(log => log.level === filterLevel);

  // Copy logs to clipboard
  const handleCopyLogs = () => {
    const text = filteredLogs.map(log => {
      const time = log.timestamp.toISOString().substring(11, 19);
      const session = log.sessionId ? ` [${log.sessionId}]` : '';
      const data = log.data ? ` ${JSON.stringify(log.data)}` : '';
      return `[${time}]${session} [${log.level.toUpperCase()}] ${log.message}${data}`;
    }).join('\n');

    navigator.clipboard.writeText(text);
    logger.info('Logs copied to clipboard', { count: filteredLogs.length });
  };

  // Clear all logs
  const handleClearLogs = () => {
    logger.clear();
    setLogs([]);
  };

  // Get current session ID from latest log
  const currentSession = logs.length > 0
    ? logs[logs.length - 1].sessionId
    : undefined;

  // Get level color
  const getLevelColor = (level: LogLevel): string => {
    const colors: Record<LogLevel, string> = {
      debug: '#888',
      info: '#0066cc',
      warn: '#ff9900',
      error: '#cc0000'
    };
    return colors[level];
  };

  return (
    <div className="devtools">
      <div className="devtools-header" onClick={() => setIsExpanded(!isExpanded)}>
        <h3>
          DevTools {isExpanded ? '▼' : '▶'}
          <span className="devtools-count">({filteredLogs.length} logs)</span>
        </h3>
        {currentSession && (
          <span className="devtools-session">
            Session: {currentSession.substring(0, 16)}...
          </span>
        )}
      </div>

      {isExpanded && (
        <>
          <div className="devtools-controls">
            <div className="devtools-filters">
              <button
                className={filterLevel === 'all' ? 'active' : ''}
                onClick={() => setFilterLevel('all')}
              >
                All
              </button>
              <button
                className={filterLevel === 'debug' ? 'active' : ''}
                onClick={() => setFilterLevel('debug')}
              >
                Debug
              </button>
              <button
                className={filterLevel === 'info' ? 'active' : ''}
                onClick={() => setFilterLevel('info')}
              >
                Info
              </button>
              <button
                className={filterLevel === 'warn' ? 'active' : ''}
                onClick={() => setFilterLevel('warn')}
              >
                Warn
              </button>
              <button
                className={filterLevel === 'error' ? 'active' : ''}
                onClick={() => setFilterLevel('error')}
              >
                Error
              </button>
            </div>
            <div className="devtools-actions">
              <button onClick={handleCopyLogs}>Copy</button>
              <button onClick={handleClearLogs}>Clear</button>
            </div>
          </div>

          <div className="devtools-logs">
            {filteredLogs.length === 0 ? (
              <div className="devtools-empty">No logs yet</div>
            ) : (
              filteredLogs.map((log, index) => (
                <div key={index} className="devtools-log-entry">
                  <span className="devtools-log-time">
                    {log.timestamp.toISOString().substring(11, 19)}
                  </span>
                  <span
                    className="devtools-log-level"
                    style={{ color: getLevelColor(log.level) }}
                  >
                    [{log.level.toUpperCase()}]
                  </span>
                  <span className="devtools-log-message">{log.message}</span>
                  {log.data && (
                    <span className="devtools-log-data">
                      {JSON.stringify(log.data)}
                    </span>
                  )}
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </>
      )}
    </div>
  );
}
