# Architect Review — Qwen3-TTS Server

**Date:** 2026-02-28  
**Reviewer:** Eigen (Architect Agent)  
**Scope:** Contracts vs implementation, interface consistency, architectural risk

---

## Executive Summary

The contracts are a reasonable description of intent, but the implementation has **drifted significantly**. The most critical issues are: (1) a **wrong-argument-order bug** in `runpod_slim.py` that will produce corrupt audio, (2) a **NameError crash** in `runpod_handler.py` on batch-with-prompts, (3) two incompatible RunPod handlers with conflicting endpoint schemes, and (4) unauthenticated debug endpoints leaking internal state. Architecture is sound for MVP scale but has no redundancy.

---

## 1. Contract Violations

### 1.1 `tts-engine.yaml` vs `tts_engine.py`

#### `generate_voice_clone` — wrong parameter name in contract

| | Contract | Implementation |
|---|---|---|
| Param 2 | `ref_audio_path: str` (file path) | `ref_audio_b64: str` (base64 string) |
| Extra params | — | `x_vector_only_mode: bool` (undocumented) |

The contract says the caller passes a **file path**. The implementation expects a **base64-encoded audio blob**. Every consumer of this interface must already know the real signature; the contract is dead.

#### `create_clone_prompt` — signature mismatch

| | Contract | Implementation |
|---|---|---|
| Params | `ref_audio_b64, name, ref_text, metadata` | `ref_audio_b64, ref_text, x_vector_only_mode` |
| `name` param | Required | **Absent** — engine does not accept or store a name |
| `metadata` param | Optional dict | **Absent** |
| Return type | `VoiceClonePromptItem` | `object` (untyped, first element of list) |

The contract says this method stores a named prompt. The engine does nothing of the sort — naming and storage are the caller's responsibility. Both `runpod_handler.py` and `runpod_slim.py` call `engine.create_clone_prompt()` with `name` as a positional argument, which silently maps to `ref_text`, corrupting the call.

#### `generate_voice_design` — parameter naming inconsistency

- Contract uses `description` for the voice description argument.  
- Engine method signature also uses `description` ✓  
- But the **relay contract** (`relay-api.yaml`) and **RunPod handler** both use `instruct` for the same field.  
- The engine internally passes its `description` arg as `instruct=description` to the model — so the wire field name and the engine param name are different. This will cause confusion when consumers read either contract.

#### Undocumented methods (implementation > contract)

The following methods exist in `tts_engine.py` but have no contract entry:

- `generate_custom_voice(text, speaker, instruct, language)` — built-in named speakers
- `generate_with_saved_voice(text, voice_name, language)` — legacy, **broken** (see §2.4)
- `save_voice(name, ref_audio_b64, ref_text, description)` — persists reference WAV
- `list_voices()` — enumerates saved + builtin voices
- `get_health()` — GPU/CPU telemetry

These are actively used by the relay (forwarded to local server) but invisible to contract consumers.

---

### 1.2 `relay-api.yaml` vs `remote_relay.py`

#### Endpoints in implementation but missing from contract

The relay exposes far more surface than the contract describes:

| Endpoint | Registered | In Contract? |
|---|---|---|
| `GET /api/v1/tts/voices` | ✓ | ✗ |
| `POST /api/v1/tts/synthesize` | ✓ | ✗ |
| `POST /api/v1/tts/clone` | ✓ | ✗ |
| `POST /api/v1/tts/design` | ✓ | ✗ |
| `DELETE /api/v1/tts/voices/{voice_id}` | ✓ | ✗ |
| `GET /api/v1/tts/voices/{voice_id}/package` | ✓ | ✗ |
| `POST /api/v1/tts/voices/import` | ✓ | ✗ |
| `POST /api/v1/tts/voices/sync` | ✓ | ✗ |
| `POST /api/v1/audio/normalize` | ✓ | ✗ |
| `GET /api/v1/voices/prompts/search` | ✓ | ✗ |
| `DELETE /api/v1/voices/prompts/{name}` | ✓ | ✗ |
| `POST /api/v1/voices/clone-prompt/batch` | ✓ | ✗ |

These aren't necessarily wrong to have — the contract is just stale.

#### Auth violation — debug endpoints are unauthenticated

Contract states `auth: required` for all endpoints. Implementation registers these **without any auth check**:

```python
app.router.add_get("/api/v1/debug", self.handle_debug_http)
app.router.add_get("/ws/debug", self.handle_debug_ws)
```

`/api/v1/debug` exposes: process memory RSS, tunnel connection state, all pending request IDs, uptime, and the last 50 debug events (which include request paths and body lengths). `/ws/debug` streams a live event feed. Both are publicly reachable on the droplet's port 9800.

#### `POST /api/v1/voices/clone-prompt` request body mismatch

| | Contract | `runpod_handler.py` actually expects |
|---|---|---|
| Fields | `audio, name, ref_text` | `audio, name, ref_text, character, emotion, intensity, description, instruct, base_description, tags` |

The expanded fields are consumed in `handle_clone_prompt_create` and passed as metadata. Contract consumers won't know about them.

---

## 2. Interface Inconsistencies

### 2.1 🔴 CRITICAL: Wrong argument order in `runpod_slim.py`

```python
# runpod_slim.py, endpoint /api/v1/tts/synthesize
wav_data, sr = engine.generate_voice_clone(ref_audio, ref_text, text, language)
```

`TTSEngine.generate_voice_clone` signature is:
```python
def generate_voice_clone(self, text, ref_audio_b64, ref_text, language, x_vector_only_mode)
```

The slim handler passes `ref_audio` (raw bytes, already decoded) as `text`, and `text` (the string to synthesize) as `ref_audio_b64`. The engine will then try to base64-decode the synthesis text string and write it as a WAV file. This will either raise an exception or produce garbage audio every time this path is hit.

Additionally, `ref_audio` is raw bytes but the engine expects a base64 string — it calls `base64.b64decode()` internally.

### 2.2 🔴 CRITICAL: NameError in `runpod_handler.py` batch path

```python
# handle_batch_design, inside loop, when create_prompts=True:
prompt_result = engine.create_clone_prompt(audio_data, item["name"], item["text"], metadata=metadata)
```

`audio_data` is never defined in this scope. The WAV bytes are in `audio_bytes` (returned by `_wav_to_bytes`). This will crash with `NameError: name 'audio_data' is not defined` any time `create_prompts=True`.

Separately: even if the name were fixed, passing synthesized WAV output as reference audio for clone prompt creation is conceptually wrong — you'd want the *original* reference audio, not the generated speech.

### 2.3 `create_clone_prompt` called incorrectly in both handlers

Both handlers pass `name` and decoded bytes where the engine expects base64:

```python
# runpod_handler.py
audio_bytes = base64.b64decode(body["audio"])          # already decoded
engine.create_clone_prompt(audio_bytes, body["name"], body.get("ref_text"), metadata=metadata)
#                          ^^^^^^^^^^^ bytes, not b64  ^^^^^^^^^^ maps to ref_text param, not name

# runpod_slim.py
ref_audio = base64.b64decode(body["audio"])            # already decoded
engine.create_clone_prompt(ref_audio, name, ref_text)
#                          ^^^^^^^^^ bytes, not b64     ^^ maps to ref_text param
```

Engine signature: `create_clone_prompt(ref_audio_b64: str, ref_text: str, x_vector_only_mode: bool)`.  
Result: `name` silently becomes `ref_text`, `ref_text` becomes `x_vector_only_mode`, and the engine tries to `base64.b64decode()` the raw bytes which either raises or produces garbage.

### 2.4 `generate_with_saved_voice` — broken legacy method

```python
wavs, sr = model.generate_voice_clone(
    text=text,
    language=language,
    reference_audio=str(self._voice_prompts[voice_name]),  # wrong kwarg name
)
```

The model API uses `ref_audio=` not `reference_audio=`. Above that, there's also dead code:
```python
prompt = self._voice_prompts[voice_name]  # assigned but never used
```

This method will raise `TypeError` on every call. It's marked "deprecated" in a comment but is registered in `list_voices()` behavior. If the relay ever forwards a request to it, it will 500.

### 2.5 Inconsistent duration field across paths

| Code path | Field name in response body | Maps to header |
|---|---|---|
| RunPod handler | `duration_s` | `X-Duration-Seconds` (relay maps correctly) |
| Tunnel path (`_forward_to_local`) | looks for `duration_seconds` | `X-Duration-Seconds` |
| Slim handler | `duration_s` | (same as RunPod handler) |

If the local GPU server returns `duration_s` (matching RunPod's convention), the tunnel path will silently return `X-Duration-Seconds: 0` to callers.

### 2.6 Delete prompt endpoint — REST vs RPC split

| Component | Method + Path |
|---|---|
| relay-api.yaml contract | `DELETE /api/v1/voices/prompts/{name}` |
| `remote_relay.py` (registered) | `DELETE /api/v1/voices/prompts/{name}` ✓ |
| `runpod_handler.py` ROUTES | `POST /api/v1/voices/prompts/delete` ✗ |

The relay correctly forwards to `DELETE /api/v1/voices/prompts/{name}`, but the RunPod handler only listens for `POST /api/v1/voices/prompts/delete`. Delete via RunPod will always return `{"error": "Unknown endpoint: /api/v1/voices/prompts/..."}`.

### 2.7 `runpod_slim.py` vs `runpod_handler.py` — incompatible endpoint schemes

| Operation | `runpod_handler.py` | `runpod_slim.py` |
|---|---|---|
| Create clone prompt | `POST /api/v1/voices/clone-prompt` | `POST /api/v1/voices/clone-prompt/create` |
| Synthesize with prompt | `POST /api/v1/tts/clone-prompt` | `POST /api/v1/tts/clone-prompt/synthesize` |
| List prompts | `GET /api/v1/voices/prompts` | Not supported |
| Cast/batch | Fully implemented | Not supported |

The slim handler cannot serve any request that `runpod_handler.py` would route correctly (and vice versa for the `/create` and `/synthesize` suffixes). If the relay routes to a RunPod endpoint running the slim handler, all clone-prompt operations will return "Unknown endpoint."

---

## 3. Missing Contracts

These components are real, active, and have no contract at all:

| Component | File(s) | Why it needs a contract |
|---|---|---|
| **Local GPU server** | Presumably `server/local_server.py` or similar | The relay forwards all requests to it. Its endpoint surface, request/response shapes, and auth model must be specified — currently inferred only from how the relay calls it. |
| **PromptStore** | `server/prompt_store.py` | Used by `runpod_handler.py` with `save_prompt`, `load_prompt`, `list_prompts`, `search_prompts`, `list_characters`, `delete_prompt`. Storage format (filesystem? SQLite?), serialization, and locking behavior are opaque. |
| **TunnelServer** | `server/tunnel.py` | Core transport layer. Message framing, request/response correlation, connection lifecycle, and max message size are undocumented. The relay references `_pending_requests` directly. |
| **EmotionPresets** | `server/emotion_presets.py` | Referenced by both RunPod handlers. `EMOTION_PRESETS`, `MODE_PRESETS`, `build_casting_batch()`, `BatchDesignItem` are all used without any documented schema. |
| **AuthManager** | `server/auth.py` | Auth is a security-critical component. Key format, rotation, multi-key support, and timing-safe comparison behavior should be specified. |
| **Config schema** | `server/config.py` | `ENABLED_MODELS`, `MODEL_HF_IDS`, `CUDA_DEVICE`, `VOICES_DIR` are used throughout. No schema, defaults, or validation rules documented. |
| **`runpod_slim.py`** | `server/runpod_slim.py` | Slim and full handler have different capabilities. There's no contract stating which is the canonical RunPod deployment, what its limitations are, or when to use each. |

---

## 4. Architectural Concerns

### 4.1 Single point of failure: WebSocket tunnel

The entire GPU path runs over **one persistent WebSocket connection** (`TunnelServer`). If that connection drops mid-request, all in-flight requests fail. There's no reconnection logic on the relay side (the GPU machine reconnects, but in-flight requests are lost). At high load, a single slow TTS synthesis (30+ seconds) blocks the tunnel if requests are serialized.

**Risk:** High. Any network hiccup between the droplet and the GPU machine causes full service degradation.

### 4.2 Two RunPod handlers, no deployment policy

`runpod_handler.py` (full) and `runpod_slim.py` (inference only) coexist with incompatible endpoint paths, different capability sets, and no documentation on which to deploy. The relay's `_forward_with_fallback` sends the same request regardless of which handler is running on RunPod. Half the operations will silently fail depending on which handler was deployed.

### 4.3 Lazy init race condition (`runpod_handler.py`)

```python
if engine is None and init_error is None:
    init()
```

If two RunPod requests arrive in the same worker process before init completes (possible with concurrent warm requests), both will call `init()`. This isn't thread-safe. In Python's asyncio this is less risky, but `runpod.serverless` may use threads. The `init_done` guard in `runpod_slim.py` is slightly better but not atomic either.

### 4.4 Voice package sync is in-memory only

`handle_sync_packages` downloads all voice packages from the GPU server but stores them only in memory (`logger.info(...)` is the only action taken on the received `packages` dict). After relay restart, all synced voice data is lost. The comment `# could persist to disk` confirms this is unfinished.

### 4.5 `gc.collect()` calls in hot path

Both RunPod handlers call `gc.collect()` after every synthesis. On CPython with large numpy arrays this can take tens of milliseconds and blocks the event loop (in the sync handler context). This is a latency landmine under load.

### 4.6 Unauthenticated debug surface (security)

As noted in §1.2: `/api/v1/debug` and `/ws/debug` are publicly accessible on the relay's port with no auth. `/ws/debug` provides a **live stream of all internal events** including request timing, body sizes, and connection state. An attacker can use this to fingerprint usage patterns or confirm the relay is live before targeting it.

### 4.7 No contract for what "local server" actually is

The relay blindly forwards HTTP requests to the GPU machine's local server over the tunnel. If the local server changes its API paths, adds auth, or changes response formats, the relay breaks silently. There is no versioning, no capability negotiation, and no health-check that validates path compatibility.

### 4.8 `AioHTTPWebSocketAdapter` polling loop

The `recv()` method in the adapter uses `asyncio.wait_for(..., timeout=5.0)` in a `while True` loop. Under sustained load with slow GPU responses, this will generate spurious timeout-and-retry cycles, adding noise to connection state tracking and potentially masking real disconnections.

---

## 5. Recommended Fixes (Prioritized)

### P0 — Correctness bugs (will crash or corrupt output)

1. **Fix argument order in `runpod_slim.py`** `/api/v1/tts/synthesize` handler:
   ```python
   # Current (wrong):
   wav_data, sr = engine.generate_voice_clone(ref_audio, ref_text, text, language)
   # Fixed:
   ref_audio_b64 = base64.b64encode(ref_audio).decode()
   wav_data, sr = engine.generate_voice_clone(text, ref_audio_b64, ref_text, language)
   ```

2. **Fix `create_clone_prompt` calls in both handlers** — re-encode bytes to base64 before calling engine; remove `name` from the positional args (engine doesn't take it):
   ```python
   # In both handlers, after decoding audio:
   audio_bytes = base64.b64decode(body["audio"])
   ref_audio_b64 = base64.b64encode(audio_bytes).decode()  # re-encode for engine
   prompt_data = engine.create_clone_prompt(ref_audio_b64, body.get("ref_text", ""))
   # store name separately via prompt_store.save_prompt(body["name"], prompt_data, ...)
   ```

3. **Fix `NameError` in `runpod_handler.py` `handle_batch_design`** — `audio_data` → `audio_bytes`. Also revisit the logic: passing synthesized output as reference audio is semantically wrong.

4. **Fix or remove `generate_with_saved_voice`** — either correct the model API kwarg (`ref_audio=` not `reference_audio=`) or delete the method and update callers.

### P1 — Security

5. **Add auth to debug endpoints** — apply `_require_auth` to `handle_debug_http` and `handle_debug_ws`, or restrict to localhost-only bindings. Debug endpoints should not be on the public port.

### P2 — Interface alignment

6. **Unify RunPod handler endpoint paths** — pick one scheme and apply it to both handlers:
   - `POST /api/v1/voices/clone-prompt` (no `/create` suffix) — matches relay contract
   - `POST /api/v1/tts/clone-prompt` (no `/synthesize` suffix) — matches relay contract
   - Document which handler is the canonical RunPod deployment

7. **Fix delete prompt routing in `runpod_handler.py`** — add `DELETE /api/v1/voices/prompts/{name}` to ROUTES (extract name from endpoint path), not `POST /api/v1/voices/prompts/delete`.

8. **Standardize audio response field to `duration_s`** — update `_forward_to_local` in `remote_relay.py` to look for `duration_s` (matching RunPod convention), or define `duration_seconds` everywhere and update RunPod handlers.

### P3 — Contract updates

9. **Update `tts-engine.yaml`**:
   - Fix `generate_voice_clone` param: `ref_audio_path` → `ref_audio_b64`
   - Fix `create_clone_prompt` signature: remove `name`/`metadata`, add `x_vector_only_mode`
   - Add undocumented methods: `generate_custom_voice`, `list_voices`, `get_health`
   - Remove or annotate `generate_with_saved_voice` as deprecated/broken

10. **Update `relay-api.yaml`**:
    - Add all missing endpoints (see §1.2 table)
    - Mark debug endpoints as `auth: none (internal)` or add auth requirement
    - Expand clone-prompt request body with full metadata fields

11. **Write contracts for**: local GPU server API, PromptStore, TunnelServer protocol, EmotionPresets schema, AuthManager, config schema, RunPod handler selection policy.

### P4 — Architecture hardening

12. **Implement persistent voice package storage on relay** — complete the `handle_sync_packages` implementation to write packages to disk.

13. **Add init guard for thread safety** — use `threading.Lock` or an async lock around the init check in both RunPod handlers.

14. **Move `gc.collect()` out of hot path** — schedule it as a background task or periodic cleanup rather than blocking after every synthesis.

15. **Add tunnel capability negotiation** — when a GPU client connects, have it advertise its API version and supported endpoints. The relay should reject mismatched clients rather than silently failing.

---

## Appendix: Component Dependency Map (Actual)

```
External Clients
    │
    ▼
remote_relay.py  ←── config.yaml, auth.py
    │   │
    │   ├──[tunnel]──► local GPU server (no contract)
    │   │                   └── tts_engine.py
    │   │                   └── prompt_store.py
    │   │
    │   └──[RunPod]──► runpod_handler.py  ─── tts_engine.py
    │                                     ─── prompt_store.py
    │                                     ─── emotion_presets.py
    │
    └── runpod_client.py  (manages RunPod HTTP)

runpod_slim.py ─── tts_engine.py
    (separate deployment, no prompt_store, incompatible paths)
```

**Docs/architecture.md** and **docs/requirements.md** are currently unfilled templates and provide no design guidance. These should be completed before the next feature cycle.
