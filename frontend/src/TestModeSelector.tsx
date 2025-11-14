import { useState, useEffect } from 'react';

export type SpawnMode = 'direct-agent' | 'direct' | 'orchestrator';

interface TestModeSelectorProps {
  value: SpawnMode;
  onChange: (mode: SpawnMode) => void;
  disabled?: boolean;
}

export default function TestModeSelector({ value, onChange, disabled }: TestModeSelectorProps) {
  const modes: { value: SpawnMode; label: string; description: string }[] = [
    {
      value: 'direct-agent',
      label: 'Direct Agent',
      description: 'Standalone agent server - no orchestrator (fastest, <1s)'
    },
    {
      value: 'direct',
      label: 'Direct Mode',
      description: 'Orchestrator with direct spawn (~5s)'
    },
    {
      value: 'orchestrator',
      label: 'Orchestrator Mode',
      description: 'Full flow with Celery queue (~10s)'
    }
  ];

  return (
    <div className="test-mode-selector">
      <label className="test-mode-label">Testing Mode:</label>
      <div className="mode-options">
        {modes.map(mode => (
          <button
            key={mode.value}
            className={`mode-button ${value === mode.value ? 'active' : ''}`}
            onClick={() => onChange(mode.value)}
            disabled={disabled}
            title={mode.description}
          >
            <span className="mode-label">{mode.label}</span>
            <span className="mode-description">{mode.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
