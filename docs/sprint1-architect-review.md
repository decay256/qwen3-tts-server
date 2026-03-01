# Architect Review — Sprint 1

**Date:** 2026-03-01  
**Reviewer:** Eigen (Architect Agent)  
**Scope:** Post-hoc review of PR #14 (`sprint1/cold-start-ux`) and PR #15 (`sprint1/preview-e2e`)  
**Baseline:** `docs/architect-review.md` (2026-02-28)

---

## Executive Summary

Both PRs are architecturally sound and respect the existing system design. PR #15 fixes a real silent data loss bug correctly. PR #14 implements a well-structured cold-start UX pattern with proper abort/cleanup mechanics. One contract gap requires updating: `relay-api.yaml` must document the new optional fields on `POST /api/v1/voices/design`. One design decision should be recorded: the "Cast" operation uses the design endpoint with inline prompt creation rather than a two-step flow.

No architectural violations. No new coupling. No SoC breaches.

---

## PR #14 — Frontend Cold-Start UX (`sprint1/cold-start-ux`)

**Changes:** `CharacterPage.tsx`, `App.css` — elapsed timer, 15s cold-start warning, 180s hard timeout with retry/cancel.

### Contract Compliance

No API contracts affected. Changes are purely frontend (UI state, CSS). No new network endpoints, no new request shapes. ✓

### Architecture Assessment

**Generation lifecycle pattern is correct.** The `startGeneration` / `stopGeneration` / `cancelGeneration` trio maps cleanly onto request lifecycle:
- `AbortController` is created per-request and stored in a ref (not state) — correct, avoids stale closure issues
- `wasTimedOutRef` is a ref rather than state — correct, must be readable synchronously in the `catch` block without triggering a re-render cycle
- Timeout fires at 180s, sets `wasTimedOutRef.current = true`, then aborts — this ordering is critical for the catch block to distinguish hard timeout from user cancel; it's done right
- `finally { stopGeneration() }` clears both interval and timeout regardless of outcome — no timer leaks

**Abort handling is correct.** The `AbortError` catch distinguishes:
1. Hard 180s timeout → sets error + `retryTarget` (user can retry)
2. User-initiated cancel → stays silent (user chose to stop)

This is the right UX model for GPU cold-start scenarios.

**Retry state is safe.** `retryTarget` holds `{ row: PresetRow; op: 'preview' | 'cast' }`. The row reference is to a stable object in local component state. Invoking `previewPreset(row)` or `castSingle(row)` from the retry handler re-triggers the full flow, including a fresh AbortController. ✓

### Minor Concerns (Non-blocking)

**1. Concurrent generation guard is implicit, not explicit.**  
`startGeneration` does not abort a previous in-flight request before starting a new one. It overwrites `abortCtrlRef.current`, making the old controller unreachable. In practice the UI likely prevents concurrent generation (buttons disabled while `generating !== null`), but the cancellation path for the old request becomes inaccessible if two requests somehow overlap. A defensive `abortCtrlRef.current?.abort()` at the top of `startGeneration` would make this explicit and safe.

**2. Magic numbers.**  
`180_000` (hard timeout) and `15` (cold-start threshold) are inline literals. These should be named constants (`GENERATION_TIMEOUT_MS`, `COLD_START_THRESHOLD_S`) either at module top or in a shared config file. Makes future tuning and testing easier.

**3. Single hook candidate.**  
The generation lifecycle logic (`startGeneration`, `stopGeneration`, `cancelGeneration`, three refs, two state variables) is self-contained and could be extracted into a `useGeneration()` custom hook if `CharacterPage` grows. Not required now — the component is the only consumer — but worth flagging for when the pattern is replicated.

---

## PR #15 — Backend E2E Proxy Fix (`sprint1/preview-e2e`)

**Changes:** `web/app/routes/tts.py` (`DesignRequest` model), new `web/tests/test_e2e_proxy_chain.py`.

### Bug Fixed

`DesignRequest` previously modeled only `{ text, instruct, language, format }`. When the frontend sent `create_prompt`, `prompt_name`, `tags` (for the Cast operation), Pydantic silently dropped them. The relay never received them; the GPU server never saved the clone prompt. Voice casts appeared to succeed but produced no persisted prompt.

Fix: add the three fields as `Optional` with `None` defaults + `exclude_none=True` on `model_dump()`. Clean and correct.

### Contract Compliance

**⚠️ Contract gap — relay-api.yaml needs updating.**

The existing `relay-api.yaml` contract for `POST /api/v1/voices/design` documents only:
```yaml
request:
  text: string (required)
  instruct: string (required)
  language: string (default "English")
```

The fix adds three new optional fields that now pass through to the relay:
- `create_prompt: bool`
- `prompt_name: str`
- `tags: list[str]`

These fields are real, actively used, and consumed by the GPU handler. The contract is now stale. **Update required** (see §4 below).

### Design Decision — Multipurpose Design Endpoint

The Cast operation reuses `POST /api/v1/voices/design` with `create_prompt=True` rather than using the separate `POST /api/v1/voices/clone-prompt` endpoint. This is an intentional inline approach: generate audio + create prompt in a single round-trip.

**Tradeoffs of this approach:**
- ✅ Single network call from frontend (simpler)
- ✅ No two-phase state management in the UI
- ✅ Relay can atomically handle both synthesis and prompt storage on the GPU
- ⚠️ `POST /api/v1/voices/design` now has a conditional side effect (prompt persistence) depending on payload shape — this is not obvious from the endpoint name
- ⚠️ The relay contract lists `POST /api/v1/voices/clone-prompt` as the dedicated endpoint for clone prompt creation; the two endpoints now overlap in capability

This is a valid design choice for the current scale and workflow (Cast is always synthesis + save). It should be documented in the contract so future consumers don't hit the same silent-drop bug.

### Architecture Assessment

**Web backend is still a thin proxy.** The route handler does auth, model validation, and delegation to `tts_proxy.tts_post`. No business logic was added. SoC is preserved. ✓

**`exclude_none=True` is correct.** Plain preview calls won't include `create_prompt`, `prompt_name`, or `tags` in the relay body. This keeps the relay body clean and backward-compatible with relay versions that don't yet handle these fields. ✓

**Test coverage is thorough.** `test_e2e_proxy_chain.py` covers:
- Full chain for basic preview (path, body, response fields)
- Language default behavior
- 502 and 504 relay error propagation
- Cast payload pass-through (the bug case)
- Plain preview exclusion of optional fields (`exclude_none=True` behavior)
- Relay path correctness (`/api/v1/voices/design` not `/api/v1/tts/voices/design`)
- Full body transformation

This is the right level of coverage for a proxy bug fix.

---

## 4. Required Contract Updates

### `contracts/relay-api.yaml` — `POST /api/v1/voices/design`

Add optional fields to the request schema:

```yaml
POST /api/v1/voices/design:
  description: >
    Generate a single voice design clip. When create_prompt=true and prompt_name
    are supplied, the GPU handler also persists the generated audio as a named clone
    prompt (used by the Cast button in the UI). This combines synthesis and prompt
    creation in a single call.
  request:
    text: string (required)
    instruct: string (required) — voice description
    language: string (default "English")
    format: string (default "wav")
    create_prompt: bool (optional) — if true, save generated audio as clone prompt
    prompt_name: string (optional, required when create_prompt=true) — prompt name
    tags: list[str] (optional) — metadata tags for the saved prompt
```

No other contracts require updating. The frontend-only changes in PR #14 have no API surface.

---

## 5. Design Decisions to Record

The following decisions emerged from Sprint 1 and should be recorded in the project's decision log (GitHub issues with `decision` label or ADR docs):

**Decision 1: Inline prompt creation on design endpoint**  
Rather than a two-step design → clone-prompt flow, the Cast button triggers a single `POST /api/v1/voices/design` with `create_prompt=true`. Rationale: simpler frontend state machine, fewer round trips, GPU can atomically handle both. Tradeoff: the design endpoint now has conditional side effects.

**Decision 2: Client-side timeout for cold-start**  
Cold-start handling is implemented in the frontend (180s AbortController timeout + retry prompt) rather than the backend (gateway timeout or polling). Rationale: the GPU cold-start duration is variable and can exceed typical HTTP gateway timeouts; frontend polling would require a job-queue model. Tradeoff: the 180s constant lives in UI code and is invisible to API consumers.

**Decision 3: Silent cancel on user abort**  
User-initiated cancellation produces no error message. Only hard timeouts produce an error + retry prompt. Rationale: the user chose to stop; showing an error would be misleading.

---

## 6. Summary

| Item | Status |
|------|--------|
| PR #14 contracts respected | ✓ |
| PR #15 contracts respected | ⚠️ relay-api.yaml needs update (see §4) |
| New coupling introduced | None |
| SoC violations | None |
| Correctness of implementation | ✓ (bug properly fixed, timer mechanics sound) |
| Test coverage | ✓ (comprehensive E2E proxy tests) |
| Action required | Update `contracts/relay-api.yaml` per §4 |
