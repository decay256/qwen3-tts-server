/** Shared API types. */

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
  runpod_available?: boolean;
  error?: string;
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

/** Connection status with details */
export interface ConnectionInfo {
  gpu_tunnel: boolean;
  runpod: 'ready' | 'cold' | 'unavailable' | 'unknown';
  active_backend: 'tunnel' | 'runpod' | 'none';
  error?: string;
  runpod_workers?: { ready: number; idle: number; initializing: number };
}
