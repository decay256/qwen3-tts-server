/** Connection status banner — shows GPU backend state and errors.
 *  Auto-polls: 30s when disconnected/cold/error, 60s when connected.
 *  Flashes on status transitions; shows "last checked Xs ago".
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiJson } from '../api/client';
import type { TTSStatus } from '../api/types';
import { useBackend, type BackendStatus } from '../context/BackendContext';

interface ConnectionInfo {
  status: 'connected' | 'cold-start' | 'busy' | 'disconnected' | 'error';
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
    const w = s.runpod_health?.workers;

    if (w && (w.idle > 0 || w.ready > 0)) {
      const readyCount = w.idle + w.ready;
      const inQueue = s.runpod_health?.jobs?.queued ?? 0;
      return {
        status: 'connected',
        label: 'RunPod Ready',
        detail: `${readyCount} worker${readyCount !== 1 ? 's' : ''} ready · ${inQueue} in queue`,
        canWarm: false,
      };
    }

    if (w && w.initializing > 0) {
      return {
        status: 'cold-start',
        label: 'RunPod Starting...',
        detail: `${w.initializing} worker${w.initializing !== 1 ? 's' : ''} initializing — will be ready shortly.`,
        canWarm: false,
      };
    }

    if (w && w.running > 0 && w.idle === 0 && w.ready === 0) {
      // Workers exist but are all processing jobs — queue overflow state
      const inQueue = s.runpod_health?.jobs?.queued ?? 0;
      return {
        status: 'busy',
        label: `RunPod Busy (${w.running} worker${w.running !== 1 ? 's' : ''} active)`,
        detail: inQueue > 0
          ? `All workers processing jobs · ${inQueue} job${inQueue !== 1 ? 's' : ''} in queue`
          : 'All workers processing jobs · new requests will queue',
        canWarm: false,
      };
    }

    if (w) {
      // health present but all worker counts are zero
      return {
        status: 'cold-start',
        label: 'RunPod Available (cold)',
        detail: 'No workers active. Click Warm Up to start a worker.',
        canWarm: true,
      };
    }

    // runpod_health absent (relay unreachable or not yet returned health data)
    return {
      status: 'cold-start',
      label: 'RunPod Fallback',
      detail: 'GPU tunnel disconnected. RunPod configured — first request may take ~30s (cold start).',
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
  const { setStatus: setBackendStatus, setTtsStatus: setContextTtsStatus } = useBackend();

  const checkStatus = useCallback(async () => {
    try {
      const s = await apiJson<TTSStatus>('/api/v1/tts/status');
      setTtsStatus(s);
      setContextTtsStatus(s);
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
  }, [setContextTtsStatus]);

  // Initial fetch on mount
  useEffect(() => { checkStatus(); }, [checkStatus]);

  // Derive current info
  const info = parseStatus(ttsStatus, fetchError ?? undefined);
  // Sprint 5: poll every 3s on all status (was adaptive 30s/60s)
  const POLL_INTERVAL_MS = 3_000;

  // Polling — 3s constant
  useEffect(() => {
    const id = setInterval(checkStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [checkStatus]);

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

      // Worker is ready when tunnel connects or RunPod has idle/ready workers
      const rw = s?.runpod_health?.workers;
      const ready = s?.tunnel_connected || (rw && (rw.idle > 0 || rw.ready > 0));

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
    busy: 'var(--info, #3b82f6)',
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
