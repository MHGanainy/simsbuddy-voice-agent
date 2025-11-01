import { LogLevel, LogEntry } from './types';

/**
 * Structured logging utility for frontend
 * Features:
 * - Color-coded console output
 * - Session ID correlation
 * - Event emission for UI display
 * - In-memory log storage (last 100 logs)
 */
class Logger {
  private sessionId?: string;
  private logs: LogEntry[] = [];
  private readonly maxLogs = 100;

  /**
   * Set the current session ID for log correlation
   */
  setSessionId(id: string): void {
    this.sessionId = id;
    this.info('Session ID set', { sessionId: id });
  }

  /**
   * Clear the current session ID
   */
  clearSessionId(): void {
    const oldSessionId = this.sessionId;
    this.sessionId = undefined;
    this.info('Session ID cleared', { previousSessionId: oldSessionId });
  }

  /**
   * Internal log method - handles console output, storage, and event emission
   */
  private log(level: LogLevel, message: string, data?: any): void {
    const entry: LogEntry = {
      timestamp: new Date(),
      level,
      message,
      sessionId: this.sessionId,
      data
    };

    // Store in memory (keep last N logs)
    this.logs.push(entry);
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    // Console output with colors
    const colors: Record<LogLevel, string> = {
      debug: 'color: gray',
      info: 'color: #0066cc',
      warn: 'color: #ff9900',
      error: 'color: #cc0000; font-weight: bold'
    };

    const time = entry.timestamp.toISOString().substring(11, 19);
    const sessionTag = this.sessionId ? ` [${this.sessionId.substring(0, 8)}...]` : '';

    console.log(
      `%c[${time}]${sessionTag} [${level.toUpperCase()}] ${message}`,
      colors[level],
      data !== undefined ? data : ''
    );

    // Emit event for UI components (DevTools)
    window.dispatchEvent(new CustomEvent('log', { detail: entry }));
  }

  /**
   * Log debug message (gray)
   * Use for: WebRTC events, state changes, technical details
   */
  debug(message: string, data?: any): void {
    this.log('debug', message, data);
  }

  /**
   * Log info message (blue)
   * Use for: Session start/stop, connection status, user actions
   */
  info(message: string, data?: any): void {
    this.log('info', message, data);
  }

  /**
   * Log warning message (orange)
   * Use for: Connection issues, retry attempts, degraded functionality
   */
  warn(message: string, data?: any): void {
    this.log('warn', message, data);
  }

  /**
   * Log error message (red, bold)
   * Use for: Connection failures, API errors, exceptions
   */
  error(message: string, data?: any): void {
    this.log('error', message, data);
  }

  /**
   * Get all stored logs
   */
  getLogs(): LogEntry[] {
    return [...this.logs];
  }

  /**
   * Clear all stored logs
   */
  clear(): void {
    this.logs = [];
    this.info('Logs cleared');
  }
}

// Singleton instance
export const logger = new Logger();
