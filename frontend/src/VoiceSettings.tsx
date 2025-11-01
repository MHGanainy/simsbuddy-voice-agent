import { useState } from 'react';
import { VoiceSettings as VoiceSettingsType } from './types';
import { logger } from './logger';

interface VoiceSettingsProps {
  settings: VoiceSettingsType;
  onSettingsChange: (settings: VoiceSettingsType) => void;
}

/**
 * Simplified voice settings component
 * Replaces 585 lines of VoiceConfiguration/VoicePicker/OpeningLineEditor
 * with simple dropdown + text input (~80 lines)
 */
export default function VoiceSettings({ settings, onSettingsChange }: VoiceSettingsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Available Inworld TTS voices (configured with speed optimization)
  const availableVoices = [
    { id: 'Ashley', name: 'Ashley (Default) - Warm, natural female' },
    { id: 'Craig', name: 'Craig (Fast) - Professional male' },
    { id: 'Edward', name: 'Edward - Smooth, natural male' },
    { id: 'Olivia', name: 'Olivia - Clear, professional female' },
    { id: 'Wendy', name: 'Wendy (Fast) - Energetic female' },
    { id: 'Priya', name: 'Priya (Asian) - Warm, clear female' },
  ];

  const handleVoiceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newVoiceId = e.target.value;
    logger.info('Voice changed', { voiceId: newVoiceId });
    onSettingsChange({ ...settings, voiceId: newVoiceId });
  };

  const handleOpeningLineChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newLine = e.target.value;
    onSettingsChange({ ...settings, openingLine: newLine });
  };

  const handleSystemPromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newPrompt = e.target.value;
    onSettingsChange({ ...settings, systemPrompt: newPrompt });
  };

  const handleReset = () => {
    const defaults: VoiceSettingsType = {
      voiceId: 'Ashley',
      openingLine: 'Hello! How can I help you today?',
      systemPrompt: ''
    };
    logger.info('Voice settings reset to defaults');
    onSettingsChange(defaults);
  };

  return (
    <div className="voice-settings">
      <div className="voice-settings-header" onClick={() => setIsExpanded(!isExpanded)}>
        <h3>Voice Settings {isExpanded ? '▼' : '▶'}</h3>
      </div>

      {isExpanded && (
        <div className="voice-settings-content">
          <div className="voice-settings-field">
            <label htmlFor="voice-select">Voice:</label>
            <select
              id="voice-select"
              value={settings.voiceId}
              onChange={handleVoiceChange}
            >
              {availableVoices.map(voice => (
                <option key={voice.id} value={voice.id}>
                  {voice.name}
                </option>
              ))}
            </select>
          </div>

          <div className="voice-settings-field">
            <label htmlFor="opening-line">Opening Line:</label>
            <input
              id="opening-line"
              type="text"
              value={settings.openingLine}
              onChange={handleOpeningLineChange}
              placeholder="Enter opening greeting..."
              maxLength={500}
            />
            <span className="voice-settings-hint">
              {settings.openingLine.length}/500 characters
            </span>
          </div>

          <div className="voice-settings-field">
            <label htmlFor="system-prompt">
              System Prompt:
              <span className="voice-settings-optional"> (optional)</span>
            </label>
            <textarea
              id="system-prompt"
              value={settings.systemPrompt || ''}
              onChange={handleSystemPromptChange}
              placeholder="You are a helpful AI assistant. Customize the AI's personality and behavior here..."
              maxLength={2000}
              rows={4}
            />
            <span className="voice-settings-hint">
              {(settings.systemPrompt || '').length}/2000 characters - Leave empty to use default
            </span>
          </div>

          <div className="voice-settings-actions">
            <button onClick={handleReset} className="secondary">
              Reset to Defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
