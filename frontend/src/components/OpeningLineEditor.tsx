/**
 * OpeningLineEditor Component
 *
 * Text editor for customizing the agent's opening greeting
 */

import React, { useState, useEffect } from 'react';
import './OpeningLineEditor.css';

interface OpeningLineEditorProps {
  voiceId: string;
  voiceName: string;
  value: string;
  defaultValue: string;
  onChange: (text: string) => void;
  disabled?: boolean;
}

const MIN_LENGTH = 5;
const MAX_LENGTH = 500;

export function OpeningLineEditor({
  voiceId,
  voiceName,
  value,
  defaultValue,
  onChange,
  disabled = false,
}: OpeningLineEditorProps) {
  const [text, setText] = useState(value);
  const [error, setError] = useState<string>('');
  const [showTemplates, setShowTemplates] = useState(false);

  // Update local text when value prop changes
  useEffect(() => {
    setText(value);
  }, [value]);

  // Validation
  useEffect(() => {
    if (text.length === 0) {
      setError('');
      return;
    }

    if (text.length < MIN_LENGTH) {
      setError(`Opening line must be at least ${MIN_LENGTH} characters`);
      return;
    }

    if (text.length > MAX_LENGTH) {
      setError(`Opening line must not exceed ${MAX_LENGTH} characters`);
      return;
    }

    // Check for unsupported characters
    if (/<|>/.test(text)) {
      setError('Opening line cannot contain HTML tags');
      return;
    }

    if (/\{|\}/.test(text)) {
      setError('Opening line cannot contain template literals');
      return;
    }

    setError('');
  }, [text]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newText = e.target.value;
    setText(newText);
    onChange(newText);
  };

  const handleReset = () => {
    setText(defaultValue);
    onChange(defaultValue);
  };

  const handleTemplateSelect = (template: string) => {
    setText(template);
    onChange(template);
    setShowTemplates(false);
  };

  // Template suggestions based on voice category/personality
  const templates = [
    `Hello! I'm ${voiceName}, your AI assistant. How can I help you today?`,
    `Hey there! I'm ${voiceName}. What can I do for you?`,
    `Good day! I'm ${voiceName}, ready to assist. What's on your mind?`,
    `Hi! ${voiceName} here. How may I help you?`,
  ];

  const isValid = !error && text.length >= MIN_LENGTH && text.length <= MAX_LENGTH;
  const characterCount = text.length;
  const characterCountClass =
    characterCount < MIN_LENGTH ? 'too-short' :
    characterCount > MAX_LENGTH * 0.9 ? 'near-limit' :
    'valid';

  return (
    <div className="opening-line-editor">
      <div className="editor-header">
        <h4>Customize Opening Line</h4>
        <button
          className="templates-toggle"
          onClick={() => setShowTemplates(!showTemplates)}
          disabled={disabled}
        >
          💡 Suggestions
        </button>
      </div>

      {showTemplates && (
        <div className="template-suggestions">
          <p className="template-label">Template Suggestions:</p>
          {templates.map((template, index) => (
            <button
              key={index}
              className="template-button"
              onClick={() => handleTemplateSelect(template)}
              disabled={disabled}
            >
              "{template}"
            </button>
          ))}
        </div>
      )}

      <div className="editor-body">
        <textarea
          className={`opening-line-textarea ${error ? 'error' : isValid ? 'valid' : ''}`}
          value={text}
          onChange={handleChange}
          placeholder={`Enter the greeting ${voiceName} will speak when users join...`}
          disabled={disabled}
          rows={3}
        />

        <div className="editor-footer">
          <div className="character-count">
            <span className={characterCountClass}>
              {characterCount} / {MAX_LENGTH}
            </span>
            {characterCount < MIN_LENGTH && characterCount > 0 && (
              <span className="hint">
                 ({MIN_LENGTH - characterCount} more needed)
              </span>
            )}
          </div>

          {error && (
            <div className="error-message">
              ⚠️ {error}
            </div>
          )}

          {!error && isValid && (
            <div className="success-message">
              ✓ Opening line looks good!
            </div>
          )}
        </div>

        <div className="editor-actions">
          <button
            className="reset-button"
            onClick={handleReset}
            disabled={disabled || text === defaultValue}
          >
            ↺ Reset to Default
          </button>
        </div>
      </div>

      <div className="editor-info">
        <p className="info-text">
          💡 <strong>Tip:</strong> Keep it friendly and concise. This is the first thing users will hear!
        </p>
      </div>
    </div>
  );
}
