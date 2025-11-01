/**
 * VoiceConfiguration Component
 *
 * Container component that integrates VoicePicker and OpeningLineEditor
 */

import React, { useState, useEffect } from 'react';
import { useVoiceConfig, type Voice } from '../hooks/useVoiceConfig';
import { VoicePicker } from './VoicePicker';
import { OpeningLineEditor } from './OpeningLineEditor';
import './VoiceConfiguration.css';

interface VoiceConfigurationProps {
  userId: string;
  onConfigSaved?: (voiceId: string, openingLine: string) => void;
  disabled?: boolean;
}

export function VoiceConfiguration({
  userId,
  onConfigSaved,
  disabled = false,
}: VoiceConfigurationProps) {
  const {
    config,
    voices,
    groupedVoices,
    isLoading,
    error,
    updateConfig,
    resetToDefault,
  } = useVoiceConfig(userId);

  const [selectedVoice, setSelectedVoice] = useState<Voice | null>(null);
  const [openingLine, setOpeningLine] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');

  // Update state when config loads
  useEffect(() => {
    if (config) {
      setSelectedVoice(config.voice);
      setOpeningLine(config.openingLine);
    }
  }, [config]);

  const handleVoiceSelect = (voice: Voice) => {
    setSelectedVoice(voice);
    setSaveStatus('idle');

    // Auto-update opening line with voice-specific default if current one is generic
    if (config?.isDefault || openingLine === config?.openingLine) {
      const defaultLine = `Hello! I'm ${voice.name}, your AI assistant. How can I help you today?`;
      setOpeningLine(defaultLine);
    }
  };

  const handleOpeningLineChange = (text: string) => {
    setOpeningLine(text);
    setSaveStatus('idle');
  };

  const handleSave = async () => {
    if (!selectedVoice || !openingLine || openingLine.length < 5) {
      setSaveStatus('error');
      return;
    }

    setIsSaving(true);
    setSaveStatus('idle');

    try {
      const success = await updateConfig(selectedVoice.id, openingLine);

      if (success) {
        setSaveStatus('success');
        if (onConfigSaved) {
          onConfigSaved(selectedVoice.id, openingLine);
        }

        // Clear success message after 3 seconds
        setTimeout(() => {
          setSaveStatus('idle');
        }, 3000);
      } else {
        setSaveStatus('error');
      }
    } catch (err) {
      console.error('Error saving configuration:', err);
      setSaveStatus('error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    if (window.confirm('Reset to default voice (Ashley) and opening line?')) {
      setIsSaving(true);
      await resetToDefault();
      setIsSaving(false);
    }
  };

  const hasChanges =
    selectedVoice?.id !== config?.voiceId ||
    openingLine !== config?.openingLine;

  const defaultOpeningLine = selectedVoice
    ? `Hello! I'm ${selectedVoice.name}, your AI assistant. How can I help you today?`
    : '';

  return (
    <div className="voice-configuration">
      <div className="config-header">
        <h2>🎤 Voice Configuration</h2>
        <p className="config-subtitle">
          Customize the voice and opening greeting for your AI assistant
        </p>
      </div>

      {error && (
        <div className="config-error">
          <strong>⚠️ Error:</strong> {error}
        </div>
      )}

      {isLoading && voices.length === 0 ? (
        <div className="config-loading">
          <div className="spinner"></div>
          <p>Loading voice options...</p>
        </div>
      ) : (
        <>
          <VoicePicker
            voices={voices}
            groupedVoices={groupedVoices}
            selectedVoiceId={selectedVoice?.id || ''}
            onVoiceSelect={handleVoiceSelect}
            userTier="free"
            disabled={disabled || isSaving}
          />

          {selectedVoice && (
            <OpeningLineEditor
              voiceId={selectedVoice.id}
              voiceName={selectedVoice.name}
              value={openingLine}
              defaultValue={defaultOpeningLine}
              onChange={handleOpeningLineChange}
              disabled={disabled || isSaving}
            />
          )}

          <div className="config-actions">
            <button
              className="save-button"
              onClick={handleSave}
              disabled={disabled || isSaving || !hasChanges || !selectedVoice || openingLine.length < 5}
            >
              {isSaving ? (
                <>
                  <span className="spinner small"></span>
                  Saving...
                </>
              ) : (
                '💾 Save Configuration'
              )}
            </button>

            <button
              className="reset-all-button"
              onClick={handleReset}
              disabled={disabled || isSaving || config?.isDefault}
            >
              ↺ Reset All to Default
            </button>

            {saveStatus === 'success' && (
              <div className="save-success">
                ✓ Configuration saved successfully!
              </div>
            )}

            {saveStatus === 'error' && (
              <div className="save-error">
                ✗ Failed to save configuration
              </div>
            )}
          </div>

          {hasChanges && !isSaving && (
            <div className="unsaved-changes-notice">
              <strong>⚠️ Unsaved changes:</strong> Click "Save Configuration" to apply your changes
            </div>
          )}
        </>
      )}
    </div>
  );
}
