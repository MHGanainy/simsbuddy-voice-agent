// Shared TypeScript types for the voice agent interface

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  timestamp: Date;
  level: LogLevel;
  message: string;
  sessionId?: string;
  data?: any;
}

export interface SessionResponse {
  sessionId: string;
  token: string;
  serverUrl: string;
  roomName: string;
  participantName: string;
}

export interface VoiceOption {
  id: string;
  name: string;
  provider: string;
}

export interface VoiceSettings {
  voiceId: string;
  openingLine: string;
}
