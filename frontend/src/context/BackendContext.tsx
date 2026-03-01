/** Shared GPU backend availability state.
 *
 *  ConnectionStatus is the single writer — it polls /api/v1/tts/status and
 *  publishes the derived status here. Any component can read it without
 *  triggering extra API calls.
 */

import { createContext, useContext, useState, type ReactNode } from 'react';
import type { TTSStatus } from '../api/types';

export type BackendStatus =
  | 'checking'      // initial state before first poll completes
  | 'connected'     // GPU tunnel up
  | 'cold-start'    // RunPod configured/available but tunnel down
  | 'busy'          // RunPod workers all running, none idle — jobs will queue
  | 'disconnected'  // no tunnel, no RunPod
  | 'error';        // fetch error

interface BackendContextValue {
  status: BackendStatus;
  setStatus: (s: BackendStatus) => void;
  /** Raw TTSStatus from the last successful poll. Null before first fetch. */
  ttsStatus: TTSStatus | null;
  setTtsStatus: (s: TTSStatus | null) => void;
}

const BackendContext = createContext<BackendContextValue>({
  status: 'checking',
  setStatus: () => {},
  ttsStatus: null,
  setTtsStatus: () => {},
});

export function BackendProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>('checking');
  const [ttsStatus, setTtsStatus] = useState<TTSStatus | null>(null);
  return (
    <BackendContext.Provider value={{ status, setStatus, ttsStatus, setTtsStatus }}>
      {children}
    </BackendContext.Provider>
  );
}

export function useBackend(): BackendContextValue {
  return useContext(BackendContext);
}

/** True if the backend can accept requests (tunnel up, or RunPod available). */
export function backendReady(status: BackendStatus): boolean {
  return status === 'connected' || status === 'cold-start' || status === 'busy';
}
