/**
 * VoicePicker Component
 *
 * Grid view of available Inworld TTS voices with filtering and selection
 */

import React, { useState, useMemo } from 'react';
import type { Voice } from '../hooks/useVoiceConfig';
import './VoicePicker.css';

interface VoicePickerProps {
  voices: Voice[];
  groupedVoices: Record<string, Voice[]>;
  selectedVoiceId: string;
  onVoiceSelect: (voice: Voice) => void;
  userTier?: string;
  disabled?: boolean;
}

const CATEGORY_LABELS: Record<string, string> = {
  professional: '👔 Professional',
  educational: '📚 Educational',
  character: '🎭 Character',
  assistant: '🤖 Assistant',
};

const LANGUAGE_LABELS: Record<string, string> = {
  en: '🇺🇸 English',
  es: '🇪🇸 Spanish',
  fr: '🇫🇷 French',
  ko: '🇰🇷 Korean',
  zh: '🇨🇳 Chinese',
  nl: '🇳🇱 Dutch',
};

export function VoicePicker({
  voices,
  groupedVoices,
  selectedVoiceId,
  onVoiceSelect,
  userTier = 'free',
  disabled = false,
}: VoicePickerProps) {
  const [languageFilter, setLanguageFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  // Get unique languages from voices
  const availableLanguages = useMemo(() => {
    const langs = new Set(voices.map(v => v.language));
    return Array.from(langs);
  }, [voices]);

  // Filter voices
  const filteredVoices = useMemo(() => {
    return voices.filter(voice => {
      if (languageFilter !== 'all' && voice.language !== languageFilter) {
        return false;
      }
      if (categoryFilter !== 'all' && voice.category !== categoryFilter) {
        return false;
      }
      return true;
    });
  }, [voices, languageFilter, categoryFilter]);

  // Check if voice is accessible for user tier
  const isVoiceAccessible = (voice: Voice): boolean => {
    if (voice.tier === 'free') return true;
    if (voice.tier === 'premium' && (userTier === 'premium' || userTier === 'enterprise')) return true;
    if (voice.tier === 'enterprise' && userTier === 'enterprise') return true;
    return false;
  };

  const handleVoiceClick = (voice: Voice) => {
    if (disabled) return;

    if (!isVoiceAccessible(voice)) {
      alert(`This voice requires a ${voice.tier} subscription`);
      return;
    }

    onVoiceSelect(voice);
  };

  return (
    <div className="voice-picker">
      <div className="voice-picker-header">
        <h3>Select Voice</h3>
        <div className="voice-picker-controls">
          {/* Language Filter */}
          <select
            value={languageFilter}
            onChange={(e) => setLanguageFilter(e.target.value)}
            className="filter-select"
            disabled={disabled}
          >
            <option value="all">All Languages</option>
            {availableLanguages.map(lang => (
              <option key={lang} value={lang}>
                {LANGUAGE_LABELS[lang] || lang.toUpperCase()}
              </option>
            ))}
          </select>

          {/* Category Filter */}
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="filter-select"
            disabled={disabled}
          >
            <option value="all">All Categories</option>
            {Object.keys(CATEGORY_LABELS).map(cat => (
              <option key={cat} value={cat}>
                {CATEGORY_LABELS[cat]}
              </option>
            ))}
          </select>

          {/* View Mode Toggle */}
          <div className="view-toggle">
            <button
              className={viewMode === 'grid' ? 'active' : ''}
              onClick={() => setViewMode('grid')}
              disabled={disabled}
              title="Grid view"
            >
              ⊞
            </button>
            <button
              className={viewMode === 'list' ? 'active' : ''}
              onClick={() => setViewMode('list')}
              disabled={disabled}
              title="List view"
            >
              ☰
            </button>
          </div>
        </div>
      </div>

      <div className={`voice-picker-content ${viewMode}`}>
        {filteredVoices.length === 0 ? (
          <div className="no-voices">
            <p>No voices match your filters</p>
          </div>
        ) : (
          filteredVoices.map(voice => {
            const isSelected = voice.id === selectedVoiceId;
            const accessible = isVoiceAccessible(voice);

            return (
              <div
                key={voice.id}
                className={`voice-card ${isSelected ? 'selected' : ''} ${!accessible ? 'locked' : ''} ${disabled ? 'disabled' : ''}`}
                onClick={() => handleVoiceClick(voice)}
              >
                <div className="voice-card-header">
                  <div className="voice-info">
                    <h4>{voice.name}</h4>
                    <div className="voice-meta">
                      <span className="voice-gender">{voice.gender}</span>
                      <span className="voice-age">{voice.age}</span>
                      <span className="voice-language">{LANGUAGE_LABELS[voice.language] || voice.language}</span>
                    </div>
                  </div>
                  <div className="voice-badges">
                    {voice.tier !== 'free' && (
                      <span className={`tier-badge ${voice.tier}`}>
                        {voice.tier === 'premium' ? '⭐' : '💎'} {voice.tier}
                      </span>
                    )}
                    {!accessible && <span className="locked-badge">🔒</span>}
                    {isSelected && <span className="selected-badge">✓</span>}
                  </div>
                </div>

                <p className="voice-description">{voice.description}</p>

                <div className="voice-tags">
                  {voice.tags.slice(0, 3).map(tag => (
                    <span key={tag} className="voice-tag">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="voice-picker-footer">
        <p className="voice-count">
          Showing {filteredVoices.length} of {voices.length} voices
        </p>
      </div>
    </div>
  );
}
