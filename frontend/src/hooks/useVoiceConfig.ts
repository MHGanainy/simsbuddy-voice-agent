/**
 * Custom hook for managing voice configuration
 *
 * Handles fetching, updating, and caching voice preferences
 */

import { useState, useEffect, useCallback } from 'react';

const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL || 'http://localhost:8080';

export interface Voice {
  id: string;
  name: string;
  language: string;
  gender: string;
  age: string;
  description: string;
  category: string;
  tier: string;
  tags: string[];
}

export interface VoiceConfig {
  userId: string;
  voiceId: string;
  openingLine: string;
  voice: Voice;
  updatedAt?: number;
  isDefault?: boolean;
}

export interface VoiceFilters {
  language?: string;
  category?: string;
  tier?: string;
}

export interface UseVoiceConfigReturn {
  config: VoiceConfig | null;
  voices: Voice[];
  groupedVoices: Record<string, Voice[]>;
  isLoading: boolean;
  error: string | null;
  fetchVoices: (filters?: VoiceFilters) => Promise<void>;
  fetchConfig: () => Promise<void>;
  updateConfig: (voiceId: string, openingLine: string) => Promise<boolean>;
  resetToDefault: () => Promise<void>;
}

export function useVoiceConfig(userId: string | null): UseVoiceConfigReturn {
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [groupedVoices, setGroupedVoices] = useState<Record<string, Voice[]>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch available voices from API
   */
  const fetchVoices = useCallback(async (filters?: VoiceFilters) => {
    setIsLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (filters?.language) params.append('language', filters.language);
      if (filters?.category) params.append('category', filters.category);
      if (filters?.tier) params.append('tier', filters.tier);

      const url = `${ORCHESTRATOR_URL}/api/voices${params.toString() ? `?${params}` : ''}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Failed to fetch voices: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        setVoices(data.voices || []);
        setGroupedVoices(data.groupedVoices || {});
      } else {
        throw new Error(data.error || 'Failed to fetch voices');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(message);
      console.error('Error fetching voices:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  /**
   * Fetch user's current voice configuration
   */
  const fetchConfig = useCallback(async () => {
    if (!userId) return;

    setIsLoading(true);
    setError(null);

    try {
      const url = `${ORCHESTRATOR_URL}/api/agent/configure/${userId}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Failed to fetch configuration: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        setConfig(data.config);
      } else {
        throw new Error(data.error || 'Failed to fetch configuration');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(message);
      console.error('Error fetching config:', err);
    } finally {
      setIsLoading(false);
    }
  }, [userId]);

  /**
   * Update user's voice configuration
   */
  const updateConfig = useCallback(async (voiceId: string, openingLine: string): Promise<boolean> => {
    if (!userId) {
      setError('User ID is required');
      return false;
    }

    setIsLoading(true);
    setError(null);

    try {
      const url = `${ORCHESTRATOR_URL}/api/agent/configure`;
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          userId,
          voiceId,
          openingLine,
          userTier: 'free', // TODO: Get from user profile
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || `Failed to update configuration: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        setConfig(data.config);
        console.log('Voice configuration updated successfully');
        return true;
      } else {
        throw new Error(data.error || 'Failed to update configuration');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(message);
      console.error('Error updating config:', err);
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [userId]);

  /**
   * Reset to default voice and opening line
   */
  const resetToDefault = useCallback(async () => {
    if (!userId) return;

    const defaultVoiceId = 'Ashley';
    const defaultOpeningLine = "Hello! I'm Ashley, your AI assistant. How can I help you today?";

    await updateConfig(defaultVoiceId, defaultOpeningLine);
  }, [userId, updateConfig]);

  // Fetch voices on mount
  useEffect(() => {
    fetchVoices();
  }, [fetchVoices]);

  // Fetch config when userId changes
  useEffect(() => {
    if (userId) {
      fetchConfig();
    }
  }, [userId, fetchConfig]);

  return {
    config,
    voices,
    groupedVoices,
    isLoading,
    error,
    fetchVoices,
    fetchConfig,
    updateConfig,
    resetToDefault,
  };
}
