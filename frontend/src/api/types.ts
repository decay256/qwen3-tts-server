/** Shared API types. */

/** Raw response from the RunPod /health endpoint. */
export interface RunPodHealth {
  workers: {
    ready: number;
    idle: number;
    initializing: number;
    running: number;
    throttled: number;
    unhealthy: number;
  };
  jobs: {
    queued: number;
    inProgress: number;
    completed: number;
    failed: number;
    retried: number;
    badfailed: number;
  };
}

export interface Character {
  id: string;
  name: string;
  base_description: string;
  created_at: string;
  updated_at: string;
}

export interface VoicePrompt {
  name: string;
  tags: string[];
  ref_text?: string;
  character?: string;
  emotion?: string;
  intensity?: string;
  description?: string;
  instruct?: string;
  base_description?: string;
  ref_audio_duration_s?: number;
}

export interface TTSStatus {
  status: string;
  tunnel_connected: boolean;
  models_loaded: string[];
  prompts_count: number;
  runpod_configured?: boolean;
  runpod_available?: boolean;
  runpod_health?: RunPodHealth;
  error?: string;
  local_error?: string;
}

export interface EmotionPreset {
  name: string;
  type: 'emotion';
  instruct_medium: string;
  instruct_intense: string;
  ref_text_medium: string;
  ref_text_intense: string;
  tags: string[];
  is_builtin: boolean;
}

export interface ModePreset {
  name: string;
  type: 'mode';
  instruct: string;
  ref_text: string;
  tags: string[];
  is_builtin: boolean;
}

export interface DesignResult {
  audio: string; // base64
  duration_s: number;
  format: string;
}

export interface RefineResult {
  new_instruct: string;
  new_base_description: string | null;
  explanation: string;
}

// NOTE: ConnectionInfo was removed — it was dead code that conflicted with
// the local ConnectionInfo defined in ConnectionStatus.tsx (different shape).
// See issue #17 / findings-issue-18-contract-gaps.md §3.

// ── Sprint 4: Draft Workflow & Character Templates ────────────────────────────

export type DraftStatus = 'pending' | 'generating' | 'ready' | 'failed' | 'approved';

/** Draft summary — returned by list endpoints (no audio_b64). */
export interface DraftSummary {
  id: string;
  user_id: string;
  character_id: string | null;
  character_name: string | null;
  preset_name: string;
  preset_type: string;
  intensity: string | null;
  text: string;
  instruct: string;
  language: string;
  status: DraftStatus;
  audio_format: string;
  duration_s: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

/** Full draft — returned by GET /api/v1/drafts/{id} (includes audio_b64). */
export interface Draft extends DraftSummary {
  audio_b64: string | null;
}

/** Template summary — returned by list endpoints (no audio_b64). */
export interface TemplateSummary {
  id: string;
  user_id: string;
  character_id: string;
  character_name: string | null;
  draft_id: string;
  name: string;
  preset_name: string;
  preset_type: string;
  intensity: string | null;
  instruct: string;
  text: string;
  audio_format: string;
  duration_s: number | null;
  language: string;
  created_at: string;
}

/** Full template — returned by GET /api/v1/templates/{id} (includes audio_b64). */
export interface Template extends TemplateSummary {
  audio_b64: string;
}
