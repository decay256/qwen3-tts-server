# Issue #18 — Contract Gap Findings

**Author:** Architect agent  
**Date:** 2026-03-01  
**Branch:** sprint2/contracts  

---

## Summary

Audit of the relay → web-proxy → frontend data flow for `GET /api/v1/tts/status` and `POST /api/v1/tts/warmup`. Three gaps found; one requires action from the backend engineer (#17).

---

## 1. Web Proxy — `runpod_health` Pass-Through

**Question:** Does `web/app/routes/tts.py` forward `runpod_health` from the relay, or does it strip it?

**Finding: FORWARDED in normal operation; STRIPPED in error fallback.**

### Normal path (relay reachable)

```python
# web/app/routes/tts.py — get_status()
return await tts_proxy.tts_get("/api/v1/tts/status")
```

`tts_proxy.tts_get` calls `resp.json()` and returns the raw dict verbatim. The relay's `handle_tts_status` includes `runpod_health` when RunPod is configured. Therefore **`runpod_health` is forwarded** to the frontend unchanged.

### Error fallback (relay unreachable)

```python
except TTSRelayError as e:
    return {
        "status": "error",
        "tunnel_connected": False,
        "models_loaded": [],
        "prompts_count": 0,
        "runpod_configured": False,
        "runpod_available": False,
        "error": e.detail,
    }
```

`runpod_health` is absent from the error response. **This is intentional and correct** — when the relay is unreachable we cannot know RunPod state. The frontend must handle `runpod_health` being absent.

**Action required for #17:** None. Pass-through is correct.

---

## 2. `TTSStatus.runpod_health` Typed as `unknown`

**File:** `frontend/src/api/types.ts`

```typescript
export interface TTSStatus {
  // ...
  runpod_health?: unknown;   // ← not typed to actual shape
}
```

**Finding:** The actual shape is the full RunPod `/health` response:

```typescript
interface RunPodHealth {
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
```

**Action required for #17 (backend/frontend):** Replace `runpod_health?: unknown` with `runpod_health?: RunPodHealth` and export `RunPodHealth` from `types.ts`. This enables the frontend to display worker counts in the connection status banner.

---

## 3. `ConnectionInfo.runpod_workers` in `types.ts` Is Unused

**File:** `frontend/src/api/types.ts`

```typescript
export interface ConnectionInfo {
  gpu_tunnel: boolean;
  runpod: 'ready' | 'cold' | 'unavailable' | 'unknown';
  active_backend: 'tunnel' | 'runpod' | 'none';
  error?: string;
  runpod_workers?: { ready: number; idle: number; initializing: number };  // ← defined but unused
}
```

**Finding:** `ConnectionStatus.tsx` defines its own local `ConnectionInfo` type (different shape) and does not import or use the exported one from `types.ts`. The exported `ConnectionInfo` type is dead code. `parseStatus()` in `ConnectionStatus.tsx` also does not read `runpod_health.workers` — it only uses `runpod_available` (a bool already computed by the relay).

**Action required for #17 (frontend):**
- Delete or update the exported `ConnectionInfo` type in `types.ts` — it conflicts with the local definition in `ConnectionStatus.tsx`.
- If worker counts should be shown in the UI (e.g. "2 workers ready"), the component needs to read `ttsStatus.runpod_health?.workers` and pass it through. This is a UX decision.

---

## 4. `GET /api/v1/status` vs `GET /api/v1/tts/status` — Endpoint Confusion

**Finding:** Two status endpoints exist with overlapping purpose:

| Endpoint | Handler | Response |
|---|---|---|
| `GET /api/v1/status` | `handle_status` | relay introspection + `local` sub-object |
| `GET /api/v1/tts/status` | `handle_tts_status` | flat merged view for frontend |

The web proxy correctly uses `/api/v1/tts/status`. The old `/api/v1/status` is used only for relay introspection (and forwarded to local GPU for tunnel health). This is correct — but the relay-api.yaml contract previously only documented `/api/v1/status`, leaving the frontend endpoint undocumented.

**Resolution:** Both endpoints now documented in `contracts/relay-api.yaml` v1.1.

---

## 5. `POST /api/v1/voices/design` — Optional Fields Present in Code, Missing from Contract

**Finding:** `web/app/routes/tts.py` `DesignRequest` already includes `create_prompt`, `prompt_name`, `tags` (added in Sprint 1, PR #15). The relay-api.yaml contract did not document these fields.

**Resolution:** Fields added to contract v1.1.

---

## Action Items for #17 (Backend Engineer)

| Priority | Action | File |
|---|---|---|
| P1 | Type `runpod_health` properly in `TTSStatus` | `frontend/src/api/types.ts` |
| P2 | Remove or reconcile duplicate `ConnectionInfo` export | `frontend/src/api/types.ts` |
| P3 | (optional) Surface worker counts in `ConnectionStatus.tsx` | `frontend/src/components/ConnectionStatus.tsx` |

---

## Research Log

- Read `server/remote_relay.py` lines 373–503: `_get_runpod_status`, `handle_status`, `handle_warmup`, `handle_tts_status`
- Read `web/app/routes/tts.py`: confirmed `tts_proxy.tts_get` returns raw JSON verbatim
- Read `web/app/services/tts_proxy.py`: confirmed `tts_get` calls `resp.json()` and returns full dict
- Read `frontend/src/api/types.ts`: found `TTSStatus.runpod_health?: unknown`, dead `ConnectionInfo` export
- Read `frontend/src/components/ConnectionStatus.tsx`: confirmed `parseStatus()` only uses `runpod_available` bool, not `runpod_health.workers`
- Read `server/runpod_client.py`: confirmed `health()` returns raw RunPod API response
- RunPod health API shape inferred from `_get_runpod_status` field access + RunPod API v2 spec
