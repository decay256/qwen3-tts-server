/** Connection status banner — shows GPU backend state and errors.
 *  Auto-polls: 30s when disconnected/cold/error, 60s when connected.
 *  Flashes on status transitions; shows "last checked Xs ago".
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiJson } from '../api/client';
import type { TTSStatus } from '../api/types';
import { useBackend, type BackendStatus } from '../context/BackendContext';

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

  if (s.runpod_configured) {
    if (s.runpod_available) {
      return {
        status: 'cold-start',
        label: 'RunPod Fallback',
        detail: 'GPU tunnel disconnected. RunPod available — first request may take ~30s (cold start).',
        canWarm: true,
      };
    }
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

/** Counts seconds since `lastChecked`, updating every second. */
function useSecondsAgo(lastChecked: number | null): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!lastChecked) return;
    const update = () => setSeconds(Math.round((Date.now() - lastChecked) / 1000));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [lastChecked]);
  return seconds;
}

/** Warmup phase labels shown to the user while polling for worker readiness. */
const WARMUP_PHASES = [
  'Warming up...',
  'Worker initializing...',
  'Worker initializing...',
  'Ready!',
] as const;

/** Max time (ms) to poll for worker readiness after a warmup request. */
const WARMUP_POLL_MAX_MS = 120_000;
/** Interval (ms) between status polls during warmup. */
const WARMUP_POLL_INTERVAL_MS = 5_000;

export function ConnectionStatus() {
  const [ttsStatus, setTtsStatus] = useState<TTSStatus | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [warming, setWarming] = useState(false);
  const [warmupLabel, setWarmupLabel] = useState<string>('🔥 Warm Up');
  const [lastChecked, setLastChecked] = useState<number | null>(null);
  const [flash, setFlash] = useState(false);
  const prevStatusRef = useRef<string | null>(null);
  const warmupPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const secondsAgo = useSecondsAgo(lastChecked);
  const { setStatus: setBackendStatus } = useBackend();

  const checkStatus = useCallback(async () => {
    try {
      const s = await apiJson<TTSStatus>('/api/v1/tts/status');
      setTtsStatus(s);
      setFetchError(null);
      return s;
    } catch (e) {
      const msg = (e as Error).message;
      setFetchError(msg.includes('502') || msg.includes('503')
        ? 'TTS relay unreachable — server may be restarting'
        : msg);
      return null;
    } finally {
      setLastChecked(Date.now());
    }
  }, []);

  // Initial fetch on mount
  useEffect(() => { checkStatus(); }, [checkStatus]);

  // Derive current info so we can compute the right poll interval
  const info = parseStatus(ttsStatus, fetchError ?? undefined);
  // 30s when not healthy, 60s when connected
  const pollInterval = info.status === 'connected' ? 60_000 : 30_000;

  // Adaptive polling — recreated whenever interval changes
  useEffect(() => {
    const id = setInterval(checkStatus, pollInterval);
    return () => clearInterval(id);
  }, [checkStatus, pollInterval]);

  // Flash banner on status transition (disconnected→connected etc.)
  useEffect(() => {
    const prev = prevStatusRef.current;
    const curr = info.status;
    prevStatusRef.current = curr;
    if (prev !== null && prev !== curr) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 1500);
      return () => clearTimeout(t);
    }
  }, [info.status]);

  // Publish status to shared BackendContext so other components can react
  useEffect(() => {
    setBackendStatus(info.status as BackendStatus);
  }, [info.status, setBackendStatus]);

  // Cleanup warmup polling on unmount
  useEffect(() => {
    return () => {
      if (warmupPollRef.current) clearInterval(warmupPollRef.current);
    };
  }, []);

  const warmUp = async () => {
    setWarming(true);
    setWarmupLabel('Warming up...');

    try {
      // POST to the real warmup endpoint — triggers RunPod worker allocation
      await apiJson('/api/v1/tts/warmup', { method: 'POST' });
    } catch {
      // If the endpoint fails, still try polling — worker may already be starting
    }

    // Poll status every 5s for up to 2 minutes to detect worker readiness
    const deadline = Date.now() + WARMUP_POLL_MAX_MS;
    let phaseIndex = 1; // start at "Worker initializing..." (phase 0 = "Warming up..." shown above)

    setWarmupLabel(WARMUP_PHASES[1]);

    if (warmupPollRef.current) clearInterval(warmupPollRef.current);

    warmupPollRef.current = setInterval(async () => {
      const s = await checkStatus();

      // Worker is ready when tunnel connects or RunPod has workers available
      const ready = s?.tunnel_connected || s?.runpod_available;

      if (ready) {
        setWarmupLabel('⚡ Ready!');
        setWarming(false);
        if (warmupPollRef.current) {
          clearInterval(warmupPollRef.current);
          warmupPollRef.current = null;
        }
        return;
      }

      // Advance phase label (cycle through initializing messages)
      phaseIndex = Math.min(phaseIndex + 1, WARMUP_PHASES.length - 2);
      setWarmupLabel(WARMUP_PHASES[phaseIndex]);

      // Stop polling after deadline
      if (Date.now() >= deadline) {
        setWarmupLabel('🔥 Warm Up');
        setWarming(false);
        if (warmupPollRef.current) {
          clearInterval(warmupPollRef.current);
          warmupPollRef.current = null;
        }
      }
    }, WARMUP_POLL_INTERVAL_MS);
  };

  const statusColor = {
    connected: 'var(--success)',
    'cold-start': 'var(--warning)',
    disconnected: 'var(--danger)',
    error: 'var(--danger)',
  }[info.status];

  return (
    <div
      className={`connection-status${flash ? ' conn-flash' : ''}`}
      style={{ borderLeft: `3px solid ${statusColor}` }}
    >
      <div className="conn-header">
        <span className="dot" style={{ background: statusColor }} />
        <strong>{info.label}</strong>
        <button
          onClick={checkStatus}
          className="btn-sm btn-secondary conn-refresh"
          title="Refresh status now"
        >
          ↻
        </button>
        {info.canWarm && (
          <button onClick={warmUp} disabled={warming} className="btn-sm btn-secondary">
            {warming ? `⏳ ${warmupLabel}` : '🔥 Warm Up'}
          </button>
        )}
      </div>
      <div className="conn-detail">{info.detail}</div>
      {lastChecked !== null && (
        <div className="conn-last-checked">Last checked: {secondsAgo}s ago</div>
      )}
    </div>
  );
}
