/** Connection status banner — shows GPU backend state and errors. */

import { useState, useEffect, useCallback } from 'react';
import { apiJson } from '../api/client';
import type { TTSStatus } from '../api/types';

interface ConnectionInfo {
  status: 'connected' | 'cold-start' | 'disconnected' | 'error';
  label: string;
  detail: string;
  canWarm: boolean;
}

function parseStatus(s: TTSStatus | null, err?: string): ConnectionInfo {
  if (err) return { status: 'error', label: 'Error', detail: err, canWarm: false };
  if (!s) return { status: 'disconnected', label: 'Checking...', detail: 'Fetching status', canWarm: false };

  if (s.tunnel_connected) {
    return {
      status: 'connected',
      label: 'GPU Connected',
      detail: `${s.models_loaded?.join(', ') || 'models loading'} · ${s.prompts_count ?? 0} prompts`,
      canWarm: false,
    };
  }

  // Tunnel disconnected — check if RunPod is configured / available
  if (s.runpod_configured) {
    if (s.runpod_available) {
      return {
        status: 'cold-start',
        label: 'RunPod Fallback',
        detail: 'GPU tunnel disconnected. RunPod available — first request may take ~30s (cold start).',
        canWarm: true,
      };
    }
    // Configured but workers not yet ready (still cold)
    return {
      status: 'cold-start',
      label: 'RunPod Fallback',
      detail: 'GPU tunnel disconnected. RunPod configured but no workers ready — click Warm Up to start.',
      canWarm: true,
    };
  }

  return {
    status: 'disconnected',
    label: 'No GPU Backend',
    detail: 'GPU tunnel disconnected, RunPod unavailable. Voice generation will fail.',
    canWarm: false,
  };
}

export function ConnectionStatus() {
  const [ttsStatus, setTtsStatus] = useState<TTSStatus | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [warming, setWarming] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const s = await apiJson<TTSStatus>('/api/v1/tts/status');
      setTtsStatus(s);
      setFetchError(null);
    } catch (e) {
      const msg = (e as Error).message;
      setFetchError(msg.includes('502') || msg.includes('503')
        ? 'TTS relay unreachable — server may be restarting'
        : msg);
    }
  }, []);

  useEffect(() => { checkStatus(); }, [checkStatus]);

  const warmUp = async () => {
    setWarming(true);
    try {
      // Fire a lightweight request to trigger cold start
      await apiJson('/api/v1/tts/status');
      await checkStatus();
    } catch {
      // ignore — status will update
    } finally {
      setWarming(false);
    }
  };

  const info = parseStatus(ttsStatus, fetchError ?? undefined);

  const statusColor = {
    connected: 'var(--success)',
    'cold-start': 'var(--warning)',
    disconnected: 'var(--danger)',
    error: 'var(--danger)',
  }[info.status];

  return (
    <div className="connection-status" style={{ borderLeft: `3px solid ${statusColor}` }}>
      <div className="conn-header">
        <span className="dot" style={{ background: statusColor }} />
        <strong>{info.label}</strong>
        {info.canWarm && (
          <button onClick={warmUp} disabled={warming} className="btn-sm btn-secondary" style={{ marginLeft: 8 }}>
            {warming ? '⏳ Warming...' : '🔥 Warm Up'}
          </button>
        )}
      </div>
      <div className="conn-detail">{info.detail}</div>
    </div>
  );
}
