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

  // Available Inworld TTS voices
  const availableVoices = [
    { id: 'Alex', name: 'Alex - Energetic male, mid-range' },
    { id: 'Ashley', name: 'Ashley - Warm, natural female' },
    { id: 'Dennis', name: 'Dennis - Smooth, calm male' },
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

  const handleReset = () => {
    const defaults: VoiceSettingsType = {
      voiceId: 'Ashley',
      openingLine: 'Hello! How can I help you today?'
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
