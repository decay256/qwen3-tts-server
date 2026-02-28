# QA Review — Qwen3-TTS Server

**Reviewer:** QA Engineer Agent  
**Date:** 2026-02-28  
**Scope:** `tests/`, `server/tts_engine.py`, `server/remote_relay.py`, `server/runpod_client.py`, `web/app/routes/`, `docs/requirements.md`, `contracts/tts-engine.yaml`

---

## Executive Summary

The test suite has solid unit coverage of isolated modules (tunnel protocol, auth, voice manager, emotion presets, prompt store) but has **critical gaps in integration coverage** and **multiple mock/real interface mismatches** that will hide real bugs. The requirements document is essentially empty, making formal traceability impossible. Two contract mismatches in `tts-engine.yaml` are actively wrong relative to the implementation.

---

## 1. Requirements Coverage Gaps

### Requirements Document State

`docs/requirements.md` contains only a placeholder FR-001 with no content and a partial NFR table. There are no formally specified Functional Requirements to trace. The analysis below uses observable behaviour from the codebase as the de-facto requirements.

### Untested Functional Areas

| Area | Missing Tests |
|------|--------------|
| **Web app auth routes** | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/reset-request`, `POST /auth/reset-confirm`, `POST /auth/verify-email` — zero tests |
| **Web app account routes** | `GET /api/v1/account`, `POST /api/v1/account/change-password`, `POST /api/v1/account/change-email`, `POST /api/v1/account/delete` — zero tests |
| **Web app character routes** | `POST /api/v1/characters`, `GET /api/v1/characters`, `GET /api/v1/characters/{id}`, `PATCH /api/v1/characters/{id}`, `DELETE /api/v1/characters/{id}` — zero tests |
| **Web app TTS proxy routes** | `POST /api/v1/tts/voices/design`, `POST /api/v1/tts/voices/cast`, `POST /api/v1/tts/voices/design/batch`, `POST /api/v1/tts/synthesize`, `POST /api/v1/tts/voices/refine`, etc. — zero tests |
| **RunPodClient** | `runsync()`, `run_async()`, `poll_status()`, `health()` — no unit tests at all |
| **RunPod fallback path** | `RemoteRelay._forward_with_fallback()` when tunnel is disconnected — not covered in `test_http_api.py` (tests only inject mock tunnel) |
| **mp3/ogg audio encoding** | `wav_to_format()` only tested for `fmt="wav"`. mp3/ogg paths (including Windows libmp3lame → mp3 codec fallback) are untested |
| **`generate_custom_voice`** | TTSEngine method has no tests at all |
| **`generate_with_saved_voice`** (legacy) | Legacy method untested; also has a bug (passes `reference_audio=` to model but model API expects `voice_clone_prompt=`) |
| **Text length limits** | `MAX_TEXT_LENGTH` config exists; no test that synthesis refuses over-long input |
| **Rate limiting** | `RATE_LIMIT` config exists; no test that rate limit enforcement works |
| **Batch design & batch clone-prompt** | End-to-end batch operations untested through local_server or relay |
| **Voice package export/import via relay** | `handle_export_package`, `handle_import_package`, `handle_sync_packages` — relay handlers not tested |
| **Debug endpoints** | `handle_debug_http`, `handle_debug_ws`, `debug_event()` — untested |
| **`AioHTTPWebSocketAdapter`** | The ws adapter wrapping aiohttp→websockets interface is untested |
| **`chunk_text` through synthesis** | Chunking is unit-tested in isolation but there is no test that long text is chunked and audio concatenated correctly at the synthesis level |
| **LLM refinement service** | `web.app.services.llm_refine.refine_prompt` is untested |
| **`chunk_text` with CJK punctuation** | `。！？` delimiters in regex but no test with CJK text |

### NFR Coverage

| NFR | Target | Test? |
|-----|--------|-------|
| API latency p99 | 200ms | ❌ No latency assertions anywhere |
| Availability 99.9% | — | ❌ No uptime/resilience tests |
| Security (OWASP Top 10) | — | ❌ No injection, CSRF, input-sanitization tests |
| Observability | Logs + metrics | ❌ Log output not asserted |

---

## 2. Mock Accuracy Issues

These are the highest-priority findings. Mock/real interface mismatches cause tests to pass against a contract that doesn't match the actual code.

### 2.1 Contract File vs. Implementation (HIGH)

**`contracts/tts-engine.yaml` `generate_voice_clone`:**

```yaml
# CONTRACT says:
args:
  ref_audio_path: str  # "path to reference WAV"
```

```python
# REAL implementation (tts_engine.py):
def generate_voice_clone(self, text, ref_audio_b64, ref_text="", language="Auto", x_vector_only_mode=False):
```

The contract specifies a **file path** but the real method takes **base64-encoded audio**. The method internally writes a temp file. Any consumer relying on the contract to pass a path will fail.

---

**`contracts/tts-engine.yaml` `create_clone_prompt`:**

```yaml
# CONTRACT says:
args:
  ref_audio_b64: str
  name: str        # ← does not exist in real engine
  ref_text: str
  metadata: dict   # ← does not exist in real engine
```

```python
# REAL implementation (tts_engine.py):
def create_clone_prompt(self, ref_audio_b64, ref_text="", x_vector_only_mode=False):
    # No 'name' parameter. Name is handled by PromptStore, not TTSEngine.
```

The contract says TTSEngine names and tags the prompt. The real engine just creates the raw prompt item; naming is a PromptStore concern. Any code calling `engine.create_clone_prompt(name="foo")` will crash with `TypeError`.

---

### 2.2 MockTTSEngine in test_runpod_slim.py (HIGH)

```python
# MOCK (test_runpod_slim.py):
def generate_voice_clone(self, ref_audio, ref_text, text, language="Auto"):
    # arg order: ref_audio, ref_text, text

# REAL engine (tts_engine.py):
def generate_voice_clone(self, text, ref_audio_b64, ref_text="", language="Auto", x_vector_only_mode=False):
    # arg order: text, ref_audio_b64, ref_text
```

The mock accepts positional arguments in a different order and uses `ref_audio` instead of `ref_audio_b64`. If `runpod_slim` calls the engine positionally, these tests will pass but the real handler will pass wrong arguments to a real engine.

```python
# MOCK:
def create_clone_prompt(self, ref_audio, name, ref_text=""):
    # Has 'name' parameter — doesn't exist on real engine

# REAL:
def create_clone_prompt(self, ref_audio_b64, ref_text="", x_vector_only_mode=False):
    # No 'name' parameter
```

Same issue: the mock's `name` param means the test covers a signature that will fail at runtime.

---

### 2.3 test_local_server.py mock_engine vs. generate_voice_design call signature

```python
# MOCK setup:
engine.generate_voice_design.return_value = (fake_wav, 24000)

# REAL engine call in generate_voice_design:
wavs, sr = model.generate_voice_design(text=text, language=language, instruct=description)
return wavs[0], sr  # ← returns wavs[0], not wavs
```

The mock correctly returns a 2-tuple `(ndarray, int)` which matches. However, the `test_handle_design_returns_audio` test patches `server.tts_engine.wav_to_format` at the module level, not at the call site inside LocalServer. If LocalServer imports `wav_to_format` locally (e.g., `from server.tts_engine import wav_to_format`), the patch target may be wrong and the test may not actually intercept the call. Verify import style in `local_server.py`.

---

### 2.4 PromptStore MockPromptItem vs. VoiceClonePromptItem (MEDIUM)

`test_prompt_store.py` uses a locally-defined `MockPromptItem` dataclass with fields: `ref_code`, `ref_spk_embedding`, `x_vector_only_mode`, `icl_mode`, `ref_text`. The actual `VoiceClonePromptItem` from `qwen_tts` is never validated. If `qwen_tts` adds required fields or changes field names, `PromptStore` will fail to serialize/deserialize and no test will catch it.

The `torch.load` mock in `test_load_prompt_from_disk` returns a plain dict, but the real `load_prompt` must reconstruct a `VoiceClonePromptItem` from that dict. This reconstruction logic is not tested.

---

## 3. Integration Test Gaps

### 3.1 Full Tunnel Request/Response Cycle

`test_http_api.py` tests the relay handlers with `relay.tunnel_server.send_request = AsyncMock(return_value=...)`. This skips the actual WebSocket message framing, serialization, and the `TunnelServer.handle_connection` logic. There is no test where:

1. A real WebSocket connection is established to the TunnelServer
2. Auth handshake completes
3. A request is forwarded through the tunnel
4. A response comes back and is decoded correctly

### 3.2 Clone Voice Full Workflow

No test covers the end-to-end clone workflow:
1. Upload reference audio → `POST /api/v1/tts/clone`
2. Optionally create a persistent prompt → `POST /api/v1/voices/clone-prompt`
3. Synthesize with saved prompt → `POST /api/v1/tts/clone-prompt`

The individual steps are unit-tested in isolation but the data flow between them (base64 encoding, temp file creation, prompt serialization, prompt reuse) is not integration-tested.

### 3.3 RunPod Fallback Flow

When the GPU tunnel disconnects, `_forward_with_fallback` should route to RunPod. No test covers:
- Tunnel connected → tunnel disconnects mid-traffic → RunPod picks up
- RunPod returns `FAILED` status → relay returns appropriate HTTP error
- RunPod cold-start: `/runsync` times out → falls back to `/run` + polling

### 3.4 Voice Package Round-Trip

Export a voice from the GPU machine, transfer through the relay, import on another machine. The relay handlers (`handle_export_package`, `handle_import_package`, `handle_sync_packages`) are completely untested. The `VoicePackager` unit tests work in isolation but the relay transport layer (base64 over tunnel, content-type handling) is not covered.

### 3.5 Web App → Relay → GPU → Audio Pipeline

No test covers the full stack from `web/app/routes/tts.py` → `tts_proxy.tts_post()` → relay HTTP → tunnel → GPU `LocalServer` → TTS engine → audio bytes back to browser. This is the primary user-facing flow.

### 3.6 Reconnection Under Load

`test_reconnection_timing.py` tests delay calculation but not actual reconnection behavior: what happens to in-flight requests when the tunnel drops? Does `TunnelServer._pending_requests` get resolved with errors? Do relay clients get 503 or hang?

---

## 4. Fragile Tests

Tests likely to break on legitimate refactors:

### 4.1 Hardcoded Preset Counts (test_emotion_presets.py)

```python
assert len(EMOTION_PRESETS) == 9
assert len(MODE_PRESETS) == 13
# Expected batch count hardcoded: 9*2 + 15 = 33
```

Adding any emotion or mode breaks these. Use `len(EMOTION_ORDER)` and `len(MODE_ORDER)` in assertions, not magic numbers.

### 4.2 Private State Access in test_http_api.py

```python
relay.tunnel_server._clients["fake"] = MagicMock()
```

Directly writes to `TunnelServer._clients` (private dict). Any refactor of client tracking (e.g., renaming, using a set, or adding a `register_client()` method) will silently break this without compile-time warning.

### 4.3 Timing-Dependent Async Tests (test_tunnel_v2.py)

```python
await asyncio.sleep(0.1)
assert client.state == ConnectionState.AUTHENTICATED
```

`asyncio.sleep(0.1)` is used to wait for async tasks to progress. This is inherently flaky on slow CI machines. Should use `asyncio.wait_for()` with event/condition signaling or mock the websocket iteration to complete synchronously.

### 4.4 Module-Level State Mutation (test_runpod_slim.py)

```python
slim.engine = cls.mock_engine
slim.init_done = True
```

`setUpClass` mutates module globals. If tests run in a different order or another test imports `runpod_slim`, state leaks. The `TestHandlerLazyInit` saves/restores state in a `try/finally` block — good — but `TestRunpodSlimHandler` does not restore the original values.

### 4.5 Status Code `None` Assertion (test_local_server.py)

```python
assert resp.status_code == 200 or resp.status_code is None  # None means 200 default
```

Testing for `None` as a valid status code is a hidden contract with the implementation. If the response is ever explicitly set to 200 instead of left as None, this comment-based contract is invisible. Should assert `== 200` only, and fix the implementation to always set an explicit status code.

### 4.6 Patch Target May Be Wrong (test_local_server.py)

```python
with patch("server.tts_engine.wav_to_format", return_value=b"fake-audio"):
```

If `local_server.py` does `from server.tts_engine import wav_to_format`, this patch target is wrong — it patches the original module after the reference was already imported. Should patch `server.local_server.wav_to_format` instead. Whether this is fragile depends on the import style in `local_server.py`.

### 4.7 Convoluted Mock in test_load_prompt_from_disk (test_prompt_store.py)

```python
loaded = store.load_prompt.__wrapped__(store, "disk_voice") \
    if hasattr(store.load_prompt, '__wrapped__') else mock_load("disk_voice")
```

This `__wrapped__` check attempts to bypass caching decorators but will silently fall back to calling `mock_load("disk_voice")` which always returns a non-None value — so the test cannot actually fail. The test is effectively a no-op for the disk-load path.

---

## 5. Recommended Test Plan (Prioritized)

### P0 — Fix Before Next Release

**5.1 Fix Contract Mismatches**
- Update `contracts/tts-engine.yaml` `generate_voice_clone` to use `ref_audio_b64` not `ref_audio_path`
- Update `contracts/tts-engine.yaml` `create_clone_prompt` to remove `name` and `metadata`, add `x_vector_only_mode`
- Add a contract compliance test that imports the real engine and verifies method signatures match the contract (use `inspect.signature`)

**5.2 Fix MockTTSEngine in test_runpod_slim.py**
- Align `generate_voice_clone(text, ref_audio_b64, ref_text, language, x_vector_only_mode)` 
- Align `create_clone_prompt(ref_audio_b64, ref_text, x_vector_only_mode)` — remove `name`
- Add a test that verifies `MockTTSEngine` method signatures match `TTSEngine` using `inspect`

**5.3 Add RunPodClient Unit Tests** (`tests/test_runpod_client.py`)
```
- test_runsync_completed: mock aiohttp session, COMPLETED response returned directly
- test_runsync_cold_start: /runsync returns IN_QUEUE → falls through to polling
- test_runsync_timeout: /runsync times out → run_async() called, polling starts
- test_poll_until_complete: simulates 3 IN_PROGRESS then COMPLETED
- test_failed_status: FAILED response propagates correctly
- test_no_job_id: handles missing id gracefully
```

**5.4 Add RunPod Fallback Tests in test_http_api.py**
```
- test_synthesize_uses_runpod_when_no_tunnel: no clients, runpod configured → forwards to runpod
- test_synthesize_runpod_returns_failed: runpod FAILED → 502 response
- test_synthesize_runpod_timeout: asyncio.TimeoutError → 504
- test_synthesize_runpod_audio_response: COMPLETED with audio → binary audio/wav response
```

---

### P1 — High Value, Tackle This Sprint

**5.5 Add Web App Auth Route Tests** (`tests/test_web_auth.py`)

Use FastAPI's `TestClient` with an in-memory SQLite database:
```
- test_register_creates_user
- test_register_duplicate_email_409
- test_register_short_password_400
- test_login_success_returns_tokens
- test_login_wrong_password_401
- test_login_inactive_user_403
- test_refresh_valid_token
- test_refresh_expired_token_401
- test_reset_request_unknown_email_no_leak (always 200)
- test_reset_confirm_sets_new_password
- test_verify_email_marks_verified
```

**5.6 Add Web App Account Route Tests** (`tests/test_web_account.py`)
```
- test_get_account_returns_user_info
- test_change_password_correct_current
- test_change_password_wrong_current_400
- test_change_email_success
- test_change_email_taken_409
- test_delete_account_removes_user_and_characters
```

**5.7 Add Web App Character Route Tests** (`tests/test_web_characters.py`)
```
- test_create_character
- test_list_characters_only_own
- test_get_character_404_other_user
- test_update_character_name
- test_delete_character
```

**5.8 Fix Fragile Preset Count Tests**

Replace:
```python
assert len(EMOTION_PRESETS) == 9
```
With:
```python
assert len(EMOTION_PRESETS) == len(EMOTION_ORDER)
assert all(name in EMOTION_PRESETS for name in EMOTION_ORDER)
```

---

### P2 — Important, Schedule Next Month

**5.9 Tunnel Integration Test** (`tests/test_tunnel_integration.py`)

Use actual `websockets` server in-process:
```
- test_full_auth_handshake: TunnelClient connects to TunnelServer, AUTH sent, AUTH_OK received
- test_request_forwarded_and_response_received: mock request_handler on client side
- test_tunnel_reconnects_after_disconnect: drop connection, verify reconnect within 15s
- test_pending_requests_rejected_on_disconnect: in-flight request gets ConnectionError, not hang
```

**5.10 wav_to_format MP3 Tests** (add to `test_tts.py`)
```
- test_mp3_format: mock subprocess.run, verify ffmpeg called with libmp3lame
- test_mp3_fallback_codec: CalledProcessError on libmp3lame, verify fallback to mp3 codec
- test_ogg_format: verify libvorbis codec used
- test_ffmpeg_timeout: subprocess.TimeoutExpired propagated correctly
```

**5.11 Synthesis Rate Limiting & Input Validation Tests**
```
- test_text_too_long_rejected: POST with text > MAX_TEXT_LENGTH → 400
- test_rate_limit_enforced: N+1 requests within window → 429
- test_empty_text_rejected: empty string → 400
```

**5.12 Clone Workflow Integration Test** (no GPU needed, mock engine)

Test the full data flow:
```
1. POST /api/v1/tts/clone (with base64 WAV) → voice stored
2. GET /api/v1/tts/voices → voice appears in list
3. POST /api/v1/tts/synthesize with voice_id → audio returned
4. DELETE /api/v1/tts/voices/{id} → voice gone
```

**5.13 Voice Package Relay Tests** (add to `test_http_api.py`)
```
- test_export_package_forwarded: relay fetches package from local, returns as zip download
- test_import_package_forwarded: multipart upload forwarded through tunnel
- test_import_package_raw_binary: raw binary body also accepted
- test_sync_packages_returns_count
```

**5.14 Fix Timing-Dependent Tunnel v2 Tests**

Replace `asyncio.sleep(0.1)` with proper event signaling:
```python
# Instead of:
await asyncio.sleep(0.1)
assert client.state == ConnectionState.AUTHENTICATED

# Use:
async def wait_for_state(client, state, timeout=1.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if client.state == state:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"State never reached {state}, got {client.state}")
```

---

### P3 — Nice to Have

**5.15 AioHTTPWebSocketAdapter Tests**
```
- test_recv_queues_messages
- test_send_when_closed_raises
- test_close_marks_closed
- test_async_iter_stops_on_close
```

**5.16 LLM Refine Service Tests** (mock LLM API)
```
- test_refine_prompt_valid_response
- test_refine_prompt_invalid_llm_response_raises_ValueError
- test_refine_prompt_llm_error_propagates
```

**5.17 generate_custom_voice Tests**
```
- test_generate_custom_voice_calls_model
- test_generate_custom_voice_no_instruct
- test_generate_custom_voice_model_not_loaded_raises
```

**5.18 Prompt Disk Load Test (rewrite)**

The `test_load_prompt_from_disk` test is broken (see §4.7). Rewrite it:
```python
def test_load_prompt_from_disk(store, tmp_path):
    """Clears cache and reloads from disk."""
    item = MockPromptItem(ref_text="disk")
    store.save_prompt("disk_voice", item)
    store._cache.clear()  # evict from cache
    
    # Now load should hit disk
    loaded = store.load_prompt("disk_voice")
    assert loaded is not None
    assert loaded.ref_text == "Hello world"  # from mock_torch.load return value
```

**5.19 Contract Compliance Test** (`tests/test_contract_compliance.py`)

```python
import inspect
from server.tts_engine import TTSEngine

def test_generate_voice_design_signature():
    sig = inspect.signature(TTSEngine.generate_voice_design)
    params = list(sig.parameters.keys())
    assert "text" in params
    assert "description" in params
    assert "language" in params

def test_generate_voice_clone_signature():
    sig = inspect.signature(TTSEngine.generate_voice_clone)
    params = list(sig.parameters.keys())
    assert "text" in params
    assert "ref_audio_b64" in params  # NOT ref_audio_path
    assert "ref_text" in params
```

---

## Summary Table

| Finding | Severity | Action |
|---------|----------|--------|
| Contract `generate_voice_clone` uses wrong arg name | 🔴 HIGH | Fix contract + add compliance test |
| Contract `create_clone_prompt` has nonexistent `name` param | 🔴 HIGH | Fix contract |
| MockTTSEngine arg order/names wrong in test_runpod_slim | 🔴 HIGH | Fix mock signatures |
| Zero tests for RunPodClient | 🔴 HIGH | Add test_runpod_client.py (P0) |
| Zero tests for RunPod fallback path in relay | 🔴 HIGH | Add to test_http_api.py (P0) |
| Zero tests for web app routes (auth, account, characters) | 🟠 MED | Add test_web_*.py (P1) |
| Hardcoded preset counts in test_emotion_presets | 🟠 MED | Fix assertions (P1) |
| Private `_clients` access in test_http_api | 🟠 MED | Refactor test (P2) |
| Timing-dependent asyncio.sleep() tests | 🟠 MED | Use event signaling (P2) |
| Module-level state mutation in test_runpod_slim | 🟠 MED | Restore state in teardown (P1) |
| test_load_prompt_from_disk is a no-op | 🟠 MED | Rewrite test (P3) |
| No integration test for full tunnel cycle | 🟡 LOW | Add test_tunnel_integration.py (P2) |
| No wav_to_format mp3/ogg tests | 🟡 LOW | Extend test_tts.py (P2) |
| No rate limiting / input length tests | 🟡 LOW | Add validation tests (P2) |
| status_code `is None` assertion | 🟡 LOW | Fix explicit code (P1) |
| Legacy generate_with_saved_voice has bug + no tests | 🟡 LOW | Fix or remove (P3) |
