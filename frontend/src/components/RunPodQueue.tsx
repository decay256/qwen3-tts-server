/** RunPodQueue — detailed worker + job queue visibility panel.
 *
 *  Reads TTSStatus from BackendContext (populated by ConnectionStatus polling).
 *  Only rendered when RunPod is configured. Collapses by default.
 *  Sprint 3 — issue #23.
 */

import { useState } from 'react';
import { useBackend } from '../context/BackendContext';

interface WorkerRowProps {
  label: string;
  count: number;
  color?: string;
  title?: string;
}

function WorkerRow({ label, count, color, title }: WorkerRowProps) {
  return (
    <div className="queue-row" title={title}>
      <span className="queue-label">{label}</span>
      <span className="queue-count" style={color ? { color } : undefined}>{count}</span>
    </div>
  );
}

function EstimatedWait({ queued, running }: { queued: number; running: number }) {
  if (queued === 0) return null;
  // Rough estimate: assume each job takes ~30s, workers process in parallel
  const activeWorkers = Math.max(running, 1);
  const batchesAhead = Math.ceil(queued / activeWorkers);
  const estimatedSec = batchesAhead * 30;
  const estimatedStr = estimatedSec < 60
    ? `~${estimatedSec}s`
    : `~${Math.ceil(estimatedSec / 60)}min`;
  return (
    <div className="queue-wait" title="Rough estimate based on ~30s per job">
      ⏱ Estimated wait: <strong>{estimatedStr}</strong>
      <span className="queue-wait-note">(estimate)</span>
    </div>
  );
}

export function RunPodQueue() {
  const { ttsStatus } = useBackend();
  const [expanded, setExpanded] = useState(false);

  if (!ttsStatus?.runpod_configured) return null;

  const health = ttsStatus.runpod_health;
  // Only show if we have actual health data (not the error variant)
  if (!health || !('workers' in health)) return null;

  const w = health.workers ?? {};
  const j = health.jobs ?? {};

  const totalWorkers = (w.ready ?? 0) + (w.idle ?? 0) + (w.initializing ?? 0) + (w.running ?? 0);
  const queuedJobs = j.queued ?? 0;

  return (
    <div className="runpod-queue">
      <button
        className="queue-toggle btn-sm btn-secondary"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded ? '▾' : '▸'} RunPod Queue
        {queuedJobs > 0 && (
          <span className="queue-badge" title="Jobs waiting for a worker">
            {queuedJobs} queued
          </span>
        )}
        {!expanded && totalWorkers > 0 && queuedJobs === 0 && (
          <span className="queue-badge queue-badge-ok">{totalWorkers} worker{totalWorkers !== 1 ? 's' : ''}</span>
        )}
      </button>

      {expanded && (
        <div className="queue-details">
          {/* Worker status */}
          <div className="queue-section">
            <div className="queue-section-title">Workers (max 4)</div>
            <WorkerRow label="Ready" count={w.ready ?? 0} color="var(--success)" title="Warm, unassigned" />
            <WorkerRow label="Idle" count={w.idle ?? 0} color="var(--success)" title="Idle, ready to accept jobs" />
            <WorkerRow label="Running" count={w.running ?? 0} color="var(--info, #3b82f6)" title="Actively processing a job" />
            <WorkerRow label="Initializing" count={w.initializing ?? 0} color="var(--warning)" title="Cold-start in progress" />
            {(w.throttled ?? 0) > 0 && (
              <WorkerRow label="Throttled" count={w.throttled ?? 0} color="var(--warning)" title="Throttled by RunPod platform" />
            )}
            {(w.unhealthy ?? 0) > 0 && (
              <WorkerRow label="Unhealthy" count={w.unhealthy ?? 0} color="var(--danger)" title="Workers in error state" />
            )}
          </div>

          {/* Job queue */}
          <div className="queue-section">
            <div className="queue-section-title">Jobs</div>
            <WorkerRow label="In queue" count={queuedJobs} color={queuedJobs > 0 ? 'var(--warning)' : undefined} title="Waiting for a worker" />
            <WorkerRow label="In progress" count={j.inProgress ?? 0} color="var(--info, #3b82f6)" title="Currently executing" />
            <WorkerRow label="Completed" count={j.completed ?? 0} title="Finished successfully" />
            {(j.failed ?? 0) > 0 && (
              <WorkerRow label="Failed" count={j.failed ?? 0} color="var(--danger)" title="Failed jobs" />
            )}
          </div>

          <EstimatedWait queued={queuedJobs} running={w.running ?? 0} />
        </div>
      )}
    </div>
  );
}
